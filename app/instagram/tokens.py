"""Long-lived access token.

Tokens last about 60 days. Refreshing returns a fresh 60-day token but only works once the current
one is at least 24 hours old. A daily cron calls refresh(), which renews weekly. The current token
is kept in Redis because a Vercel function can't rewrite its own env vars.
"""
import logging
import time

import httpx

from app import config
from app.config import DAY
from app.storage.kv import kv

log = logging.getLogger(__name__)

KEY = "ig:token"
REFRESH_EVERY = 7 * DAY


async def current() -> str:
    data = await kv.get_json(KEY)
    return data["access_token"] if data else config.IG_ACCESS_TOKEN


async def refresh(force: bool = False) -> dict:
    data = await kv.get_json(KEY)
    if data and not force and time.time() - data["refreshed_at"] < REFRESH_EVERY:
        return {"status": "fresh", "expires_at": data["expires_at"]}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": await current()},
        )
    if not resp.is_success:
        # Usually the token is younger than 24h; tomorrow's cron run retries.
        log.error("Token refresh failed %s: %s", resp.status_code, resp.text[:500])
        return {"status": "error", "code": resp.status_code}

    body = resp.json()
    now = time.time()
    expires_in = int(body.get("expires_in", 0))
    await kv.set_json(KEY, {"access_token": body["access_token"], "refreshed_at": now,
                            "expires_at": now + expires_in})
    log.info("Token refreshed; valid for %.0f days", expires_in / DAY)
    return {"status": "refreshed", "expires_at": now + expires_in}
