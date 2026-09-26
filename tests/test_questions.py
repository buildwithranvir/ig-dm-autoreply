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
    assert '❓ #1 @curious asked: "what laptop do you use?"' in ig.to(OWNER)[-1]

    run(bot.handle_event(dm("curious", "which laptop tho?")))
    assert ig.to("curious")[-1] == "still checking bro"
    assert sum("❓" in t for t in ig.to(OWNER)) == 1

    run(bot.handle_event(dm(OWNER, "1 save macbook air m2")))
    assert ig.to("curious")[-1] == "it's macbook air m2 bro"
    assert "✅ #1 sent to @curious" in ig.to(OWNER)[-1] and "Saved" in ig.to(OWNER)[-1]
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


def test_number_without_live_question_is_normal_chat(ig):
    ig.profiles[OWNER] = {"username": "ranvir_1028", "is_user_follow_business": True}
    run(bot.handle_event(dm(OWNER, "5 bros walked in")))
    assert ig.to(OWNER)[-1].endswith("ai reply to: 5 bros walked in")


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
])
def test_duplicate_question_detection(question, pending, expected):
    assert questions.is_duplicate(question, pending) is expected
