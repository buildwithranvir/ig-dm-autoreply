import pytest

from app import bot, screening
from tests.conftest import OWNER, dm, run


@pytest.mark.parametrize("profile,expected", [
    ({"is_user_follow_business": True}, screening.FOLLOWER),
    ({"is_user_follow_business": False, "follower_count": 0}, screening.ACCEPT),
    ({"follower_count": 5000}, screening.ACCEPT),
    (None, screening.ACCEPT),  # profile unavailable: still reply
])
def test_evaluate(profile, expected):
    assert screening.evaluate(profile)[0] == expected


def test_anyone_gets_a_reply_whatever_their_followers(ig):
    """The reported case: an account with no profile picture and 0 followers got no reply."""
    ig.profiles["e1"] = {"username": "newaccount123", "follower_count": 0}
    run(bot.handle_event(dm("e1", "heyyy")))
    assert len(ig.to("e1")) == 1


def test_new_conversation_alerts_owner_once(ig):
    ig.profiles["r1"] = {"username": "realperson", "follower_count": 3}
    run(bot.handle_event(dm("r1", "can you share the AI tools list?")))
    run(bot.handle_event(dm("r1", "thanks")))
    assert len(ig.to("r1")) == 2
    run(bot.handle_event(dm(OWNER, "inbox")))
    assert " ".join(ig.to(OWNER)).count("moved @realperson to General") == 1


def test_spam_from_non_follower_is_left_alone(ig):
    ig.profiles["s2"] = {"username": "promo", "follower_count": 900}
    run(bot.handle_event(dm("s2", "invest in crypto now")))
    run(bot.handle_event(dm("s2", "hello?")))
    assert not ig.to("s2")
    run(bot.handle_event(dm(OWNER, "inbox")))
    assert "left @promo in Requests (looks like spam)" in ig.to(OWNER)[0]
