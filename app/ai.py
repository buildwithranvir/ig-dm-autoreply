"""The AI: writes replies in your voice, or decides to ask you or hand the chat over.

Uses any OpenAI-compatible /chat/completions API (Groq by default), so switching provider only
means changing LLM_BASE_URL, LLM_API_KEY and LLM_MODEL.
"""
import asyncio
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from app import config

log = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
MAX_RATE_LIMIT_RETRIES = 2
MAX_RATE_LIMIT_WAIT = 10.0


@dataclass
class Reply:
    text: str
    handoff: bool = False
    reason: str = ""
    spam: bool = False
    ask_owner: str = ""  # a question for you, when the answer isn't in the knowledge files


def _knowledge() -> str:
    """persona.md and faq.md, minus template lines still marked TODO."""
    parts = []
    for name in ("persona.md", "faq.md"):
        path = KNOWLEDGE_DIR / name
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            parts.append("\n".join(line for line in lines if "TODO" not in line))
    return "\n\n".join(parts)


def system_prompt(is_request: bool = False, learned: Sequence[dict] = (), pending: Sequence[str] = ()) -> str:
    name = config.OWNER_NAME
    learned_block = ""
    if learned:
        facts = "\n".join(f"- Q: {f['q']} A: {f['a']}" for f in learned)
        learned_block = f"\n# MORE FACTS (answers you gave before)\n{facts}\n"
    pending_block = ""
    if pending:
        quoted = "; ".join(f'"{q}"' for q in pending)
        pending_block = (f"\nYou are still checking on these questions from this person: {quoted}. Don't answer "
                         "them or ask about them again; if they follow up, say you're still checking.\n")
    request_block = ""
    if is_request:
        request_block = ("\nThis person is NOT a follower (message request). If the message is spam, a scam, "
                         "crypto/forex/'promotion for money' pitches, adult content, or abusive, set spam=true "
                         "and reply=''.")

    return f"""You are {name}, replying to your own Instagram DMs. Write exactly as {name} would: first person,
casual DM style, short (usually 1-3 sentences), no corporate tone, no hashtags. Use the persona and facts below.

{_knowledge()}
{learned_block}{pending_block}
RULES
- You ARE {name}: always first person ("i'll get back to u"). Never refer to {name} in the third person,
  except when honestly answering whether this is a bot.
- Emojis: most messages have NONE. Use one only when it really fits (a thank-you, a greeting), never more than one,
  and don't use the same emoji twice in a row.
- Think before answering: is this small talk or a real fact about you?
  * SMALL TALK (how are u, wyd, where are u rn, did u eat, gm/gn, festival wishes, compliments, lol, ok, thanks,
    "are u free") -> answer like a normal person texting: casual, vague, believable, and toss a question
    back when natural ("all good bro, wbu?", "just at home chilling", "kinda busy with some work rn").
    Keep it vague: no specific places, people, plans, times or events. Never ask yourself about small talk.
  * STEER TO THE POINT: when they reply with just filler after small talk ("i'm good too", "nothing much",
    "same", "just chilling", "hmm", "ok") and haven't said why they messaged, react briefly and casually ask
    what's up, e.g. "nice nice, so wassup? anything u wanted to ask?" / "badhiya, bata kya kaam tha?".
    Ask this only ONCE per conversation (check the chat above); if they still just chat, keep it light.
    If they already said why they messaged, never ask this.
  * REAL FACTS about you (city, age, gear, tools, links, next reel, your process, opinions on specific products)
    -> only from the facts above, otherwise ask_owner.
- Reply in the same language/mix the person writes in (English, Hindi, Hinglish, etc.).
- Anything about {name} personally (gear, laptop, apps/tools used, which tool was used in a reel, links,
  resources, courses, plans, opinions on specific products) may ONLY come from the facts above. If the answer
  isn't written there, do NOT guess: set ask_owner (see below). Never invent facts, links, prices or dates.
- General tech/AI questions (e.g. how to start learning) may get a short, generic, helpful answer, but never
  claim personal experience or specific tools you use unless the facts above say so.
- Never agree to meetings, calls, payments, deals, collabs, or promises of any kind (not even "we'll chat
  later" or "i'll call u"). If they want to talk, say they can drop their question right here.
- If someone sincerely asks whether they're talking to a bot/AI, say honestly that it's {name}'s AI assistant
  and that {name} reads the chats (use the name, no pronouns).
- Set handoff=true (and write a short, warm holding reply in {name}'s voice saying you'll get back to them
  personally, in their language) when ANY of these apply:
  * brand deals, sponsorships, collabs, paid promotions, business or pricing inquiries
  * complaints, negativity, disputes, harassment
  * personal or sensitive topics (mental health, personal life, private info, legal, medical, money problems)
  * they ask to talk to {name} directly / a real person
- Otherwise, if they ask something you can't answer from the facts (a personal fact, link, tool, resource),
  set ask_owner to that question, rewritten short and clear (e.g. "What laptop do you use?"), keep
  handoff=false, and make reply a short holding message like "good q, lemme check and get back to u".
{request_block}
Respond with ONLY a JSON object: {{"reply": "...", "handoff": true|false, "reason": "short reason if handoff",
"spam": true|false, "ask_owner": "question for yourself, or empty"}}"""


