from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.ml.history import backfill_days, ingest_range, update_recent_history
from app.ml.pipeline import train_model
from app.ml.store import load_metrics, load_observations

_started = False
PACIFIC = ZoneInfo("America/Los_Angeles")


def _training_through_date():
    m = load_metrics() or {}
    raw = m.get("training_through_utc") or m.get("training_through")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(PACIFIC).date()
    except Exception:
        return None


def _history_bounds():
    df = load_observations()
    if df.empty:
        return None, None, 0
    return df["timestamp_utc"].min(), df["timestamp_utc"].max(), len(df)


def _history_through_date():
    _, ts, _ = _history_bounds()
    if ts is None:
        return None
    try:
        return ts.tz_convert(PACIFIC).date()
    except Exception:
        return None


async def _repair_history():
    """
    Treat the local SQLite history as a rebuildable cache.

    Empty store: rebuild the configured bootstrap window.
    Existing store: refill from shortly before the newest observation through
    now. The overlap reconciles late/corrected source observations.
    """
    first, latest, rows = _history_bounds()
    bootstrap_days = max(30, int(os.getenv("ML_BOOTSTRAP_DAYS", "365")))
    overlap_hours = max(6, int(os.getenv("ML_REPAIR_OVERLAP_HOURS", "30")))
    now = datetime.now(timezone.utc)

    if latest is None or rows == 0:
        print(f"[ML] history empty; rebuilding {bootstrap_days} days in background")
        return await backfill_days(bootstrap_days)

    latest_dt = latest.to_pydatetime()
    start = latest_dt - timedelta(hours=overlap_hours)
    if start >= now:
        start = now - timedelta(hours=overlap_hours)

    print(
        "[ML] repairing history from",
        start.isoformat(),
        "through",
        now.isoformat(),
        f"(existing rows={rows})",
    )
    return await ingest_range(start, now)


def _daily_retrain_due(now_utc: datetime) -> bool:
    now_local = now_utc.astimezone(PACIFIC)
    hour = int(os.getenv("ML_DAILY_RETRAIN_HOUR", "2"))
    if now_local.hour < hour:
        return False

    yesterday = now_local.date() - timedelta(days=1)
    history_date = _history_through_date()
    trained_date = _training_through_date()

    if history_date is None or history_date < yesterday:
        return False

    return trained_date is None or trained_date < yesterday


def _maybe_train(now):
    if not _daily_retrain_due(now):
        print(
            "[ML] daily retrain not due; history through",
            _history_through_date(),
            "training through",
            _training_through_date(),
        )
        return

    try:
        metrics = train_model()
        print("[ML] daily retrain complete:", (metrics or {}).get("model_version"))
    except Exception as exc:
        print("[ML] daily retrain skipped:", exc)


def _loop():
    minutes = max(5, int(os.getenv("ML_INGEST_MINUTES", "15")))
    time.sleep(8)

    # Startup recovery runs on this daemon thread, never on the web-server
    # startup path. A wiped free-Render filesystem therefore rebuilds itself
    # without preventing the dashboard from coming online.
    try:
        result = asyncio.run(_repair_history())
        print("[ML] startup history repair:", result)
        _maybe_train(datetime.now(timezone.utc))
    except Exception as exc:
        print("[ML] startup history repair failed:", exc)

    while True:
        try:
            result = asyncio.run(update_recent_history(30))
            print("[ML] recent history update:", result)
            _maybe_train(datetime.now(timezone.utc))
        except Exception as exc:
            print("[ML] ingest failed:", exc)

        time.sleep(minutes * 60)


def start_ml_automation():
    global _started
    if (
        os.getenv("ML_AUTOMATION_ENABLED", "true").lower()
        not in {"true", "1", "yes", "on"}
        or _started
    ):
        return

    _started = True
    threading.Thread(
        target=_loop,
        daemon=True,
        name="richmond-ml",
    ).start()
