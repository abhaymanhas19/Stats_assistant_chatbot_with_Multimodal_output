import asyncio
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from datetime import date
from urllib.parse import quote, urlsplit

import aiohttp
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.cache import cache
from yarl import URL

from ..models import StatsProjectFile

SESSION_TTL = 20 * 60
START_SECONDS = 150
CALL_SECONDS = 120
UNSIGNED = "UNSIGNED-PAYLOAD"
CHUNK = 1024 * 1024
UNREACHABLE = "The analysis server can't be reached. Try again in a minute."
NO_SESSION = "The server session ended. Load the data again."


class EngineError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _session_key(project_id, user_id) -> str:
    return f"stats-engine:{project_id}:{user_id}"


def _sign(method: str, target: str, body_hash: str) -> dict:
    ts = str(int(time.time()))
    sig = hmac.new(
        settings.STATS_RUNNER_SECRET.encode(), f"{ts}\n{method}\n{target}\n{body_hash}".encode(), hashlib.sha256
    ).hexdigest()
    return {"X-Runner-Auth": f"{ts}.{sig}"}


async def _send(host: str, method: str, target: str, timeout: float, payload=None, data=None, length=None) -> dict:
    if not settings.STATS_RUNNER_SECRET:
        raise EngineError(503, UNREACHABLE)
    if payload is not None:
        body = json.dumps(payload).encode()
        headers = {**_sign(method, target, hashlib.sha256(body).hexdigest()), "Content-Type": "application/json"}
    else:
        body = data
        headers = {**_sign(method, target, UNSIGNED), "Content-Length": str(length)}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as http:
            async with http.request(method, URL(f"http://{host}{target}", encoded=True), data=body, headers=headers) as res:
                out = await res.json(content_type=None)
                status = res.status
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        raise EngineError(503, UNREACHABLE)
    if not isinstance(out, dict):
        raise EngineError(502, UNREACHABLE)
    if status >= 400:
        raise EngineError(status, out.get("error") or UNREACHABLE)
    return out


def _runner_host() -> str:
    return urlsplit(settings.STATS_RUNNER_URL).netloc


async def start(project_id, user_id, fresh=False) -> None:
    key = _session_key(project_id, user_id)
    if fresh:
        await end(project_id, user_id)
    elif await cache.aget(key):
        await cache.atouch(key, SESSION_TTL)
        return
    out = await _send(_runner_host(), "POST", "/sessions", START_SECONDS, payload={})
    await cache.aset(key, {"id": out["id"], "host": out["host"]}, SESSION_TTL)


async def end(project_id, user_id) -> None:
    key = _session_key(project_id, user_id)
    sess = await cache.aget(key)
    await cache.adelete(key)
    if sess:
        try:
            await _send(sess["host"], "DELETE", f"/sessions/{sess['id']}", 30, payload={})
        except EngineError:
            pass


async def _session(project_id, user_id) -> dict:
    key = _session_key(project_id, user_id)
    sess = await cache.aget(key)
    if not sess:
        raise EngineError(410, NO_SESSION)
    await cache.atouch(key, SESSION_TTL)
    return sess


async def _forget_if_gone(project_id, user_id, e: EngineError) -> None:
    if e.status in (404, 410, 504):
        await cache.adelete(_session_key(project_id, user_id))


@asynccontextmanager
async def _slot(user_id, seconds: float):
    day_key = f"stats-engine-day:{user_id}:{date.today().isoformat()}"
    if (await cache.aget(day_key) or 0) >= settings.STATS_ENGINE_DAILY_SECONDS:
        raise EngineError(429, "You've used today's server analysis time. It resets tomorrow.")
    busy_key = f"stats-engine-busy:{user_id}"
    if not await cache.aadd(busy_key, 1, int(seconds) + 60):
        raise EngineError(429, "Another analysis is still running on the server. Wait for it to finish.")
    t0 = time.monotonic()
    try:
        yield
    finally:
        await cache.adelete(busy_key)
        used = int(time.monotonic() - t0) + 1
        if not await cache.aadd(day_key, used, 2 * 24 * 3600):
            await cache.aincr(day_key, used)


async def run(project_id, user_id, msg: dict, seconds: float | None = None) -> dict:
    seconds = min(seconds or CALL_SECONDS, settings.STATS_ENGINE_CALL_SECONDS)
    sess = await _session(project_id, user_id)
    async with _slot(user_id, seconds):
        try:
            out = await _send(
                sess["host"], "POST", f"/sessions/{sess['id']}/op", seconds + 30, payload={**msg, "timeout": seconds}
            )
        except EngineError as e:
            await _forget_if_gone(project_id, user_id, e)
            raise
    if not out.get("ok"):
        raise EngineError(422, out.get("error") or "The analysis server couldn't run this.")
    return {"result": out.get("result")}


def _project_file(project_id, row_id):
    return StatsProjectFile.objects.select_related("file").filter(project_id=project_id, id=row_id).first()


async def _chunks(handle):
    read = sync_to_async(handle.read, thread_sensitive=False)
    try:
        while chunk := await read(CHUNK):
            yield chunk
    finally:
        await sync_to_async(handle.close, thread_sensitive=False)()


async def load_file(project_id, user_id, row_id, path: str | None) -> dict:
    row = await sync_to_async(_project_file)(project_id, row_id)
    if row is None:
        raise EngineError(404, "File not found.")
    sess = await _session(project_id, user_id)
    stored = row.file.file
    length = await sync_to_async(lambda: stored.size, thread_sensitive=False)()
    handle = await sync_to_async(stored.open, thread_sensitive=False)("rb")
    target = f"/sessions/{sess['id']}/files?path={quote(path or f'data/{row.name}', safe='')}"
    try:
        await _send(sess["host"], "PUT", target, settings.STATS_ENGINE_CALL_SECONDS, data=_chunks(handle), length=length)
    except EngineError as e:
        await _forget_if_gone(project_id, user_id, e)
        raise
    return {"ok": True, "path": path or f"data/{row.name}", "size": length}
