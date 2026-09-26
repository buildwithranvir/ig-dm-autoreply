import asyncio

import httpx
import pytest

from app import ai, config


@pytest.fixture
def llm(monkeypatch):
    """Point ai.decide at a scripted fake API. Call it with the responses to return, in order."""
    def script(*responses):
        calls = iter(responses)
        real_client = httpx.AsyncClient
        monkeypatch.setattr(ai.httpx, "AsyncClient",
                            lambda **kw: real_client(transport=httpx.MockTransport(lambda req: next(calls))))

    async def no_sleep(_):
        pass

    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(ai.asyncio, "sleep", no_sleep)
    return script


def ok(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def json_failure(text):
    return httpx.Response(400, json={"error": {"code": "json_validate_failed", "failed_generation": text}})


def decide(text="hi"):
    return asyncio.run(ai.decide([{"role": "user", "content": text}]))


def test_parses_reply(llm):
    llm(ok('{"reply": "hey!", "handoff": false, "ask_owner": ""}'))
    assert decide().text == "hey!"


def test_json_failure_retries_then_succeeds(llm):
    llm(json_failure("cool bro"), ok('{"reply": "nice, so wassup?"}'))
    assert decide("same").text == "nice, so wassup?"


def test_json_failure_twice_uses_plain_text(llm):
    llm(json_failure("cool bro"), json_failure("cool bro, enjoy"))
    reply = decide("same")
    assert reply.text == "cool bro, enjoy" and not reply.handoff


def test_json_debris_is_stripped(llm):
    llm(json_failure('nice nice, so wassup?"}'), json_failure('nice nice, so wassup?"}'))
    assert decide("im all good too").text == "nice nice, so wassup?"


@pytest.mark.parametrize("raw,expected", [
    ("cool bro", "cool bro"),
    ('nice nice, so wassup?"}', "nice nice, so wassup?"),
    ('{"reply": "hey bro", "hand', "hey bro"),
    ('{"reply": "he said \\"hi\\""}', 'he said "hi"'),
    ('{"handoff": true}', ""),
    ('  "ok bro"  ', "ok bro"),
])
def test_salvage_reply(raw, expected):
    assert ai.salvage_reply(raw) == expected


def test_rate_limit_then_success(llm):
    llm(httpx.Response(429, text="try again in 1s"), ok('{"reply": "hey"}'))
    assert decide().text == "hey"


def test_unavailable_returns_none(llm):
    llm(httpx.Response(500, text="boom"))
    assert decide() is None


def test_empty_reply_becomes_handoff(llm):
    llm(ok('{"reply": ""}'))
    assert decide().handoff


def test_retry_after_parsing():
    assert ai.retry_after(httpx.Response(429, text="Please try again in 1.725s.")) == pytest.approx(2.225)
    assert ai.retry_after(httpx.Response(429, headers={"retry-after": "4"})) == 4.5
    assert ai.retry_after(httpx.Response(429, text="nope")) == 3.0


def test_prompt_skips_unfilled_template_lines():
    assert "TODO" not in ai.system_prompt()
