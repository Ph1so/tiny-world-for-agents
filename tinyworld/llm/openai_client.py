"""OpenAI compatible adapter. Covers OpenAI, OpenRouter, Ollama, and anything with the same chat API.

base_url and the name of the api key env var come from configs/models.yaml. OpenAI caches long
prompts on its own (no marker needed); cached tokens are read back from the usage block.
"""
from __future__ import annotations

import os
import time

from .base import LLMClient, LLMError, Reply, RetryableError, with_retries


class OpenAICompatibleClient(LLMClient):
    name = "openai_compatible"

    def __init__(self, model_id: str, base_url: str | None = None, api_key_env: str = "OPENAI_API_KEY",
                 reasoning: dict | None = None, sampling: dict | None = None, timeout_s: float = 120.0,
                 max_retries: int = 6, client=None):
        import openai

        self.model_id = model_id
        self.base_url = base_url
        self.reasoning = dict(reasoning) if reasoning else None   # for example {"reasoning_effort": "low"}
        self.sampling = dict(sampling or {})
        self.max_retries = max_retries
        key = os.environ.get(api_key_env)
        if client is None and not key:
            if base_url and ("localhost" in base_url or "127.0.0.1" in base_url):
                key = "none"                                        # local servers such as Ollama take any key
            else:
                raise LLMError(f"{api_key_env} is not set. Put it in .env (see .env.example).")
        self._openai = openai
        self.client = client or openai.OpenAI(api_key=key, base_url=base_url, timeout=timeout_s, max_retries=0)

    def settings(self) -> dict:
        return {"reasoning": self.reasoning, "sampling": self.sampling, "base_url": self.base_url}

    def complete(self, system: str, user: str, max_tokens: int) -> Reply:
        kwargs: dict = {
            "model": self.model_id,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            **self.sampling,
        }
        if self.reasoning:
            kwargs.update(self.reasoning)

        def once() -> Reply:
            t0 = time.perf_counter()
            try:
                resp = self.client.chat.completions.create(**kwargs)
            except self._openai.RateLimitError as e:
                raise RetryableError(str(e)) from e
            except self._openai.APIStatusError as e:
                if e.status_code >= 500 or e.status_code == 429:
                    raise RetryableError(str(e)) from e
                raise LLMError(str(e)) from e
            except self._openai.APIConnectionError as e:
                raise RetryableError(str(e)) from e
            latency = time.perf_counter() - t0
            choice = resp.choices[0] if resp.choices else None
            text = (choice.message.content or "") if choice else ""
            u = resp.usage
            inp = int(getattr(u, "prompt_tokens", 0) or 0) if u else 0
            out = int(getattr(u, "completion_tokens", 0) or 0) if u else 0
            details = getattr(u, "prompt_tokens_details", None) if u else None
            cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
            return Reply(text=text, input_tokens=inp, output_tokens=out, latency_s=latency,
                         cache_read_tokens=cached,
                         raw={"finish_reason": getattr(choice, "finish_reason", None), "id": getattr(resp, "id", None)})

        return with_retries(once, max_retries=self.max_retries)
