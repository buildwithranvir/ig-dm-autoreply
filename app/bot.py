"""Handles each incoming messaging event from the webhook."""
import asyncio
import logging
import time

from app import ai, config, screening
from app.config import DAY, HOUR
from app.instagram import api, messaging
from app.owner import alerts, questions
from app.storage import history
from app.storage.kv import kv

log = logging.getLogger(__name__)

PAUSE_TTL = DAY
REPLY_WINDOW_MS = 23 * HOUR * 1000  # only answer messages well inside the 24h window


ATTACHMENT_NAMES = {
    "ig_reel": "a reel", "reel": "a reel", "ig_post": "a post", "share": "a post", "story": "a story",
    "image": "a photo", "video": "a video", "audio": "a voice note", "file": "a file",
}
RESET_WORDS = {"reset", "forget"}


def _describe_attachment(attachment: dict) -> str:
    kind = attachment.get("type", "attachment")
    name = ATTACHMENT_NAMES.get(kind, kind)
    caption = ((attachment.get("payload") or {}).get("title") or "").strip()
    return f'{name} (caption: "{caption[:300]}")' if caption else name


def describe(message: dict) -> str:
    """The message text, plus a note about anything else they sent (photo, reel and its caption...)."""
    text = (message.get("text") or "").strip()
    parts = [_describe_attachment(a) for a in message.get("attachments") or []]
    if (message.get("reply_to") or {}).get("story"):
        parts.append("a reply to your story")
    if parts:
        return f"{text} [sent: {', '.join(parts)}]".strip()
    return text or "[sent something unsupported, e.g. a sticker]"


def _display_name(igsid: str, profile: dict | None) -> str:
    return f"@{profile['username']}" if profile and profile.get("username") else f"user {igsid}"


async def handle_event(event: dict) -> None:
    message = event.get("message")
    sender_id = (event.get("sender") or {}).get("id")
    if not message or not sender_id:
        return  # reads, reactions, postbacks

    if message.get("is_echo") or sender_id == config.IG_USER_ID:
        recipient_id = (event.get("recipient") or {}).get("id")
        await _on_echo(recipient_id, message.get("mid"), message.get("text") or "")
        return
    if message.get("is_deleted") or not await _is_new(message.get("mid")):
        return
    if time.time() * 1000 - event.get("timestamp", time.time() * 1000) > REPLY_WINDOW_MS:
        log.info("Message from %s is too old to answer", sender_id)
        return

    text = describe(message)
    log.info("DM from %s: %r", sender_id, text)
    await questions.record_message_from(sender_id)

    if sender_id == config.OWNER_ALERT_IGSID:
        if not await _handle_owner_command(message) and config.BOT_ENABLED:
            await _chat_with_owner(text)
        return
    if "delete my data" in text.lower():
        await _delete_data(sender_id)
        return
    if config.BOT_ENABLED:
        await _converse(sender_id, text)


async def _is_new(mid: str | None) -> bool:
    """Instagram retries deliveries; each message ID is handled once."""
    if not mid:
        return True
    if await kv.set(f"seen:{mid}", "1", ex=2 * DAY, nx=True):
        return True
    log.info("Duplicate delivery of %s ignored", mid)
    return False


async def _on_echo(recipient_id: str | None, mid: str | None, text: str) -> None:
    """A message sent from your account. If the bot didn't send it, you replied yourself."""
    if not recipient_id or not mid or await messaging.was_sent_by_bot(mid):
        return
    # The echo can arrive before the bot has recorded its own message ID, so check once more.
    await asyncio.sleep(1.5)
    if await messaging.was_sent_by_bot(mid):
        return
    if text:
        await history.add(recipient_id, "assistant", text)
    if recipient_id != config.OWNER_ALERT_IGSID:
        await kv.set(f"pause:{recipient_id}", "manual reply", ex=PAUSE_TTL)
        log.info("You replied to %s yourself; bot paused there for 24h", recipient_id)


async def _handle_owner_command(message: dict) -> bool:
    """Messages from the alert account: inbox, reset, or an answer to a question.
    Returns False for anything else, which then becomes a chat with the assistant."""
    await alerts.mark_owner_active()
    text = (message.get("text") or "").strip()
    command = text.lower()
    if command == "inbox":
        await alerts.deliver_queue()
        return True
    if command in RESET_WORDS:
        await _fresh_start()
        return True
    if not text or message.get("attachments"):
        return False  # a shared reel or photo is something to talk about, not an answer
    return await questions.handle_answer(text, (message.get("reply_to") or {}).get("mid"))


