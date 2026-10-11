"""Settings from environment variables (.env locally, project env vars on Vercel)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


HOUR = 3600
DAY = 24 * HOUR

# Instagram app (App Dashboard > Instagram > API setup with Instagram business login)
IG_APP_ID = _get("IG_APP_ID")
IG_APP_SECRET = _get("IG_APP_SECRET")
META_APP_SECRET = _get("META_APP_SECRET")  # optional; some dashboard test payloads are signed with it
IG_ACCESS_TOKEN = _get("IG_ACCESS_TOKEN")  # seed token; refreshed copies live in Redis
IG_USER_ID = _get("IG_USER_ID")
WEBHOOK_VERIFY_TOKEN = _get("WEBHOOK_VERIFY_TOKEN")
GRAPH_API_VERSION = _get("GRAPH_API_VERSION", "v25.0")
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"

# Upstash Redis REST credentials (Vercel's Upstash integration names them KV_REST_API_*)
REDIS_REST_URL = _get("UPSTASH_REDIS_REST_URL") or _get("KV_REST_API_URL")
REDIS_REST_TOKEN = _get("UPSTASH_REDIS_REST_TOKEN") or _get("KV_REST_API_TOKEN")

# Vercel Cron sends "Authorization: Bearer <CRON_SECRET>"
CRON_SECRET = _get("CRON_SECRET")

# Bot behaviour
BOT_ENABLED = _get("BOT_ENABLED", "true").lower() not in ("0", "false", "no", "off")
OWNER_NAME = _get("OWNER_NAME", "Ranvir")
OWNER_ALERT_IGSID = _get("OWNER_ALERT_IGSID")  # your 2nd account: receives alerts and questions
# After you reply to someone yourself, the bot stays quiet in that chat for this long
MANUAL_REPLY_PAUSE_MINUTES = _int("MANUAL_REPLY_PAUSE_MINUTES", 10)
MAX_AUTO_DMS_PER_HOUR = _int("MAX_AUTO_DMS_PER_HOUR", 100)
MAX_REPLIES_PER_THREAD_PER_DAY = _int("MAX_REPLIES_PER_THREAD_PER_DAY", 30)
DISCLOSURE_PREFIX = _get("DISCLOSURE_PREFIX", f"🤖 (AI replying for {OWNER_NAME})")
HANDOFF_FALLBACK = _get("HANDOFF_FALLBACK", "good question, let me get back to you on this one personally")
ASK_FALLBACK = "good q, lemme check and get back to u"

# LLM: any OpenAI-compatible chat API (Groq by default)
LLM_BASE_URL = _get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = _get("LLM_API_KEY")
LLM_MODEL = _get("LLM_MODEL", "openai/gpt-oss-120b")
LLM_REASONING_EFFORT = _get("LLM_REASONING_EFFORT", "low")  # for reasoning models; empty for others


def missing(*names: str) -> list[str]:
    """Names of required settings that are empty."""
    return [n for n in names if not globals().get(n)]
