
from __future__ import annotations
import pandas as pd

RECENT_LIVE_MAX_AGE_MINUTES = 30.0

def _age_minutes(value):
    if not value:
        return None
    try:
        t = pd.Timestamp(value)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")
        return max(0.0, (pd.Timestamp.now(tz="UTC") - t).total_seconds() / 60.0)
    except Exception:
        return None

async def recent_h2s_from_history(hours: int = 6):
    try:
        from app.services.h2s import get_h2s_history
        history = await get_h2s_history(hours=hours)
    except Exception as exc:
        print(f"[H2S] recent-history recovery failed: {exc}")
        return None

    observations = history.get("observations", []) if isinstance(history, dict) else []

    def valid_for(stream_id):
        rows = []
        for o in observations:
            if str(o.get("data_stream_id")) != str(stream_id):
                continue
            if o.get("value") is None:
                continue
            try:
                if float(o.get("value")) == -999:
                    continue
            except Exception:
                continue
            if "missing" in str(o.get("qc") or "").lower():
                continue
            rows.append(o)
        return rows

    def latest(rows, name, stream, lat, lon):
        if not rows:
            return None
        row = sorted(rows, key=lambda x: str(x.get("timestamp_utc") or ""))[-1]
        reading_age = _age_minutes(row.get("timestamp_utc"))
        recent_live = reading_age is not None and reading_age <= RECENT_LIVE_MAX_AGE_MINUTES

        return {
            "id": str(stream),
            "data_stream_id": stream,
            "name": name,
            "lat": row.get("latitude", lat),
            "lon": row.get("longitude", lon),
            "h2s_ppb": float(row["value"]),
            "unit": row.get("unit") or "PPB",
            "timestamp_utc": row.get("timestamp_utc"),
            "timestamp_local": row.get("timestamp_local"),
            "qc": row.get("qc"),
            "operation_qc": row.get("operation_qc"),
            "below_mdl": row.get("below_mdl", False),
            "mdl_ppb": row.get("mdl"),
            "simulated": False,
            "source": "Sonoma recent valid observation" if recent_live else "Sonoma recent-history fallback",
            "reading_age_minutes": None if reading_age is None else round(reading_age, 1),
            "recent_live": recent_live,
        }

    sensors = []
    n = latest(valid_for(9950), "North Side", 9950, 37.921047, -122.37995)
    s = latest(valid_for(9963), "South Side", 9963, 37.91796, -122.37807)
    if n:
        sensors.append(n)
    if s:
        sensors.append(s)
    if not sensors:
        return None

    stamps = [x.get("timestamp_utc") for x in sensors if x.get("timestamp_utc")]
    ages = [x.get("reading_age_minutes") for x in sensors if x.get("reading_age_minutes") is not None]
    all_recent = bool(sensors and all(x.get("recent_live", False) for x in sensors))

    return {
        "timestamp": max(stamps) if stamps else None,
        "source": "Sonoma recent valid observation" if all_recent else "Sonoma recent-history fallback",
        "simulated": False,
        "stale_fallback": not all_recent,
        "recent_live": all_recent,
        "sensors": sensors,
        "metadata": {
            "fallback_reason": (
                "Current Sonoma slot had no valid H2S; selected the latest valid "
                "reading from recent Sonoma history."
            ),
            "history_hours": hours,
            "max_reading_age_minutes": max(ages) if ages else None,
            "recent_live_max_age_minutes": RECENT_LIVE_MAX_AGE_MINUTES,
        },
    }
