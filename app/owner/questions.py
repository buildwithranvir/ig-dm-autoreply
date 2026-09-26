"""Ask-then-relay: questions the AI can't answer go to you, and your answer goes back in your voice.

1. The AI can't answer, so the alert account gets: ❓ #12 @user asked: "<their exact message>"
2. You answer by swipe-replying to that alert, by starting with the number ("12 <answer>"), or, when
   it's the only open question, by just typing the answer. Starting with "save" also teaches the bot.
3. The AI words your answer as a reply and DMs the person.
"""
import logging
import re
import time

from app import ai, config
from app.config import DAY, HOUR
from app.instagram import messaging
from app.owner import alerts
from app.storage import history
from app.storage.kv import kv

log = logging.getLogger(__name__)

QUESTION_TTL = 2 * DAY
PERSON_WINDOW = 23 * HOUR  # the person can only be DMed within 24h of their last message
LEARNED_KEY = "facts:learned"
OPEN_KEY = "q:open"
MAX_LEARNED = 50

ANSWER_RE = re.compile(r"^#?(\d+)\s+(.+)$", re.DOTALL)
# Words that say nothing about *what* is being asked. Creator-account words ("last reel", "video")
# are included because most questions mention them; two questions sharing only those aren't the same.
FILLER_WORDS = set(
    "i you u my your ur me do did does the a an is are was were what which how where when who why "
    "use used using have has got get can could for in on of to it its this that bro find from with "
    "last latest recent new reel reels video videos post posts story stories content".split()
)


async def learned_facts() -> list[dict]:
    return await kv.get_json(LEARNED_KEY) or []


async def pending_for(igsid: str) -> list[str]:
    return await kv.get_json(f"pending:{igsid}") or []


async def _set_pending(igsid: str, questions: list[str]) -> None:
    if questions:
        await kv.set_json(f"pending:{igsid}", questions, ex=DAY)
    else:
        await kv.delete(f"pending:{igsid}")


async def record_message_from(igsid: str) -> None:
    """Remember when this person last messaged, which opens their 24h window."""
    await kv.set(f"lastmsg:{igsid}", str(time.time()), ex=DAY)


def _key_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - FILLER_WORDS - {config.OWNER_NAME.lower()}


def is_duplicate(question: str, pending: list[str]) -> bool:
    """The AI rephrases questions, so compare their key words rather than the exact text.
    Two questions match when most of their key words are shared (Jaccard similarity)."""
    new = _key_words(question)
    for old in map(_key_words, pending):
        if new and old and len(new & old) / len(new | old) >= 0.6:
            return True
    return False


async def ask(igsid: str, who: str, question: str, message: str) -> None:
    """question is the AI's short rewording, used to spot repeats and to save answers.
    message is what the person actually wrote, and is what you see in the alert."""
    pending = await pending_for(igsid)
    if is_duplicate(question, pending):
        log.info("Not asking again, %r repeats a question still open for %s", question, igsid)
        return
    qid = str(await kv.incr("q:counter"))
    await kv.set_json(f"q:{qid}", {"igsid": igsid, "who": who, "question": question, "message": message},
                      ex=QUESTION_TTL)
    await kv.set_json(OPEN_KEY, [*await _open_ids(), qid], ex=QUESTION_TTL)
    await _set_pending(igsid, [*pending, question])
    await alerts.notify(
        f"❓ #{qid} {who} asked: \"{message[:300]}\"\n"
        f"Swipe-reply to this with your answer and I'll DM them. Start it with \"save\" to also remember it."
    )


async def _open_ids() -> list[str]:
    return await kv.get_json(OPEN_KEY) or []


async def _open_questions() -> dict[str, dict]:
    """Questions still waiting for an answer, oldest first."""
    live = {}
    for qid in await _open_ids():
        q = await kv.get_json(f"q:{qid}")
        if q:
            live[qid] = q
    return live


async def _close(qid: str) -> None:
    await kv.delete(f"q:{qid}")
    await kv.set_json(OPEN_KEY, [i for i in await _open_ids() if i != qid], ex=QUESTION_TTL)


