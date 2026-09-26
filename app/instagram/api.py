"""Calls to the Instagram API with Instagram Login (graph.instagram.com)."""
import hashlib
import hmac

import httpx

from app import config
from app.instagram import tokens

PROFILE_FIELDS = "name,username,profile_pic,follower_count,is_user_follow_business,is_verified_user"
MAX_TEXT = 1000  # Instagram's limit for a text message


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    """Check the X-Hub-Signature-256 header ("sha256=<hex>") against the app secret(s)."""
    if not header or not header.startswith("sha256="):
        return False
    received = header.removeprefix("sha256=")
    for secret in (config.IG_APP_SECRET, config.META_APP_SECRET):
        if secret:
            expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, received):
                return True
    return False


async def _post_message(payload: dict, timeout: float) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(
            f"{config.GRAPH_BASE}/me/messages",
            headers={"Authorization": f"Bearer {await tokens.current()}"},
            json=payload,
        )


async def send_text(recipient_id: str, text: str) -> httpx.Response:
    """Send a DM. Only allowed within 24 hours of the person's last message."""
    return await _post_message({"recipient": {"id": recipient_id}, "message": {"text": text[:MAX_TEXT]}}, 15)


async def sender_action(recipient_id: str, action: str) -> None:
    """Show "mark_seen", "typing_on" or "typing_off". Cosmetic, so failures are ignored."""
    try:
        await _post_message({"recipient": {"id": recipient_id}, "sender_action": action}, 5)
    except httpx.HTTPError:
        pass


async def get_profile(igsid: str) -> dict | None:
    """Profile of someone who messaged the account, or None if unavailable (e.g. they blocked you)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{config.GRAPH_BASE}/{igsid}",
            params={"fields": PROFILE_FIELDS, "access_token": await tokens.current()},
        )
    return resp.json() if resp.is_success else None
