"""Check that IG_ACCESS_TOKEN works and print your Instagram user ID (put it in .env as IG_USER_ID)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import config  # noqa: E402

if not config.IG_ACCESS_TOKEN:
    sys.exit("IG_ACCESS_TOKEN is empty, fill in .env first.")

resp = httpx.get(
    f"{config.GRAPH_BASE}/me",
    params={"fields": "user_id,username,account_type", "access_token": config.IG_ACCESS_TOKEN},
    timeout=15,
)
print(resp.status_code, resp.text)
if resp.is_success:
    data = resp.json()
    print(f"\nOK: logged in as @{data.get('username')} ({data.get('account_type')})")
    print(f"Set IG_USER_ID={data.get('user_id')} in .env")