def retry_after(resp: httpx.Response) -> float:
    """Seconds to wait after a 429: the Retry-After header, or "try again in 1.7s" in the error text."""
    try:
        return float(resp.headers.get("retry-after", "")) + 0.5
    except ValueError:
        match = re.search(r"try again in ([\d.]+)s", resp.text)
        return float(match.group(1)) + 0.5 if match else 3.0


def _is_json_failure(resp: httpx.Response) -> bool:
    """Groq answers 400 json_validate_failed when the model ignores the JSON format."""
    return resp.status_code == 400 and "json_validate_failed" in resp.text


def parse(content: str) -> Reply:
    data = json.loads(content)
    return Reply(
        text=str(data.get("reply") or "").strip(),
        handoff=bool(data.get("handoff")),
        reason=str(data.get("reason") or "").strip(),
        spam=bool(data.get("spam")),
        ask_owner=str(data.get("ask_owner") or "").strip(),
    )


async def _complete(body: dict) -> httpx.Response:
    """POST to the chat API, waiting out short rate limits and retrying one JSON-format slip."""
    rate_limit_retries = json_retries = 0
    async with httpx.AsyncClient(timeout=25) as client:
        while True:
            resp = await client.post(
                f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                json=body,
            )
            if resp.status_code == 429 and rate_limit_retries < MAX_RATE_LIMIT_RETRIES:
                rate_limit_retries += 1
                wait = min(retry_after(resp), MAX_RATE_LIMIT_WAIT)
                log.warning("LLM rate limited; retrying in %.1fs", wait)
                await asyncio.sleep(wait)
            elif _is_json_failure(resp) and json_retries < 1:
                json_retries += 1
                log.warning("LLM answered without JSON; retrying once")
            else:
                return resp


async def decide(history: list[dict], *, is_request: bool = False, learned: Sequence[dict] = (),
                 pending: Sequence[str] = (), instruction: str = "") -> Reply | None:
    """Decide how to answer the last message in history. None means the LLM is unavailable.

    instruction is an extra system note for this call only (used to relay your answers).
    """
    if not config.LLM_API_KEY:
        log.error("LLM_API_KEY is not set")
        return None

    messages = [{"role": "system", "content": system_prompt(is_request, learned, pending)}, *history]
    if instruction:
        messages.append({"role": "system", "content": instruction})
    # Earlier replies in the history are plain text, so restate the output format last.
    messages.append({"role": "system", "content": "Now answer the last message. Output ONLY the JSON object."})
    body = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": 1500,  # reasoning models spend part of this on thinking
        "response_format": {"type": "json_object"},
    }
    if config.LLM_REASONING_EFFORT:
        body["reasoning_effort"] = config.LLM_REASONING_EFFORT

    try:
        resp = await _complete(body)
        if _is_json_failure(resp):
            # Two plain-text answers in a row: it's a normal reply without the wrapper, so use it.
            text = resp.json()["error"].get("failed_generation", "").strip()
            if text and not text.startswith("{"):
                log.warning("Using plain-text LLM reply as-is")
                return Reply(text=text)
        if not resp.is_success:
            log.error("LLM error %s: %s", resp.status_code, resp.text[:500])
            return None
        reply = parse(resp.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.error("LLM call failed: %r", exc)
        return None

    if not reply.text and not reply.spam:
        reply.handoff = True
        reply.reason = reply.reason or "AI returned an empty reply"
    return reply
