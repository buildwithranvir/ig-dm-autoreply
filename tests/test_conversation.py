import time

from app import bot
from app.owner import questions
from app.storage import history
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
    assert "the AI is down and @fan5 is waiting" in ig.to(OWNER)[0]


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


def test_manual_reply_pause_is_short(ig):
    follower(ig, "f8")
    run(bot.handle_event(echo("f8", "typed-by-hand", "hey, accepted your request")))
    expires = kv.backend._data["pause:f8"][1]
    assert 0 < expires - time.time() <= 10 * 60


def test_family_center_invite_does_not_pause_chat(ig):
    follower(ig, "f7")
    run(bot.handle_event(echo("f7", "system-1", "Invite to set up supervision: https://familycenter.instagram.com/fc/invite/abc")))
    assert run(kv.get("pause:f7")) is None
    run(bot.handle_event(dm("f7", "hey")))
    assert len(ig.to("f7")) == 1


def test_delete_my_data(ig):
    follower(ig, "f4")
    run(bot.handle_event(dm("f4", "hey")))
    run(bot.handle_event(dm("f4", "please delete my data")))
    assert "deleted" in ig.to("f4")[-1]
    assert run(kv.get("hist:f4")) is None


def test_owner_gets_boss_mode_without_disclosure(ig):
    run(bot.handle_event(dm(OWNER, "yo what's up")))
    assert ig.to(OWNER) == ["boss reply to: yo what's up"]


def test_owner_is_never_paused_or_screened(ig):
    run(bot.handle_event(dm(OWNER, "wanna collab")))  # a handoff topic for anyone else
    run(bot.handle_event(dm(OWNER, "hello")))
    assert ig.to(OWNER)[-1] == "boss reply to: hello"
    assert run(kv.get(f"pause:{OWNER}")) is None


def shared_reel(sender, caption="5 AI tools for devs", text=None):
    event = dm(sender, text or "")
    if text is None:
        event["message"].pop("text")
    event["message"]["attachments"] = [{"type": "ig_reel", "payload": {"url": "u", "title": caption}}]
    return event


def test_shared_reels_get_no_reply_from_anyone(ig):
    follower(ig, "fan")
    run(bot.handle_event(shared_reel("fan")))
    run(bot.handle_event(shared_reel(OWNER)))
    assert ig.sent == []
    assert run(history.get("fan"))[-1]["content"] == '[sent: a reel (caption: "5 AI tools for devs")]'


def test_owner_reel_is_not_taken_as_an_answer(ig):
    follower(ig, "asker")
    run(bot.handle_event(dm(OWNER, "inbox")))
    run(bot.handle_event(dm("asker", "what laptop do you use?")))
    sent_before = len(ig.sent)
    run(bot.handle_event(shared_reel(OWNER)))
    assert len(ig.sent) == sent_before
    assert run(questions.pending_for("asker"))  # question #1 still open


def test_reel_with_typed_text_still_gets_a_reply(ig):
    follower(ig, "fan2")
    run(bot.handle_event(shared_reel("fan2", text="how did u make this?")))
    assert len(ig.to("fan2")) == 1


def test_reset_forgets_chat_questions_and_queued_alerts(ig):
    follower(ig, "asker")
    run(bot.handle_event(dm("asker", "what laptop do you use?")))  # window closed: alert queued
    run(bot.handle_event(dm(OWNER, "reset")))
    assert "Fresh start, boss" in ig.to(OWNER)[-1]
    assert "1 open question(s)" in ig.to(OWNER)[-1] and "1 queued alert(s)" in ig.to(OWNER)[-1]
    assert run(kv.get("hist:" + OWNER)) is None
    assert run(kv.get_json("pending:asker")) is None
    run(bot.handle_event(dm(OWNER, "1 macbook")))  # question #1 is gone, so this is just chat
    assert ig.to(OWNER)[-1] == "boss reply to: 1 macbook"
    assert len(ig.to("asker")) == 1


def test_forget_also_works_as_reset(ig):
    run(bot.handle_event(dm(OWNER, "Forget")))
    assert "Fresh start, boss" in ig.to(OWNER)[-1]


def test_story_reply_and_media_are_described():
    assert bot.describe({"attachments": [{"type": "ig_reel"}]}) == "[sent: a reel]"
    reel = {"attachments": [{"type": "ig_reel", "payload": {"title": "my agent setup"}}]}
    assert bot.describe(reel) == '[sent: a reel (caption: "my agent setup")]'
    assert bot.describe({"text": "nice", "reply_to": {"story": {"id": "1"}}}) == "nice [sent: a reply to your story]"
    assert bot.describe({"text": "hey", "reply_to": None}) == "hey"
