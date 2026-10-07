"""Anthropic adapter. The system prompt is marked for prompt caching with cache_control."""
from __future__ import annotations

import os
import time

from .base import LLMClient, LLMError, Reply, RetryableError, with_retries


class AnthropicClient(LLMClient):
    name = "anthropic"

    def __init__(self, model_id: str, api_key_env: str = "ANTHROPIC_API_KEY", thinking: dict | None = None,
                 sampling: dict | None = None, timeout_s: float = 120.0, max_retries: int = 6,
                 client=None):
        import anthropic

        self.model_id = model_id
        self.thinking = dict(thinking) if thinking else None       # for example {"type": "enabled", "budget_tokens": 2048}
        self.sampling = dict(sampling or {})                        # temperature, top_p, ... provider defaults when empty
        self.max_retries = max_retries
        key = os.environ.get(api_key_env)
        if client is None and not key:
            raise LLMError(f"{api_key_env} is not set. Put it in .env (see .env.example).")
        self._anthropic = anthropic
        # The SDK retries too. Its retries are turned off so the backoff here is the only one.
        self.client = client or anthropic.Anthropic(api_key=key, timeout=timeout_s, max_retries=0)

    def settings(self) -> dict:
        return {"thinking": self.thinking, "sampling": self.sampling, "cache_control": "ephemeral on system"}

    def complete(self, system: str, user: str, max_tokens: int) -> Reply:
        kwargs: dict = {
            "model": self.model_id,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            **self.sampling,
        }
        if self.thinking:
            kwargs["thinking"] = self.thinking

        def once() -> Reply:
            t0 = time.perf_counter()
            try:
                msg = self.client.messages.create(**kwargs)
            except self._anthropic.RateLimitError as e:
                raise RetryableError(str(e)) from e
            except self._anthropic.APIStatusError as e:
                if e.status_code >= 500 or e.status_code == 429:
                    raise RetryableError(str(e)) from e
                raise LLMError(str(e)) from e
            except self._anthropic.APIConnectionError as e:          # timeouts included
                raise RetryableError(str(e)) from e
            latency = time.perf_counter() - t0
            text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
            u = msg.usage
            read = int(getattr(u, "cache_read_input_tokens", 0) or 0)
            write = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
            return Reply(text=text, input_tokens=int(u.input_tokens) + read + write,
                         output_tokens=int(u.output_tokens), latency_s=latency,
                         cache_read_tokens=read, cache_write_tokens=write,
                         raw={"stop_reason": msg.stop_reason, "id": msg.id})

        return with_retries(once, max_retries=self.max_retries)
