"""Alerts to your alert account, within Instagram's 24-hour messaging rule.

The bot may only DM the alert account if it messaged in the last 24 hours. Inside that window
alerts go out immediately; outside it they queue in Redis until the alert account sends any
message ("inbox"), which reopens the window and delivers the queue.
"""
import logging
import re
import time

from app import config
from app.config import DAY, HOUR
from app.instagram import messaging
from app.instagram.api import MAX_TEXT
from app.storage.kv import kv

log = logging.getLogger(__name__)

WINDOW_KEY = "owner:last_msg"
QUEUE_KEY = "alerts:queue"
WINDOW = 23 * HOUR  # stay safely inside the 24h limit
QUESTION_TAG = re.compile(r"❓ #(\d+)")  # the "❓ #12" marker on question alerts


async def _link_question(mid: str, text: str) -> None:
    """Remember which question an alert message carries, so a swipe-reply to it counts as the answer."""
    ids = set(QUESTION_TAG.findall(text))
    if len(ids) == 1:
        await kv.set(f"qalert:{mid}", ids.pop(), ex=2 * DAY)


async def question_for_alert(mid: str | None) -> str | None:
    return await kv.get(f"qalert:{mid}") if mid else None


async def mark_owner_active() -> None:
    await kv.set(WINDOW_KEY, str(time.time()))


async def _window_open() -> bool:
    last = await kv.get(WINDOW_KEY)
    return bool(last) and time.time() - float(last) < WINDOW


async def notify(text: str) -> None:
    if not config.OWNER_ALERT_IGSID:
        return
    if await _window_open():
        mid = await messaging.send(config.OWNER_ALERT_IGSID, text)
        if mid:
            await _link_question(mid, text)
            return
    await kv.rpush(QUEUE_KEY, text)
    log.info("Alert queued until the alert account messages again: %s", text)


def pack(items: list[str]) -> list[str]:
    """Combine alerts into as few messages as possible, each within the length limit."""
    out, current = [], ""
    for item in items:
        item = item[:MAX_TEXT]
        if current and len(current) + 2 + len(item) > MAX_TEXT:
            out.append(current)
            current = item
        else:
            current = f"{current}\n\n{item}" if current else item
    return out + ([current] if current else [])


async def deliver_queue() -> None:
    """The alert account messaged: reopen the window and send everything queued."""
    await mark_owner_active()
    queued = await kv.pop_all(QUEUE_KEY)
    if not queued:
        await messaging.send(config.OWNER_ALERT_IGSID, "📭 No queued alerts. You'll get live alerts for the next 24h.")
        return
    header = f"📬 {len(queued)} alert(s) while you were away:"
    for message in pack([header, *queued]):
        mid = await messaging.send(config.OWNER_ALERT_IGSID, message)
        if not mid:
            await kv.rpush(QUEUE_KEY, *queued)  # nothing is lost; the next "inbox" retries
            return
        await _link_question(mid, message)
