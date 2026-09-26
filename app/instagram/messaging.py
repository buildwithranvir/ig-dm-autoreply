"""Sending DMs and remembering which ones the bot sent.

Instagram echoes every message sent from the account back to the webhook. Echoes whose message
ID was recorded here came from the bot; any other echo is a reply you typed yourself.
"""
import logging

from app import config
from app.config import DAY
from app.instagram import api
from app.storage import history
from app.storage.kv import kv

log = logging.getLogger(__name__)


async def was_sent_by_bot(mid: str) -> bool:
    return bool(await kv.get(f"sent:{mid}"))


async def send(recipient_id: str, text: str) -> str | None:
    """Send a DM. Returns the sent message's ID, or None if Instagram refused it."""
    resp = await api.send_text(recipient_id, text)
    if not resp.is_success:
        log.error("Send API error %s to %s: %s", resp.status_code, recipient_id, resp.text[:500])
        return None
    mid = resp.json().get("message_id") or "unknown"
    await kv.set(f"sent:{mid}", "1", ex=2 * DAY)
    log.info("Sent to %s: %r", recipient_id, text[:80])
    return mid


async def send_as_owner(recipient_id: str, text: str) -> bool:
    """Send an AI reply in your voice. The first one in each 24h conversation carries the disclosure."""
    first = await kv.set(f"disclosed:{recipient_id}", "1", ex=DAY, nx=True)
    ok = await send(recipient_id, f"{config.DISCLOSURE_PREFIX}\n{text}" if first else text)
    if ok:
        await history.add(recipient_id, "assistant", text)
    elif first:
        await kv.delete(f"disclosed:{recipient_id}")
    return ok
