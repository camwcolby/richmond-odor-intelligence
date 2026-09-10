
from __future__ import annotations
import pandas as pd

def _iso_utc(value):
    if value is None or pd.isna(value):
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()

def h2s_fallback_from_ml_store():
    from app.ml.store import load_observations

    df = load_observations()
    if df is None or df.empty or "timestamp_utc" not in df.columns:
        return None

    frame = df.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame = frame[frame["timestamp_utc"].notna()].sort_values("timestamp_utc")

    specs = [
        ("north_h2s_ppb", "9950", 9950, "North Side", 37.921047, -122.37995),
        ("south_h2s_ppb", "9963", 9963, "South Side", 37.91796, -122.37807),
    ]

    sensors = []
    newest = None

    for col, sid, stream, name, lat, lon in specs:
        if col not in frame.columns:
            continue

        vals = pd.to_numeric(frame[col], errors="coerce")
        valid = frame[vals.notna() & (vals != -999)]

        if valid.empty:
            continue

        row = valid.iloc[-1]
        value = float(pd.to_numeric(pd.Series([row[col]]), errors="coerce").iloc[0])
        ts = row["timestamp_utc"]

        if newest is None or ts > newest:
            newest = ts

        sensors.append({
            "id": sid,
            "data_stream_id": stream,
            "name": name,
            "lat": lat,
            "lon": lon,
            "h2s_ppb": round(value, 3),
            "unit": "PPB",
            "timestamp_utc": _iso_utc(ts),
            "timestamp_local": None,
            "qc": "Historical fallback",
            "operation_qc": "Historical fallback",
            "below_mdl": False,
            "mdl_ppb": 5.0,
            "simulated": False,
            "source": "Latest ingested Sonoma history",
        })

    if not sensors:
        return None

    return {
        "timestamp": _iso_utc(newest),
        "source": "Latest ingested Sonoma history",
        "simulated": False,
        "stale_fallback": True,
        "sensors": sensors,
        "metadata": {
            "fallback_reason": "Live Sonoma request returned no valid current observations.",
            "fallback_source": "ML observation store",
        },
    }
