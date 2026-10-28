from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.ml.history import backfill_recent_first, fill_missing_history, update_recent_history
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
    Treat the local SQLite history as a rebuildable cache (Render's disk is
    wiped on restart). Rebuild newest-first so the dashboard has data within
    minutes, then fill older history back to ML_BOOTSTRAP_DAYS in saved chunks.
    """
    first, latest, rows = _history_bounds()
    bootstrap_days = max(30, int(os.getenv("ML_BOOTSTRAP_DAYS", "730")))
    if latest is None or rows == 0:
        print(f"[ML] history empty; rebuilding {bootstrap_days} days newest-first")
        return await backfill_recent_first(days=bootstrap_days)
    print(f"[ML] filling history gaps (existing rows={rows})")
    return await fill_missing_history(days=bootstrap_days)


def _nowcast_maintenance(now_utc: datetime):
    """Weekly: retrain the served nowcast on all history and recompute its validation."""
    from app.ml.nowcast import load_artifact
    from app.ml.nowcast_eval import load_validation, retrain_and_validate

    every_days = max(1, int(os.getenv("NOWCAST_RETRAIN_DAYS", "7")))
    min_days = max(30, int(os.getenv("NOWCAST_MIN_TRAIN_DAYS", "300")))
    first, latest, rows = _history_bounds()
    if latest is None:
        return
    span_days = (latest - first).total_seconds() / 86400
    if span_days < min_days:
        print(f"[nowcast] history spans {span_days:.0f} days; waiting for {min_days} before retraining")
        return

    def age_days(raw):
        if not raw:
            return float("inf")
        try:
            t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return (now_utc - t).total_seconds() / 86400
        except Exception:
            return float("inf")

    art = load_artifact() or {}
    val = load_validation() or {}
    if age_days(art.get("trained_at_utc")) < every_days and age_days(val.get("computed_at_utc")) < every_days:
        return
    print("[nowcast] weekly retrain + validation starting")
    try:
        result = retrain_and_validate(load_observations())
        print("[nowcast] weekly retrain complete:", result)
    except Exception as exc:
        import traceback
        print("[nowcast] weekly retrain failed:", repr(exc))
        traceback.print_exc()


def _daily_retrain_due(now_utc: datetime) -> bool:
    now_local = now_utc.astimezone(PACIFIC)
    hour = int(os.getenv("ML_DAILY_RETRAIN_HOUR", "2"))
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
        print("[ML] retrain starting; history through", _history_through_date())
        metrics = train_model()
        print("[ML] daily retrain complete:", (metrics or {}).get("model_version"))
    except Exception as exc:
        import traceback
        print("[ML] daily retrain failed:", repr(exc))
        traceback.print_exc()


def _loop():
    minutes = max(5, int(os.getenv("ML_INGEST_MINUTES", "15")))
    time.sleep(8)

    # Startup recovery runs on this daemon thread, never on the web-server
    # startup path. A wiped free-Render filesystem therefore rebuilds itself
    # without preventing the dashboard from coming online.
    try:
        result = asyncio.run(_repair_history())
        print("[ML] startup history repair:", result)
        _nowcast_maintenance(datetime.now(timezone.utc))
        if os.getenv("ML_RUNTIME_RETRAIN_ENABLED", "false").lower() in {"true", "1", "yes", "on"}:
            _maybe_train(datetime.now(timezone.utc))
        else:
            print("[ML] runtime retraining disabled; serving committed model artifact")
    except Exception as exc:
        print("[ML] startup history repair failed:", exc)

    while True:
        try:
            result = asyncio.run(update_recent_history(30))
            print("[ML] recent history update:", result)
            _nowcast_maintenance(datetime.now(timezone.utc))
            if os.getenv("ML_RUNTIME_RETRAIN_ENABLED", "false").lower() in {"true", "1", "yes", "on"}:
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
