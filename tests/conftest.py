"""Shared fixtures: in-memory storage, a fake Instagram API and a scripted stand-in for the LLM."""
import asyncio
import time

import pytest

from app import ai, config
from app.instagram import api
from app.storage.kv import MemoryBackend, kv

OWNER = "owner-alert-account"


class FakeSendResponse:
    is_success, status_code, text = True, 200, "{}"

    def __init__(self, mid: str):
        self._mid = mid

    def json(self):
        return {"message_id": self._mid}


async def fake_decide(history, *, is_request=False, learned=(), pending=(), instruction="", boss=False):
    """Keyword-driven LLM stand-in: collab -> handoff, crypto -> spam, laptop -> ask you, down -> unavailable."""
    last = history[-1]["content"]
    if boss:
        return ai.Reply(text=f"boss reply to: {last}")
    if instruction:
        answer = instruction.split('": "')[1].split('"')[0]
        return ai.Reply(text=f"it's {answer} bro")
    if "down" in last:
        return None
    if "crypto" in last:
        return ai.Reply(text="", spam=True)
    if "collab" in last:
        return ai.Reply(text="let me get back to you on this personally", handoff=True, reason="brand deal")
    if "laptop" in last:
        if any(f["q"] == "What laptop do you use?" for f in learned):
            return ai.Reply(text="known laptop answer")
        if pending:
            return ai.Reply(text="still checking bro")
        return ai.Reply(text="good q, lemme check", ask_owner="What laptop do you use?")
    return ai.Reply(text=f"ai reply to: {last}")


class Instagram:
    """Records every DM the bot sends and serves profiles set by the test."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.profiles: dict[str, dict] = {}

    def to(self, igsid: str) -> list[str]:
        return [text for rid, text in self.sent if rid == igsid]

    async def send_text(self, recipient_id, text):
        self.sent.append((recipient_id, text))
        return FakeSendResponse(f"bot-mid-{len(self.sent)}")

    async def get_profile(self, igsid):
        return self.profiles.get(igsid)


@pytest.fixture
def ig(monkeypatch):
    fake = Instagram()

    async def noop(*_):
        pass

    monkeypatch.setattr(kv, "backend", MemoryBackend())
    monkeypatch.setattr(config, "OWNER_ALERT_IGSID", OWNER)
    monkeypatch.setattr(config, "IG_USER_ID", "me")
    monkeypatch.setattr(config, "BOT_ENABLED", True)
    monkeypatch.setattr(config, "DISCLOSURE_PREFIX", "[AI]")
    monkeypatch.setattr(api, "send_text", fake.send_text)
    monkeypatch.setattr(api, "get_profile", fake.get_profile)
    monkeypatch.setattr(api, "sender_action", noop)
    monkeypatch.setattr(ai, "decide", fake_decide)
    monkeypatch.setattr(asyncio, "sleep", noop)
    return fake


def dm(sender: str, text: str = "hi", mid: str | None = None) -> dict:
    return {"sender": {"id": sender}, "recipient": {"id": "me"}, "timestamp": int(time.time() * 1000),
            "message": {"mid": mid or f"m-{sender}-{time.time_ns()}", "text": text}}


def echo(to: str, mid: str, text: str = "x") -> dict:
    return {"sender": {"id": "me"}, "recipient": {"id": to}, "timestamp": int(time.time() * 1000),
            "message": {"mid": mid, "text": text, "is_echo": True}}


def run(coro):
    return asyncio.run(coro)
