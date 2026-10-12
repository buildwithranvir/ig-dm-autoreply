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


def test_any_owner_message_delivers_waiting_alerts(ig):
    """The reported case: a question waited in the queue because only "inbox" delivered it."""
    import time
    from app import bot
    from tests.conftest import dm
    ig.profiles["e1"] = {"username": "newaccount123", "is_user_follow_business": False}
    run(kv.set(alerts.WINDOW_KEY, str(time.time() - 25 * 3600)))  # window closed
    run(bot.handle_event(dm("e1", "what laptop do you use?")))
    assert not ig.to(OWNER)
    run(bot.handle_event(dm(OWNER, "hey")))
    owner_msgs = ig.to(OWNER)
    assert "❓ #1" in owner_msgs[0] and owner_msgs[-1] == "boss reply to: hey"
    assert ig.to("e1") == ["[AI]\ngood q, lemme check"]  # "hey" was NOT relayed as the answer


def test_owner_is_nudged_once_before_window_closes(ig):
    import time
    from app import bot
    from tests.conftest import dm
    ig.profiles["f1"] = {"username": "fan", "is_user_follow_business": True}
    run(kv.set(alerts.WINDOW_KEY, str(time.time() - 21 * 3600)))
    run(bot.handle_event(dm("f1", "hey")))
    run(bot.handle_event(dm("f1", "hello again")))
    nudges = [t for t in ig.to(OWNER) if "Send me anything" in t]
    assert len(nudges) == 1


def test_no_nudge_while_window_is_young(ig):
    import time
    run(kv.set(alerts.WINDOW_KEY, str(time.time() - 2 * 3600)))
    run(alerts.nudge_if_window_closing())
    assert not ig.to(OWNER)
