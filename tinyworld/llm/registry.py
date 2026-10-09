"""Named model entries from configs/models.yaml, and the client for each one.

No model id lives in code. A run names a model entry, the entry names the provider and the id.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from .base import LLMClient, Reply

DEFAULT_MODELS_PATH = Path(__file__).resolve().parents[2] / "configs" / "models.yaml"


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    provider: str                                  # anthropic | openai_compatible | mock
    model: str = ""                                # provider model id
    input_per_m: float = 0.0                       # USD per million input tokens
    output_per_m: float = 0.0                      # USD per million output tokens
    cache_read_per_m: float | None = None          # USD per million cached input tokens read (input price when null)
    cache_write_per_m: float | None = None         # USD per million cache write tokens (input price when null)
    max_tokens: int = 1024                         # reply budget per call (thinking budget must fit inside)
    thinking: dict[str, Any] | None = None         # anthropic: {"type": "enabled", "budget_tokens": 2048}
    reasoning: dict[str, Any] | None = None        # openai_compatible: {"reasoning_effort": "low"}
    reply_tool: bool = False                       # anthropic: offer a "reply" tool that takes the reply's JSON object
    sampling: dict[str, Any] = {}                  # temperature, top_p ... empty means provider defaults
    base_url: str | None = None                    # openai_compatible only
    api_key_env: str | None = None                 # name of the env var holding the key
    mock: dict[str, Any] = {}                      # mock only: kind and knobs
    note: str | None = None                        # free text, for example "price not verified"

    def cost_usd(self, reply: Reply) -> float:
        plain = reply.input_tokens - reply.cache_read_tokens - reply.cache_write_tokens
        read_price = self.input_per_m if self.cache_read_per_m is None else self.cache_read_per_m
        write_price = self.input_per_m if self.cache_write_per_m is None else self.cache_write_per_m
        usd = (max(plain, 0) * self.input_per_m + reply.cache_read_tokens * read_price
               + reply.cache_write_tokens * write_price + reply.output_tokens * self.output_per_m)
        return usd / 1_000_000


def load_models(path: str | Path | None = None) -> dict[str, ModelSpec]:
    path = Path(path) if path else DEFAULT_MODELS_PATH
    raw = yaml.safe_load(path.read_text()) or {}
    entries = raw.get("models", raw)
    out: dict[str, ModelSpec] = {}
    for name, body in entries.items():
        out[name] = ModelSpec(name=name, **(body or {}))
    return out


def get_model(name: str, path: str | Path | None = None) -> ModelSpec:
    models = load_models(path)
    if name not in models:
        raise KeyError(f"model {name!r} is not in {path or DEFAULT_MODELS_PATH}. Known: {sorted(models)}")
    return models[name]


def load_env(dotenv_path: str | Path | None = None) -> None:
    """Read .env into os.environ (existing variables win)."""
    try:
        from dotenv import load_dotenv
    except ImportError:                                   # pragma: no cover
        return
    load_dotenv(dotenv_path, override=False)


def make_client(spec: ModelSpec, seed: int = 0) -> LLMClient:
    if spec.provider == "mock":
        from .mock import MockClient, SensibleMockClient
        kind = spec.mock.get("kind", "sensible")
        knobs = {k: v for k, v in spec.mock.items() if k != "kind"}
        if kind == "sensible":
            return SensibleMockClient(seed=seed, **knobs)
        return MockClient(knobs.get("script"))
    load_env()
    if spec.provider == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(spec.model, api_key_env=spec.api_key_env or "ANTHROPIC_API_KEY",
                               thinking=spec.thinking, sampling=spec.sampling, reply_tool=spec.reply_tool)
    if spec.provider == "openai_compatible":
        from .openai_client import OpenAICompatibleClient
        return OpenAICompatibleClient(spec.model, base_url=spec.base_url,
                                      api_key_env=spec.api_key_env or "OPENAI_API_KEY",
                                      reasoning=spec.reasoning, sampling=spec.sampling)
    raise ValueError(f"unknown provider {spec.provider!r} for model {spec.name!r}")
