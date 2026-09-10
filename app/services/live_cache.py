
from __future__ import annotations
import asyncio, json, os, time
from pathlib import Path

CACHE_DIR = Path(os.getenv("LIVE_CACHE_DIR", "data/live_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TTL_SECONDS = int(os.getenv("LIVE_CACHE_TTL_SECONDS", "120"))
DEFAULT_STALE_SECONDS = int(os.getenv("LIVE_CACHE_STALE_SECONDS", "21600"))

_memory = {}
_locks = {}

def _path(key):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
    return CACHE_DIR / f"{safe}.json"

def _load(key):
    if key in _memory:
        return _memory[key]
    p = _path(key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "saved_at" in data and "value" in data:
            _memory[key] = data
            return data
    except Exception:
        pass
    return None

def _save(key, value):
    entry = {"saved_at": time.time(), "value": value}
    _memory[key] = entry
    try:
        p = _path(key)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(p)
    except Exception as exc:
        print(f"[LIVE CACHE] disk write failed for {key}: {exc}")
    return entry

def _age(entry):
    if not entry:
        return None
    try:
        return max(0.0, time.time() - float(entry["saved_at"]))
    except Exception:
        return None

async def cached_async(key, fetcher, *, ttl_seconds=None, stale_seconds=None):
    ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
    stale = DEFAULT_STALE_SECONDS if stale_seconds is None else int(stale_seconds)

    entry = _load(key)
    age = _age(entry)

    if entry and age is not None and age <= ttl:
        return entry["value"]

    lock = _locks.setdefault(key, asyncio.Lock())

    async def refresh():
        async with lock:
            latest = _load(key)
            latest_age = _age(latest)
            if latest and latest_age is not None and latest_age <= ttl:
                return latest["value"]
            value = await fetcher()
            _save(key, value)
            return value

    if entry and age is not None and age <= stale:
        async def background():
            try:
                await refresh()
            except Exception as exc:
                print(f"[LIVE CACHE] background refresh failed for {key}: {exc}")
        asyncio.create_task(background())
        return entry["value"]

    try:
        return await refresh()
    except Exception:
        fallback = _load(key)
        if fallback:
            return fallback["value"]
        raise

def newest_cache_status(prefix):
    files = sorted(
        CACHE_DIR.glob(f"{prefix}*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return {"available": False, "age_seconds": None}
    p = files[0]
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        saved = float(payload.get("saved_at", p.stat().st_mtime))
    except Exception:
        saved = p.stat().st_mtime
    return {
        "available": True,
        "age_seconds": round(max(0.0, time.time() - saved), 1),
    }
