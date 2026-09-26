"""Ask-then-relay: questions the AI can't answer go to you, and your answer goes back in your voice.

1. The AI can't answer, so the alert account gets: ❓ #12 @user asked: "..."
2. You reply "12 <answer>", or "12 save <answer>" to also teach the bot for next time.
3. The AI words your answer as a reply and DMs the person.
"""
import re
import time

from app import ai, config
from app.config import DAY, HOUR
from app.instagram import messaging
from app.owner import alerts
from app.storage import history
from app.storage.kv import kv

QUESTION_TTL = 2 * DAY
PERSON_WINDOW = 23 * HOUR  # the person can only be DMed within 24h of their last message
LEARNED_KEY = "facts:learned"
MAX_LEARNED = 50

ANSWER_RE = re.compile(r"^#?(\d+)\s+(.+)$", re.DOTALL)
FILLER_WORDS = set(
    "i you u my your ur me do did does the a an is are was what which how where when who why "
    "use used using have has got get can could for in on of to it this that bro".split()
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
    return set(re.findall(r"[a-z0-9]+", text.lower())) - FILLER_WORDS


def is_duplicate(question: str, pending: list[str]) -> bool:
    """The AI rephrases questions, so compare their key words rather than the exact text."""
    new = _key_words(question)
    for old in map(_key_words, pending):
        if new and old and len(new & old) / min(len(new), len(old)) >= 0.6:
            return True
    return False


async def ask(igsid: str, who: str, question: str) -> None:
    pending = await pending_for(igsid)
    if is_duplicate(question, pending):
        return
    qid = await kv.incr("q:counter")
    await kv.set_json(f"q:{qid}", {"igsid": igsid, "who": who, "question": question}, ex=QUESTION_TTL)
    await _set_pending(igsid, [*pending, question])
    await alerts.notify(
        f"❓ #{qid} {who} asked: \"{question}\"\n"
        f"Reply \"{qid} your answer\" and I'll DM them. To also remember it: \"{qid} save your answer\""
    )


def parse_answer(text: str) -> tuple[str, bool, str] | None:
    """Parse "12 save macbook" into ("12", True, "macbook"). None if it isn't an answer."""
    match = ANSWER_RE.match(text.strip())
    if not match:
        return None
    qid, rest = match.groups()
    save = rest.lower().startswith("save ")
    answer = rest[5:].strip() if save else rest.strip()
    if not answer or answer.lower() == "save":
        return None
    return qid, save, answer


async def _tell_owner(text: str) -> None:
    await messaging.send(config.OWNER_ALERT_IGSID, text)


async def handle_answer(text: str) -> bool:
    """Relay the answer if text answers a live question. Returns False if it's just chat."""
    parsed = parse_answer(text)
    if not parsed:
        return False
    qid, save, answer = parsed
    q = await kv.get_json(f"q:{qid}")
    if not q:
        return False

    igsid, who, question = q["igsid"], q["who"], q["question"]
    last = await kv.get(f"lastmsg:{igsid}")
    if not last or time.time() - float(last) > PERSON_WINDOW:
        await kv.delete(f"q:{qid}")
        await _tell_owner(f"⌛ #{qid}: too late, {who}'s 24h window has closed. Reply to them in the app.")
        return True

    instruction = (
        f"You just found out the answer to their question \"{question}\": \"{answer}\". "
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

    await kv.delete(f"q:{qid}")
    await _set_pending(igsid, [p for p in await pending_for(igsid) if p != question])
    note = ""
    if save:
        facts = [f for f in await learned_facts() if f["q"] != question]
        await kv.set_json(LEARNED_KEY, [*facts, {"q": question, "a": answer}][-MAX_LEARNED:])
        note = "\n💾 Saved. I'll answer this myself next time."
    await _tell_owner(f"✅ #{qid} sent to {who}: \"{reply.text}\"{note}")
    return True
