"""Adapters: retry, mock, model registry, cost, and the real adapters against fake SDK clients."""
import json
import random
from types import SimpleNamespace

import httpx
import pytest

from tinyworld.llm import LLMError, Reply, RetryableError, get_model, load_models, make_client, with_retries
from tinyworld.llm.anthropic_client import AnthropicClient
from tinyworld.llm.mock import MockClient, SensibleMockClient
from tinyworld.llm.openai_client import OpenAICompatibleClient
from tinyworld.llm.registry import ModelSpec


def test_retry_backoff_then_success():
    calls, slept = [], []
    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise RetryableError("429")
        return Reply("ok")
    r = with_retries(fn, max_retries=5, base_delay=1.0, sleep=slept.append, rng=random.Random(0))
    assert r.text == "ok" and len(calls) == 3
    assert len(slept) == 2 and 1.0 <= slept[0] <= 1.25 and 2.0 <= slept[1] <= 2.5


def test_retry_gives_up():
    def fn():
        raise RetryableError("500")
    with pytest.raises(LLMError):
        with_retries(fn, max_retries=2, sleep=lambda s: None)


def test_retry_does_not_retry_plain_errors():
    n = [0]
    def fn():
        n[0] += 1
        raise LLMError("400 bad request")
    with pytest.raises(LLMError):
        with_retries(fn, max_retries=3, sleep=lambda s: None)
    assert n[0] == 1


def test_mock_list_and_callable():
    m = MockClient(["a", "b"])
    assert [m.complete("s", "u", 10).text for _ in range(3)] == ["a", "b", "b"]
    assert m.calls[0] == ("s", "u", 10)
    m2 = MockClient(lambda s, u: u.upper())
    assert m2.complete("s", "hi", 10).text == "HI"
    assert m2.complete("s", "hi", 10).input_tokens > 0


def test_models_yaml_loads_and_has_no_model_in_code():
    models = load_models()
    assert "mock" in models and models["mock"].provider == "mock"
    real = [m for m in models.values() if m.provider != "mock"]
    assert real, "models.yaml needs real entries"
    for m in real:
        assert m.model and m.provider in ("anthropic", "openai_compatible")
        assert m.input_per_m >= 0 and m.output_per_m >= 0
    with pytest.raises(KeyError):
        get_model("no_such_model")


def test_cost_with_cache_prices():
    spec = ModelSpec(provider="anthropic", model="x", input_per_m=3.0, output_per_m=15.0,
                     cache_read_per_m=0.3, cache_write_per_m=3.75)
    r = Reply("t", input_tokens=1000, output_tokens=100, cache_read_tokens=500, cache_write_tokens=200)
    want = (300 * 3.0 + 500 * 0.3 + 200 * 3.75 + 100 * 15.0) / 1e6
    assert spec.cost_usd(r) == pytest.approx(want)
    plain = ModelSpec(provider="anthropic", model="x", input_per_m=3.0, output_per_m=15.0)
    assert plain.cost_usd(r) == pytest.approx((1000 * 3.0 + 100 * 15.0) / 1e6)


def test_make_client_mock_kinds():
    assert isinstance(make_client(get_model("mock"), seed=1), SensibleMockClient)
    c = make_client(get_model("mock_wait"))
    assert isinstance(c, MockClient) and "wait" in c.complete("s", "u", 5).text


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        AnthropicClient("some-model")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        OpenAICompatibleClient("some-model")
    # a local server needs no key
    OpenAICompatibleClient("m", base_url="http://localhost:11434/v1", client=object())


def _resp(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://example.test"))


class _FakeAnthropic:
    """Looks enough like anthropic.Anthropic().messages.create for the adapter."""
    def __init__(self, fail_first=0):
        self.kwargs = []
        self.fail_first = fail_first
        self.messages = self

    def create(self, **kw):
        import anthropic
        self.kwargs.append(kw)
        if len(self.kwargs) <= self.fail_first:
            raise anthropic.RateLimitError("slow down", response=_resp(429), body=None)
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=100, cache_creation_input_tokens=20)
        return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking="..."),
                                        SimpleNamespace(type="text", text='{"action": {"name": "wait", "steps": 1}}')],
                               usage=usage, stop_reason="end_turn", id="msg_1")


