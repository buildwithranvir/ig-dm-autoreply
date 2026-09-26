from app import bot
from app.storage.kv import kv
from tests.conftest import OWNER, dm, echo, run


def follower(ig, igsid, username="fan"):
    ig.profiles[igsid] = {"username": username, "is_user_follow_business": True}


def test_follower_gets_reply_with_disclosure_only_first_time(ig):
    follower(ig, "f1")
    run(bot.handle_event(dm("f1", "hey")))
    run(bot.handle_event(dm("f1", "what tools do you use")))
    assert ig.to("f1") == ["[AI]\nai reply to: hey", "ai reply to: what tools do you use"]
    assert not ig.to(OWNER)


def test_handoff_sends_holding_reply_pauses_and_alerts(ig):
    run(bot.handle_event(dm(OWNER, "inbox")))  # opens the alert window
    follower(ig, "b1", "brand")
    run(bot.handle_event(dm("b1", "wanna do a paid collab?")))
    assert "personally" in ig.to("b1")[0]
    assert "@brand needs you (brand deal)" in ig.to(OWNER)[-1]
    run(bot.handle_event(dm("b1", "hello??")))
    assert len(ig.to("b1")) == 1


def test_llm_down_alerts_instead_of_replying(ig):
    follower(ig, "f5", "fan5")
    run(bot.handle_event(dm("f5", "is the server down")))
    assert not ig.to("f5")
    run(bot.handle_event(dm(OWNER, "inbox")))
    assert "AI unavailable, @fan5 is waiting" in ig.to(OWNER)[0]


def test_spam_flag_is_ignored_for_followers(ig):
    follower(ig, "f6")
    run(bot.handle_event(dm("f6", "lol crypto memes")))
    assert run(kv.get_json("thread:f6"))["decision"] == "follower"


def test_duplicate_delivery_ignored(ig):
    follower(ig, "f2")
    event = dm("f2", mid="same")
    run(bot.handle_event(event))
    run(bot.handle_event(event))
    assert len(ig.sent) == 1


def test_manual_reply_pauses_chat_but_bot_echo_does_not(ig):
    follower(ig, "f3")
    run(bot.handle_event(dm("f3")))
    run(bot.handle_event(echo("f3", "bot-mid-1")))
    assert run(kv.get("pause:f3")) is None
    run(bot.handle_event(echo("f3", "typed-by-hand", "I'll send it tonight")))
    assert run(kv.get("pause:f3"))
    run(bot.handle_event(dm("f3", "ok thanks")))
    assert len(ig.to("f3")) == 1


def test_delete_my_data(ig):
    follower(ig, "f4")
    run(bot.handle_event(dm("f4", "hey")))
    run(bot.handle_event(dm("f4", "please delete my data")))
    assert "deleted" in ig.to("f4")[-1]
    assert run(kv.get("hist:f4")) is None


def test_owner_account_can_chat_with_ai(ig):
    follower(ig, OWNER, "ranvir_1028")
    run(bot.handle_event(dm(OWNER, "yo what's up")))
    assert ig.to(OWNER) == ["[AI]\nai reply to: yo what's up"]


def test_owner_reset_clears_pause(ig):
    follower(ig, OWNER, "ranvir_1028")
    run(bot.handle_event(dm(OWNER, "wanna collab")))
    assert run(kv.get(f"pause:{OWNER}"))
    run(bot.handle_event(dm(OWNER, "reset")))
    assert run(kv.get(f"pause:{OWNER}")) is None
    run(bot.handle_event(dm(OWNER, "hey")))
    assert ig.to(OWNER)[-1].endswith("ai reply to: hey")


def test_story_reply_and_media_are_described():
    assert bot.describe({"attachments": [{"type": "ig_reel"}]}) == "[sent: ig_reel]"
    assert bot.describe({"text": "nice", "reply_to": {"story": {"id": "1"}}}) == "nice [sent: reply to your story]"
    assert bot.describe({"text": "hey", "reply_to": None}) == "hey"
