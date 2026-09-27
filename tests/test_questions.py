import time

import pytest

from app import bot
from app.owner import questions
from app.storage.kv import kv
from tests.conftest import OWNER, dm, run


def ask_about_laptop(ig, igsid):
    ig.profiles[igsid] = {"username": igsid, "is_user_follow_business": True}
    run(bot.handle_event(dm(OWNER, "inbox")))  # opens the alert window
    run(bot.handle_event(dm(igsid, "what laptop do you use?")))


def test_question_is_relayed_and_saved(ig):
    ask_about_laptop(ig, "curious")
    assert ig.to("curious") == ["[AI]\ngood q, lemme check"]
    assert '❓ #1 Boss, @curious asked: "what laptop do you use?"' in ig.to(OWNER)[-1]

    run(bot.handle_event(dm("curious", "which laptop tho?")))
    assert ig.to("curious")[-1] == "still checking bro"
    assert sum("❓" in t for t in ig.to(OWNER)) == 1

    run(bot.handle_event(dm(OWNER, "1 save macbook air m2")))
    assert ig.to("curious")[-1] == "it's macbook air m2 bro"
    assert "#1 sent to @curious" in ig.to(OWNER)[-1] and "Saved" in ig.to(OWNER)[-1]
    assert run(questions.pending_for("curious")) == []

    ig.profiles["other"] = {"username": "other", "is_user_follow_business": True}
    run(bot.handle_event(dm("other", "laptop?")))
    assert ig.to("other")[-1].endswith("known laptop answer")


def test_alert_quotes_exact_message_not_ai_rewording(ig):
    ig.profiles["w1"] = {"username": "w1", "is_user_follow_business": True}
    run(bot.handle_event(dm(OWNER, "inbox")))
    run(bot.handle_event(dm("w1", "bro which laptop is that in ur setup??")))
    alert = ig.to(OWNER)[-1]
    assert '"bro which laptop is that in ur setup??"' in alert
    assert "What laptop do you use?" not in alert


def test_answer_without_save_is_not_remembered(ig):
    ask_about_laptop(ig, "c3")
    run(bot.handle_event(dm(OWNER, "1 dell xps")))
    assert ig.to("c3")[-1] == "it's dell xps bro"
    assert run(questions.learned_facts()) == []


def test_answer_after_24h_window_is_refused(ig):
    ask_about_laptop(ig, "late")
    run(kv.set("lastmsg:late", str(time.time() - 25 * 3600)))
    run(bot.handle_event(dm(OWNER, "1 macbook")))
    assert len(ig.to("late")) == 1
    assert "too late" in ig.to(OWNER)[-1]


def owner_reply(text, reply_to_mid=None):
    event = dm(OWNER, text)
    if reply_to_mid:
        event["message"]["reply_to"] = {"mid": reply_to_mid, "is_self_reply": False}
    return event


def alert_mid(ig, qid):
    """Message ID the fake Instagram gave the alert for question #qid."""
    index = next(i for i, (rid, text) in enumerate(ig.sent) if rid == OWNER and f"❓ #{qid} " in text)
    return f"bot-mid-{index + 1}"


def test_swipe_reply_to_alert_answers_that_question(ig):
    ask_about_laptop(ig, "p1")
    ig.profiles["p2"] = {"username": "p2", "is_user_follow_business": True}
    run(bot.handle_event(dm("p2", "what laptop do you use?")))  # second open question: #2
    run(bot.handle_event(owner_reply("thinkpad x1", reply_to_mid=alert_mid(ig, 1))))
    assert ig.to("p1")[-1] == "it's thinkpad x1 bro"
    assert len(ig.to("p2")) == 1  # only the holding reply


def test_plain_answer_goes_to_the_only_open_question(ig):
    """The reported bug: answering without the number replied to the alert account instead."""
    ask_about_laptop(ig, "client")
    run(bot.handle_event(owner_reply("an ai gmail summariser, link is in my bio")))
    assert ig.to("client")[-1] == "it's an ai gmail summariser, link is in my bio bro"
    assert "#1 sent to @client" in ig.to(OWNER)[-1]
    assert not any("reply to:" in t for t in ig.to(OWNER))


