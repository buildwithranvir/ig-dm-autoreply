"""Recent messages per conversation (last few turns, kept for a day) so the AI has context."""
from app.config import DAY
from app.storage.kv import kv

MAX_TURNS = 12


def _key(igsid: str) -> str:
    return f"hist:{igsid}"


async def get(igsid: str) -> list[dict]:
    return await kv.get_json(_key(igsid)) or []


async def add(igsid: str, role: str, content: str) -> None:
    """role is "user" (them) or "assistant" (you, or the bot speaking as you)."""
    turns = await get(igsid)
    turns.append({"role": role, "content": content[:1000]})
    await kv.set_json(_key(igsid), turns[-MAX_TURNS:], ex=DAY)


async def clear(igsid: str) -> None:
    await kv.delete(_key(igsid))
