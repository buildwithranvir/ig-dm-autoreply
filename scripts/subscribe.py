"""Subscribe your Instagram account to this app's webhooks (the 'messages' field), then show current subscriptions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import config  # noqa: E402

if not config.IG_ACCESS_TOKEN:
    sys.exit("IG_ACCESS_TOKEN is empty, fill in .env first.")

auth = {"access_token": config.IG_ACCESS_TOKEN}
url = f"{config.GRAPH_BASE}/me/subscribed_apps"

resp = httpx.post(url, params={**auth, "subscribed_fields": "messages"}, timeout=15)
print("subscribe:", resp.status_code, resp.text)

resp = httpx.get(url, params=auth, timeout=15)
print("current:  ", resp.status_code, resp.text)