def split_save(text: str) -> tuple[bool, str]:
    """Split "save macbook" into (True, "macbook"); anything else is (False, text)."""
    text = text.strip()
    if text.lower().startswith("save "):
        return True, text[5:].strip()
    return False, text


def parse_answer(text: str) -> tuple[str, bool, str] | None:
    """Parse "12 save macbook" into ("12", True, "macbook"). None if it doesn't start with a number."""
    match = ANSWER_RE.match(text.strip())
    if not match:
        return None
    qid, rest = match.groups()
    save, answer = split_save(rest)
    if not answer or answer.lower() == "save":
        return None
    return qid, save, answer


async def _tell_owner(text: str) -> None:
    await messaging.send(config.OWNER_ALERT_IGSID, text)


async def _match_question(text: str, reply_to_mid: str | None) -> tuple[str, bool, str] | str | None:
    """Work out which question the alert account is answering.

    Tries, in order: a swipe-reply to a question alert, a leading question number ("12 answer"),
    and finally the only open question. Returns (qid, save, answer), "ambiguous" when several
    questions are open and the message doesn't say which, or None when it isn't an answer.
    """
    qid = await alerts.question_for_alert(reply_to_mid)
    if qid and await kv.get(f"q:{qid}"):
        save, answer = split_save(text)
        return (qid, save, answer) if answer else None

    parsed = parse_answer(text)
    if parsed and await kv.get(f"q:{parsed[0]}"):
        return parsed

    open_questions = await _open_questions()
    if len(open_questions) == 1:
        save, answer = split_save(text)
        return (next(iter(open_questions)), save, answer) if answer else None
    if len(open_questions) > 1:
        return "ambiguous"
    return None


async def handle_answer(text: str, reply_to_mid: str | None = None) -> bool:
    """Relay the answer if the message answers an open question. Returns False if it's just chat."""
    match = await _match_question(text, reply_to_mid)
    if match is None:
        return False
    if match == "ambiguous":
        waiting = "\n".join(f"#{qid} {q['who']}: \"{q.get('message', q['question'])[:80]}\""
                            for qid, q in (await _open_questions()).items())
        await _tell_owner("Which question is this for? Swipe-reply to its ❓ alert, or start your message "
                          f"with its number (e.g. \"12 your answer\"):\n{waiting}")
        return True

    qid, save, answer = match
    q = await kv.get_json(f"q:{qid}")
    igsid, who, question = q["igsid"], q["who"], q["question"]
    message = q.get("message", question)
    last = await kv.get(f"lastmsg:{igsid}")
    if not last or time.time() - float(last) > PERSON_WINDOW:
        await _close(qid)
        await _tell_owner(f"⌛ #{qid}: too late, {who}'s 24h window has closed. Reply to them in the app.")
        return True

    instruction = (
        f"You just found out the answer to their question \"{message}\": \"{answer}\". "
        "Write the message you send them now, giving this answer naturally in your voice. "
        "Don't mention checking with anyone. Set handoff=false, spam=false, ask_owner=\"\"."
    )
    reply = await ai.decide(await history.get(igsid), learned=await learned_facts(), instruction=instruction)
    if reply is None or not reply.text:
        await _tell_owner(f"⚠️ #{qid}: AI unavailable, nothing was sent to {who}. Try again in a minute.")
        return True
    if not await messaging.send_as_owner(igsid, reply.text):
        await _tell_owner(f"⚠️ #{qid}: Instagram refused the message to {who}. Reply to them in the app.")
        return True

    await _close(qid)
    await _set_pending(igsid, [p for p in await pending_for(igsid) if p != question])
    note = ""
    if save:
        facts = [f for f in await learned_facts() if f["q"] != question]
        await kv.set_json(LEARNED_KEY, [*facts, {"q": question, "a": answer}][-MAX_LEARNED:])
        note = "\n💾 Saved. I'll answer this myself next time."
    await _tell_owner(f"✅ #{qid} sent to {who}: \"{reply.text}\"{note}")
    return True