def test_plain_save_answer_is_remembered(ig):
    ask_about_laptop(ig, "s1")
    run(bot.handle_event(owner_reply("save macbook air m2")))
    assert ig.to("s1")[-1] == "it's macbook air m2 bro"
    assert run(questions.learned_facts()) == [{"q": "What laptop do you use?", "a": "macbook air m2"}]


def test_plain_answer_with_several_open_questions_asks_which(ig):
    ask_about_laptop(ig, "a1")
    ig.profiles["a2"] = {"username": "a2", "is_user_follow_business": True}
    run(bot.handle_event(dm("a2", "what laptop do you use?")))
    run(bot.handle_event(owner_reply("macbook")))
    assert "Which question is this for" in ig.to(OWNER)[-1]
    assert "#1 @a1" in ig.to(OWNER)[-1] and "#2 @a2" in ig.to(OWNER)[-1]
    assert len(ig.to("a1")) == 1 and len(ig.to("a2")) == 1


def test_swipe_reply_to_queued_alert(ig):
    ig.profiles["q9"] = {"username": "q9", "is_user_follow_business": True}
    run(bot.handle_event(dm("q9", "what laptop do you use?")))  # alert window closed: queued
    assert not ig.to(OWNER)
    run(bot.handle_event(dm(OWNER, "inbox")))
    run(bot.handle_event(owner_reply("dell xps", reply_to_mid=alert_mid(ig, 1))))
    assert ig.to("q9")[-1] == "it's dell xps bro"


def test_answered_question_is_closed(ig):
    ask_about_laptop(ig, "done1")
    run(bot.handle_event(owner_reply("1 macbook")))
    ig.profiles[OWNER] = {"username": "ranvir_1028", "is_user_follow_business": True}
    run(bot.handle_event(owner_reply("thanks bot")))  # no open questions left: normal chat
    assert ig.to(OWNER)[-1] == "boss reply to: thanks bot"


def test_new_question_is_asked_while_another_is_open(ig):
    run(bot.handle_event(dm(OWNER, "inbox")))
    run(questions.ask("c7", "@c7", "What was the last reel project?", "what was the last reel project"))
    run(questions.ask("c7", "@c7", "Where can I find the agent of the last reel?", "where's the agent from the reel"))
    alerts_sent = [t for t in ig.to(OWNER) if "❓" in t]
    assert len(alerts_sent) == 2 and "where's the agent from the reel" in alerts_sent[1]


def test_number_without_live_question_is_normal_chat(ig):
    ig.profiles[OWNER] = {"username": "ranvir_1028", "is_user_follow_business": True}
    run(bot.handle_event(dm(OWNER, "5 bros walked in")))
    assert ig.to(OWNER)[-1] == "boss reply to: 5 bros walked in"


@pytest.mark.parametrize("text,expected", [
    ("12 macbook", ("12", False, "macbook")),
    ("#12 save macbook air", ("12", True, "macbook air")),
    ("12 Save it's a dell", ("12", True, "it's a dell")),
    ("12 save", None),
    ("12 saved me bro", ("12", False, "saved me bro")),
    ("hello", None),
])
def test_parse_answer(text, expected):
    assert questions.parse_answer(text) == expected


@pytest.mark.parametrize("question,pending,expected", [
    ("what laptop do you use?", ["What laptop do you use?"], True),
    ("Which laptop do u have", ["What laptop do you use?"], True),
    ("What mic do you use?", ["What laptop do you use?"], False),
    ("Which tool did i use for the voiceover in my last reel?", ["What tool for the voiceover?"], True),
    ("What editing app do you use?", ["Which tool did you use for the voiceover?"], False),
    # the reported bug: sharing only "last reel" doesn't make two questions the same
    ("Where can I find the agent of the last reel?", ["What was the last reel project?"], False),
    ("Where can I find the agent from your last reel?", ["Where can I find the agent of the last reel?"], True),
    ("What is the link to your latest video?", ["Which mic is in your latest video?"], False),
    ("Where is Ranvir located?", ["Where does Ranvir live?"], False),
])
def test_duplicate_question_detection(question, pending, expected):
    assert questions.is_duplicate(question, pending) is expected
