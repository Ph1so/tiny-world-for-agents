"""Model adapters. One interface: client.complete(system, user, max_tokens) -> Reply."""
from .base import LLMClient, LLMError, Reply, RetryableError, with_retries
from .registry import ModelSpec, get_model, load_models, make_client

__all__ = ["LLMClient", "LLMError", "Reply", "RetryableError", "with_retries",
           "ModelSpec", "get_model", "load_models", "make_client"]
