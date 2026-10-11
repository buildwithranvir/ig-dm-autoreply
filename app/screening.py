"""Who a conversation is with: a follower or someone new (a message request).

Everyone gets a reply. Knowing whether the sender follows you only changes two things: the AI
also checks non-followers' messages for obvious spam, and you get a "moved to General" alert the
first time the bot answers someone new (replying to a message request moves it to General).
"""
from app.config import DAY
from app.instagram import api
from app.storage.kv import kv

ACCEPTED_TTL = 90 * DAY
SKIPPED_TTL = 7 * DAY  # how long a sender flagged as spam is left alone

FOLLOWER, ACCEPT, SKIP = "follower", "accept", "skip"


def evaluate(profile: dict | None) -> tuple[str, str]:
    """Return (decision, reason) for a sender's profile. Only spam (set later by the AI) is skipped."""
    if profile and profile.get("is_user_follow_business"):
        return FOLLOWER, "follows you"
    return ACCEPT, "new conversation"


async def screen(igsid: str) -> tuple[str, str, dict | None]:
    """Return (decision, reason, profile summary), reusing the stored decision when there is one."""
    saved = await kv.get_json(f"thread:{igsid}")
    if saved:
        return saved["decision"], saved["reason"], saved.get("profile")

    profile = await api.get_profile(igsid)
    decision, reason = evaluate(profile)
    summary = {k: profile.get(k) for k in ("username", "name", "follower_count")} if profile else None
    await save(igsid, decision, reason, summary)
    return decision, reason, summary


async def save(igsid: str, decision: str, reason: str, profile: dict | None) -> None:
    ttl = SKIPPED_TTL if decision == SKIP else ACCEPTED_TTL
    await kv.set_json(f"thread:{igsid}", {"decision": decision, "reason": reason, "profile": profile}, ex=ttl)
