"""Key-value storage: Upstash Redis over REST in production, in memory for local runs and tests.

Only the handful of Redis commands the bot needs are implemented. Everything goes through the
module-level `kv` object; tests swap its backend with `kv.backend = MemoryBackend()`.
"""
import json
import time

import httpx

from app import config


class MemoryBackend:
    """Process-local stand-in for Redis. Data is lost on restart."""

    name = "memory"

    def __init__(self):
        self._data: dict[str, tuple[object, float | None]] = {}

    def _live(self, key: str):
        item = self._data.get(key)
        if item and item[1] is not None and item[1] < time.time():
            del self._data[key]
            return None
        return item

    async def get(self, key: str) -> str | None:
        item = self._live(key)
        return item[0] if item else None

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and self._live(key):
            return False
        self._data[key] = (str(value), time.time() + ex if ex else None)
        return True

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, ex: int | None = None) -> int:
        item = self._live(key)
        value = int(item[0]) + 1 if item else 1
        expires = item[1] if item else (time.time() + ex if ex else None)
        self._data[key] = (str(value), expires)
        return value

    async def rpush(self, key: str, *values: str) -> None:
        item = self._live(key)
        self._data[key] = ([*(item[0] if item else []), *values], None)

    async def pop_all(self, key: str) -> list[str]:
        item = self._live(key)
        self._data.pop(key, None)
        return list(item[0]) if item else []


class UpstashBackend:
    """Upstash Redis REST API: POST a JSON command array, receive {"result": ...}."""

    name = "upstash"

    def __init__(self, url: str, token: str):
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _cmd(self, *args):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self._url, headers=self._headers, json=[str(a) for a in args])
        resp.raise_for_status()
        return resp.json().get("result")

    async def get(self, key: str) -> str | None:
        return await self._cmd("GET", key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        args = ["SET", key, value]
        if ex:
            args += ["EX", ex]
        if nx:
            args.append("NX")
        return await self._cmd(*args) == "OK"

    async def delete(self, key: str) -> None:
        await self._cmd("DEL", key)

    async def incr(self, key: str, ex: int | None = None) -> int:
        value = int(await self._cmd("INCR", key))
        if value == 1 and ex:
            await self._cmd("EXPIRE", key, ex)
        return value

    async def rpush(self, key: str, *values: str) -> None:
        await self._cmd("RPUSH", key, *values)

    async def pop_all(self, key: str) -> list[str]:
        # LPOP with a count is atomic, so two concurrent flushes can't deliver the same item twice.
        return await self._cmd("LPOP", key, 1000) or []


class KV:
    """Thin facade over the active backend, plus JSON helpers."""

    def __init__(self, backend):
        self.backend = backend

    async def get(self, key: str) -> str | None:
        return await self.backend.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        return await self.backend.set(key, value, ex=ex, nx=nx)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            await self.backend.delete(key)

    async def incr(self, key: str, ex: int | None = None) -> int:
        return await self.backend.incr(key, ex=ex)

    async def rpush(self, key: str, *values: str) -> None:
        await self.backend.rpush(key, *values)

    async def pop_all(self, key: str) -> list[str]:
        return await self.backend.pop_all(key)

    async def get_json(self, key: str):
        raw = await self.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value, ex: int | None = None) -> None:
        await self.set(key, json.dumps(value), ex=ex)


def _default_backend():
    if config.REDIS_REST_URL and config.REDIS_REST_TOKEN:
        return UpstashBackend(config.REDIS_REST_URL, config.REDIS_REST_TOKEN)
    return MemoryBackend()


kv = KV(_default_backend())