async def _fresh_start() -> None:
    """Forget the chat with the owner and every open question and queued alert."""
    owner = config.OWNER_ALERT_IGSID
    await history.clear(owner)
    await kv.delete(f"pause:{owner}", f"disclosed:{owner}", f"pending:{owner}")
    dropped_questions = await questions.forget_all()
    dropped_alerts = await alerts.clear_queue()
    cleared = []
    if dropped_questions:
        cleared.append(f"{dropped_questions} open question(s)")
    if dropped_alerts:
        cleared.append(f"{dropped_alerts} queued alert(s)")
    extra = f" and cleared {' and '.join(cleared)}" if cleared else ""
    await messaging.send(owner, f"🔄 Fresh start, boss. I've forgotten our chat{extra}.")


async def _chat_with_owner(text: str) -> None:
    """The owner chatting with their assistant: boss mode, no screening, no disclosure tag."""
    owner = config.OWNER_ALERT_IGSID
    await history.add(owner, "user", text)
    await api.sender_action(owner, "typing_on")
    reply = await ai.decide(await history.get(owner), learned=await questions.learned_facts(), boss=True)
    if reply is None or not reply.text:
        await messaging.send(owner, "⚠️ The AI is down right now, boss. Try again in a minute.")
        return
    if await messaging.send(owner, reply.text):
        await history.add(owner, "assistant", reply.text)


async def _delete_data(igsid: str) -> None:
    await history.clear(igsid)
    await kv.delete(*(f"{key}:{igsid}" for key in
                      ("thread", "pause", "disclosed", "skipalert", "movedalert", "pending", "lastmsg")))
    await messaging.send(igsid, "✅ Done, your conversation data with this assistant has been deleted.")


async def _within_rate_limits(igsid: str) -> bool:
    now = time.time()
    hourly = await kv.incr(f"rate:{int(now // HOUR)}", ex=HOUR)
    per_thread = await kv.incr(f"rate:{igsid}:{int(now // DAY)}", ex=DAY)
    return hourly <= config.MAX_AUTO_DMS_PER_HOUR and per_thread <= config.MAX_REPLIES_PER_THREAD_PER_DAY


async def _converse(igsid: str, text: str) -> None:
    await history.add(igsid, "user", text)
    if await kv.get(f"pause:{igsid}"):
        log.info("Chat with %s is paused; you're handling it", igsid)
        return

    decision, reason, profile = await screening.screen(igsid)
    who = _display_name(igsid, profile)
    snippet = text[:200]

    if decision == screening.SKIP:
        # Alert once per screening period; repeat messages from the same person stay quiet.
        if await kv.set(f"skipalert:{igsid}", "1", ex=screening.SKIPPED_TTL, nx=True):
            await alerts.notify(f"⛔ Boss, I left {who} in Requests ({reason}): \"{snippet}\"")
        return
    if not await _within_rate_limits(igsid):
        log.warning("Rate limit reached; not replying to %s", igsid)
        return

    is_request = decision == screening.ACCEPT and not await kv.get(f"movedalert:{igsid}")
    await api.sender_action(igsid, "mark_seen")
    await api.sender_action(igsid, "typing_on")
    reply = await ai.decide(await history.get(igsid), is_request=is_request,
                            learned=await questions.learned_facts(),
                            pending=await questions.pending_for(igsid))

    if reply is None:
        await alerts.notify(f"⚠️ Boss, the AI is down and {who} is waiting for you: \"{snippet}\"")
        return
    if reply.spam and is_request:
        await screening.save(igsid, screening.SKIP, "AI flagged as spam", profile)
        await alerts.notify(f"⛔ Boss, I left {who} in Requests (looks like spam): \"{snippet}\"")
        return

    if reply.handoff:
        await messaging.send_as_owner(igsid, reply.text or config.HANDOFF_FALLBACK)
        await kv.set(f"pause:{igsid}", "handoff", ex=PAUSE_TTL)
        await alerts.notify(f"🙋 Boss, {who} needs you ({reply.reason or 'not sure how to answer'}): \"{snippet}\"")
    elif reply.ask_owner:
        if not await messaging.send_as_owner(igsid, reply.text or config.ASK_FALLBACK):
            return
        await questions.ask(igsid, who, reply.ask_owner, text)
    elif not reply.text or not await messaging.send_as_owner(igsid, reply.text):
        return

    if is_request and await kv.set(f"movedalert:{igsid}", "1", ex=screening.ACCEPTED_TTL, nx=True):
        await alerts.notify(f"✅ Boss, I moved {who} to General ({reason}): \"{snippet}\"")
