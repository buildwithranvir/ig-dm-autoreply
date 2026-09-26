import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


def signed(body: bytes, secret: str = "s") -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}


def test_signature_is_required(monkeypatch):
    monkeypatch.setattr(config, "IG_APP_SECRET", "s")
    body = json.dumps({"object": "instagram", "entry": []}).encode()
    assert client.post("/webhook", content=body, headers=signed(body)).status_code == 200
    assert client.post("/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=0"}).status_code == 403


def test_malformed_body_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "IG_APP_SECRET", "s")
    assert client.post("/webhook", content=b"not json", headers=signed(b"not json")).status_code == 400


def test_verify_handshake(monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_VERIFY_TOKEN", "vt")
    params = {"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"}
    assert client.get("/webhook", params=params).text == "42"
    assert client.get("/webhook", params={**params, "hub.verify_token": "no"}).status_code == 403


def test_cron_requires_secret(monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "c")
    assert client.get("/cron/refresh-token").status_code == 401
