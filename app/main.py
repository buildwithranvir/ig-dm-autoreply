"""HTTP entry point: Instagram webhook, token-refresh cron and privacy page."""
import json
import logging
import sys

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from app import bot, config
from app.instagram import api, tokens
from app.owner import alerts
from app.storage.kv import kv

# Windows consoles default to cp1252, and DMs are full of emoji.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

app = FastAPI(title="Instagram DM assistant")

REQUIRED_SETTINGS = ("IG_APP_SECRET", "IG_ACCESS_TOKEN", "WEBHOOK_VERIFY_TOKEN", "IG_USER_ID",
                     "OWNER_ALERT_IGSID", "CRON_SECRET", "LLM_API_KEY")


@app.get("/")
def health():
    return {
        "ok": True,
        "storage": kv.backend.name,
        "bot_enabled": config.BOT_ENABLED,
        "missing_settings": config.missing(*REQUIRED_SETTINGS),
    }


@app.get("/webhook")
def verify_webhook(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    """Called by Meta when you click "Verify and save" in the App Dashboard."""
    if mode == "subscribe" and config.WEBHOOK_VERIFY_TOKEN and token == config.WEBHOOK_VERIFY_TOKEN:
        log.info("Webhook verified by Meta")
        return PlainTextResponse(challenge)
    log.warning("Webhook verification failed")
    raise HTTPException(status_code=403, detail="verification failed")


def _messaging_events(payload: dict):
    """Real events arrive as entry[].messaging[]; dashboard test events as entry[].changes[].value."""
    for entry in payload.get("entry", []):
        yield from entry.get("messaging", [])
        for change in entry.get("changes", []):
            if change.get("field") == "messages" and isinstance(change.get("value"), dict):
                yield change["value"]


@app.post("/webhook")
async def receive_webhook(request: Request):
    raw = await request.body()
    if not api.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        log.warning("Rejected webhook with a bad or missing signature")
        raise HTTPException(status_code=403, detail="bad signature")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    log.info("Webhook payload: %s", json.dumps(payload, ensure_ascii=False))

    for event in _messaging_events(payload):
        try:
            await bot.handle_event(event)
        except Exception:
            # Keep returning 200: errors make Meta retry and eventually disable the webhook.
            log.exception("Failed to handle event")
    return {"ok": True}


@app.get("/cron/refresh-token")
async def cron_refresh_token(authorization: str = Header(""), force: bool = False):
    if not config.CRON_SECRET or authorization != f"Bearer {config.CRON_SECRET}":
        raise HTTPException(status_code=401, detail="unauthorized")
    result = await tokens.refresh(force=force)
    await alerts.nudge_if_window_closing()
    return result


PRIVACY_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Privacy Policy</title></head>
<body style="font-family:sans-serif;max-width:640px;margin:2rem auto;padding:0 1rem;line-height:1.5">
<h1>Privacy Policy</h1>
<p>This app replies to Instagram direct messages sent to its owner's Instagram account. It processes
the messages you send to that account and your Instagram-scoped user ID only to write and send replies.</p>
<p>Message content is sent to a third-party AI provider to draft replies. Recent messages are kept for
up to 24 hours to hold the conversation. Your username, name and follower count may be kept for up to
90 days to decide whether to reply to message requests. Nothing is sold or used for advertising.</p>
<p>To delete your data, send "delete my data" as a direct message to the account you messaged.</p>
</body>
</html>"""


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    """Meta requires a public privacy policy URL to publish the app."""
    return PRIVACY_HTML
