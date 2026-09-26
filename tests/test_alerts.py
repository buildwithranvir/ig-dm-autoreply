from app.owner import alerts
from app.storage.kv import kv
from tests.conftest import OWNER, run


def test_pack_stays_under_message_limit():
    packed = alerts.pack(["a" * 600, "b" * 600, "c" * 10])
    assert len(packed) == 2 and all(len(m) <= 1000 for m in packed)


def test_failed_delivery_keeps_queue(ig, monkeypatch):
    run(kv.rpush(alerts.QUEUE_KEY, "alert 1", "alert 2"))

    class Refused:
        is_success, status_code, text = False, 400, "window closed"

    async def refuse(*_):
        return Refused()

    monkeypatch.setattr("app.instagram.api.send_text", refuse)
    run(alerts.deliver_queue())
    assert run(kv.pop_all(alerts.QUEUE_KEY)) == ["alert 1", "alert 2"]


def test_live_alert_when_window_open(ig):
    run(alerts.mark_owner_active())
    run(alerts.notify("hello"))
    assert ig.to(OWNER) == ["hello"]
