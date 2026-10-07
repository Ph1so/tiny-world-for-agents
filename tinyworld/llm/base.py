"""The one small interface every model adapter implements, plus retry with backoff.

    reply = client.complete(system, user, max_tokens)
    reply.text, reply.input_tokens, reply.output_tokens, reply.latency_s
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Reply:
    text: str
    input_tokens: int = 0            # every input token the provider billed, cached ones included
    output_tokens: int = 0
    latency_s: float = 0.0
    cache_read_tokens: int = 0       # part of input_tokens that was read from the prompt cache
    cache_write_tokens: int = 0      # part of input_tokens that was written to the prompt cache
    raw: dict = field(default_factory=dict)   # provider specific extras (stop reason, ids)


class LLMError(Exception):
    """A call failed for good. Nothing more will be tried."""


class RetryableError(LLMError):
    """Rate limit, overloaded, 5xx, timeout, or connection trouble. Worth another try."""


class LLMClient:
    name: str = "base"
    model_id: str = ""

    def complete(self, system: str, user: str, max_tokens: int) -> Reply:
        raise NotImplementedError

    def settings(self) -> dict:
        """What was sent to the provider besides the prompt. Recorded in config.yaml."""
        return {}


def with_retries(fn: Callable[[], Reply], max_retries: int = 6, base_delay: float = 1.0,
                 max_delay: float = 60.0, sleep: Callable[[float], None] = time.sleep,
                 rng: random.Random | None = None) -> Reply:
    """Call fn. On RetryableError wait base_delay * 2**attempt (plus jitter, capped) and call again."""
    rng = rng or random.Random()
    attempt = 0
    while True:
        try:
            return fn()
        except RetryableError as e:
            if attempt >= max_retries:
                raise LLMError(f"gave up after {max_retries} retries: {e}") from e
            delay = min(max_delay, base_delay * (2 ** attempt)) * (1 + 0.25 * rng.random())
            sleep(delay)
            attempt += 1