def test_anthropic_adapter_caches_system_and_counts_tokens(monkeypatch):
    fake = _FakeAnthropic(fail_first=1)
    monkeypatch.setattr("tinyworld.llm.base.time.sleep", lambda s: None)
    c = AnthropicClient("model-x", client=fake, thinking={"type": "enabled", "budget_tokens": 1024})
    r = c.complete("SYS", "USER", 2048)
    assert len(fake.kwargs) == 2                                  # one retry after the 429
    kw = fake.kwargs[-1]
    assert kw["model"] == "model-x" and kw["max_tokens"] == 2048
    assert kw["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert kw["messages"] == [{"role": "user", "content": "USER"}]
    assert kw["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert r.text.startswith('{"action"') and r.input_tokens == 130 and r.output_tokens == 5
    assert r.cache_read_tokens == 100 and r.cache_write_tokens == 20 and r.latency_s >= 0
    assert c.settings()["thinking"]["budget_tokens"] == 1024


class _FakeOpenAI:
    def __init__(self):
        self.kwargs = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kw):
        self.kwargs.append(kw)
        usage = SimpleNamespace(prompt_tokens=50, completion_tokens=7,
                                prompt_tokens_details=SimpleNamespace(cached_tokens=40))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="reply"), finish_reason="stop")],
                               usage=usage, id="cmpl_1")


def test_openai_adapter(monkeypatch):
    fake = _FakeOpenAI()
    c = OpenAICompatibleClient("gpt-x", base_url="https://example.test/v1", client=fake,
                               reasoning={"reasoning_effort": "low"}, sampling={"temperature": 0.5})
    r = c.complete("SYS", "USER", 300)
    kw = fake.kwargs[0]
    assert kw["model"] == "gpt-x" and kw["max_completion_tokens"] == 300
    assert kw["messages"][0] == {"role": "system", "content": "SYS"} and kw["reasoning_effort"] == "low"
    assert kw["temperature"] == 0.5
    assert r.text == "reply" and r.input_tokens == 50 and r.output_tokens == 7 and r.cache_read_tokens == 40
    assert c.settings()["base_url"] == "https://example.test/v1"


def test_openai_adapter_retries_on_5xx(monkeypatch):
    import openai
    monkeypatch.setattr("tinyworld.llm.base.time.sleep", lambda s: None)
    n = [0]
    class Flaky(_FakeOpenAI):
        def create(self, **kw):
            n[0] += 1
            if n[0] == 1:
                raise openai.InternalServerError("boom", response=_resp(503), body=None)
            return super().create(**kw)
    c = OpenAICompatibleClient("m", client=Flaky())
    assert c.complete("s", "u", 10).text == "reply" and n[0] == 2


def test_anthropic_reply_tool_is_offered_and_its_input_becomes_the_text():
    fake = _FakeAnthropic()
    c = AnthropicClient("model-x", client=fake, reply_tool=True)
    assert c.complete("S", "U", 100).text.startswith('{"action"')          # the model answered in text: unchanged
    kw = fake.kwargs[-1]
    assert [t["name"] for t in kw["tools"]] == ["reply"] and "tool_choice" not in kw
    assert c.settings()["reply_tool"] is True

    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    fake.create = lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok, replying"),
                 SimpleNamespace(type="tool_use", name="reply", input={"thought": "t", "action": {"name": "wait", "steps": 2}})],
        usage=usage, stop_reason="tool_use", id="msg_2")
    r = c.complete("S", "U", 100)
    assert json.loads(r.text) == {"thought": "t", "action": {"name": "wait", "steps": 2}} and r.raw["via"] == "reply_tool"

    off = _FakeAnthropic()
    assert "reply_tool" not in AnthropicClient("model-x", client=off).settings()
    AnthropicClient("model-x", client=off).complete("S", "U", 100)
    assert "tools" not in off.kwargs[-1]
    assert get_model("sonnet").reply_tool and not get_model("haiku").reply_tool
