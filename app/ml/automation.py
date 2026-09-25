from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.ml.history import update_recent_history
from app.ml.pipeline import train_model
from app.ml.store import load_metrics, load_observations

_started = False
PACIFIC = ZoneInfo("America/Los_Angeles")


def _training_through_date():
    m = load_metrics() or {}
    raw = m.get("training_through")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(PACIFIC).date()
    except Exception:
        return None


def _history_through_date():
    df = load_observations()
    if df.empty:
        return None
    ts = df["timestamp_utc"].max()
    try:
        return ts.tz_convert(PACIFIC).date()
    except Exception:
        return None


def _daily_retrain_due(now_utc: datetime) -> bool:
    """
    Retrain once per Pacific calendar day after the configured local hour,
    but only when the observation store has reached at least yesterday.
    """
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


def _loop():
    minutes = max(5, int(os.getenv("ML_INGEST_MINUTES", "15")))
    time.sleep(8)

    while True:
        try:
            # Re-read a full day so late/corrected provider observations are
            # reconciled before deciding whether the daily model is due.
            result = asyncio.run(update_recent_history(30))
            print("[ML] recent history update:", result)

            now = datetime.now(timezone.utc)
            if _daily_retrain_due(now):
                try:
                    metrics = train_model()
                    print("[ML] daily retrain complete:", (metrics or {}).get("model_version"))
                except Exception as exc:
                    print("[ML] daily retrain skipped:", exc)
            else:
                print(
                    "[ML] daily retrain not due; history through",
                    _history_through_date(),
                    "training through",
                    _training_through_date(),
                )
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
