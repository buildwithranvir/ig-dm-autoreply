import pytest

from app import bot, screening
from tests.conftest import OWNER, dm, run


@pytest.mark.parametrize("profile,expected", [
    (None, screening.SKIP),
    ({"is_user_follow_business": True}, screening.FOLLOWER),
    ({"is_verified_user": True}, screening.ACCEPT),
    ({"profile_pic": "x", "follower_count": 50}, screening.ACCEPT),
    ({"profile_pic": "x", "follower_count": 3}, screening.SKIP),
    ({"follower_count": 5000}, screening.SKIP),  # no profile picture
])
def test_evaluate(profile, expected):
    assert screening.evaluate(profile, 10)[0] == expected


def test_legit_request_is_accepted_and_alert_queued(ig):
    ig.profiles["r1"] = {"username": "realperson", "profile_pic": "x", "follower_count": 40}
    run(bot.handle_event(dm("r1", "can you share the AI tools list?")))
    assert len(ig.to("r1")) == 1
    assert not ig.to(OWNER)  # alert window closed, so the alert waits in the queue
    run(bot.handle_event(dm(OWNER, "inbox")))
    assert "moved @realperson to General" in ig.to(OWNER)[0]


def test_suspicious_profile_is_left_alone_with_one_alert(ig):
    ig.profiles["s1"] = {"username": "x9x9x9", "follower_count": 0}
    run(bot.handle_event(dm("s1", "promo?")))
    run(bot.handle_event(dm("s1", "hello??")))
    assert not ig.to("s1")
    run(bot.handle_event(dm(OWNER, "inbox")))
    assert " ".join(ig.to(OWNER)).count("left @x9x9x9 in Requests") == 1


def test_spam_request_is_left_alone(ig):
    ig.profiles["s2"] = {"username": "promo", "profile_pic": "x", "follower_count": 900}
    run(bot.handle_event(dm("s2", "invest in crypto now")))
    run(bot.handle_event(dm("s2", "hello?")))
    assert not ig.to("s2")
    run(bot.handle_event(dm(OWNER, "inbox")))
    assert "left @promo in Requests (looks like spam)" in ig.to(OWNER)[0]
