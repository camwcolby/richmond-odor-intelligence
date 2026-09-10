
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import pandas as pd

def _ts(value):
    if value is None:
        return None
    try:
        t = pd.Timestamp(value)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")
        return t
    except Exception:
        return None

def _age_minutes(value):
    t = _ts(value)
    if t is None:
        return None
    now = pd.Timestamp.now(tz="UTC")
    return round(max(0.0, (now - t).total_seconds() / 60.0), 1)

def _valid(obs: dict[str, Any]) -> bool:
    value = obs.get("value")
    if value is None:
        return False
    try:
        if float(value) == -999:
            return False
    except Exception:
        return False
    qc = str(obs.get("qc") or obs.get("qcName") or "").lower()
    return "missing" not in qc

def summarize_history_payload(payload: dict[str, Any], hours: int) -> dict[str, Any]:
    observations = payload.get("observations", []) if isinstance(payload, dict) else []
    result = {
        "hours_requested": hours,
        "source": payload.get("source") if isinstance(payload, dict) else None,
        "observation_count": len(observations),
        "streams": [],
    }

    for stream_id, name in [(9950, "North Side"), (9963, "South Side")]:
        rows = [o for o in observations if str(o.get("data_stream_id")) == str(stream_id)]
        rows = sorted(rows, key=lambda x: str(x.get("timestamp_utc") or ""))
        raw_latest = rows[-1] if rows else None
        valid_rows = [o for o in rows if _valid(o)]
        valid_latest = valid_rows[-1] if valid_rows else None

        result["streams"].append({
            "data_stream_id": stream_id,
            "name": name,
            "returned_observations": len(rows),
            "valid_observations": len(valid_rows),
            "latest_raw": None if raw_latest is None else {
                "timestamp_utc": raw_latest.get("timestamp_utc"),
                "value": raw_latest.get("value"),
                "qc": raw_latest.get("qc"),
                "operation_qc": raw_latest.get("operation_qc"),
                "age_minutes": _age_minutes(raw_latest.get("timestamp_utc")),
            },
            "latest_valid": None if valid_latest is None else {
                "timestamp_utc": valid_latest.get("timestamp_utc"),
                "value": valid_latest.get("value"),
                "qc": valid_latest.get("qc"),
                "operation_qc": valid_latest.get("operation_qc"),
                "age_minutes": _age_minutes(valid_latest.get("timestamp_utc")),
            },
        })

    return result

async def build_h2s_diagnostics() -> dict[str, Any]:
    from app.services.h2s import get_h2s_history

    windows = []
    for hours in [2, 6, 24]:
        try:
            payload = await get_h2s_history(hours=hours)
            windows.append(summarize_history_payload(payload, hours))
        except Exception as exc:
            windows.append({
                "hours_requested": hours,
                "error": str(exc),
                "streams": [],
            })

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "windows": windows,
        "interpretation": (
            "If latest_raw is Missing/-999 but latest_valid is recent, Sonoma is reachable "
            "and the newest slot is incomplete. If even 24-hour history has no valid "
            "observations, investigate upstream Sonoma availability, stream IDs, token/session, "
            "or request schema."
        ),
    }
