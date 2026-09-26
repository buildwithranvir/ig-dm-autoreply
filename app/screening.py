"""Which conversations the bot engages with.

Replying to a message request moves it from Requests to General, so replying means accepting.
Followers are always answered; non-followers must look like a real account.
"""
from app import config
from app.config import DAY
from app.instagram import api
from app.storage.kv import kv

ACCEPTED_TTL = 90 * DAY
SKIPPED_TTL = 7 * DAY  # re-screen after a week; their profile may have changed

FOLLOWER, ACCEPT, SKIP = "follower", "accept", "skip"


def evaluate(profile: dict | None, min_followers: int) -> tuple[str, str]:
    """Return (decision, reason) for a sender's profile."""
    if not profile:
        return SKIP, "profile unavailable"
    if profile.get("is_user_follow_business"):
        return FOLLOWER, "follows you"
    if profile.get("is_verified_user"):
        return ACCEPT, "verified account"
    if not profile.get("profile_pic"):
        return SKIP, "no profile picture"
    followers = int(profile.get("follower_count") or 0)
    if followers < min_followers:
        return SKIP, f"only {followers} followers"
    return ACCEPT, f"{followers} followers"


async def screen(igsid: str) -> tuple[str, str, dict | None]:
    """Return (decision, reason, profile summary), reusing the stored decision when there is one."""
    saved = await kv.get_json(f"thread:{igsid}")
    if saved:
        return saved["decision"], saved["reason"], saved.get("profile")

    profile = await api.get_profile(igsid)
    decision, reason = evaluate(profile, config.REQUEST_MIN_FOLLOWERS)
    summary = {k: profile.get(k) for k in ("username", "name", "follower_count")} if profile else None
    await save(igsid, decision, reason, summary)
    return decision, reason, summary


async def save(igsid: str, decision: str, reason: str, profile: dict | None) -> None:
    ttl = SKIPPED_TTL if decision == SKIP else ACCEPTED_TTL
    await kv.set_json(f"thread:{igsid}", {"decision": decision, "reason": reason, "profile": profile}, ex=ttl)
