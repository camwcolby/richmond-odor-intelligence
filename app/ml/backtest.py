"""Read-only replay of the deployed peak model against historical H2S."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import joblib
import numpy as np
import pandas as pd
from app.ml.store import MODEL_PATH, load_observations
from app.ml.pipeline import _base_features, PEAK_FEATURES

PACIFIC = ZoneInfo("America/Los_Angeles")
THRESHOLDS = (30.0, 60.0)

def backtest(start_date="2026-10-19", end_date="2026-10-25"):
    start_local = datetime.fromisoformat(start_date).replace(tzinfo=PACIFIC)
    end_local = datetime.fromisoformat(end_date).replace(tzinfo=PACIFIC) + timedelta(days=1)
    if end_local <= start_local or end_local - start_local > timedelta(days=32):
        raise ValueError("Select a positive date range of at most 31 days.")
    start = pd.Timestamp(start_local.astimezone(timezone.utc))
    end = pd.Timestamp(end_local.astimezone(timezone.utc))
    raw = load_observations()
    if raw.empty:
        return {"available": False, "reason": "No historical observations in Render database"}
    if not MODEL_PATH.exists():
        return {"available": False, "reason": "Production model artifact missing"}
    artifact = joblib.load(MODEL_PATH)
    if "peak_model" not in artifact:
        return {"available": False, "reason": "Peak model missing from artifact"}
    # Build features using earlier observations for lag/rolling warm-up.
    history = raw.loc[raw["timestamp_utc"] < end].copy()
    x = _base_features(history)
    selected = x.loc[(x.timestamp_utc >= start) & (x.timestamp_utc < end)].copy()
    if selected.empty:
        return {"available": False, "reason": "No observations in requested date range"}
    selected["prediction"] = np.maximum(
        0, artifact["peak_model"].predict(selected[artifact.get("peak_features", PEAK_FEATURES)])
    )
    # Strict 15-minute grid: future targets must not silently jump over missing slots.
    actual = history.set_index("timestamp_utc")["system_h2s_max"] if "system_h2s_max" in history else x.set_index("timestamp_utc")["system_h2s_max"]
    # The final hour of requested range may require observations after end.
    full = _base_features(raw)
    actual = full.set_index("timestamp_utc")["system_h2s_max"]
    for k in range(1, 5):
        selected[f"future_{k}"] = actual.reindex(
            selected["timestamp_utc"] + pd.Timedelta(minutes=15*k)
        ).to_numpy()
    selected["actual_future_max"] = selected[[f"future_{k}" for k in range(1,5)]].max(axis=1)
    selected["future_slots"] = selected[[f"future_{k}" for k in range(1,5)]].notna().sum(axis=1)
    # Only score complete horizons; incomplete ones cannot be called misses.
    scored = selected.loc[selected.future_slots == 4].copy()
    events = []
    for threshold in THRESHOLDS:
        readings = full.loc[(full.timestamp_utc >= start) & (full.timestamp_utc < end)].copy()
        readings["crossed"] = readings.system_h2s_max >= threshold
        # Distinct starts; allow 60 minutes below threshold before a new event.
        active = readings.crossed.fillna(False)
        starts = active & ~active.shift(1, fill_value=False)
        for _, onset in readings.loc[starts].iterrows():
            onset_ts = onset.timestamp_utc
            prior = scored.loc[
                (scored.timestamp_utc < onset_ts)
                & (scored.timestamp_utc >= onset_ts - pd.Timedelta(minutes=60))
            ]
            hits = prior.loc[prior.prediction >= threshold]
            first = hits.iloc[0] if not hits.empty else None
            events.append({
                "threshold_ppb": threshold,
                "onset_utc": onset_ts.isoformat(),
                "onset_local": onset_ts.tz_convert(PACIFIC).isoformat(),
                "sensor": ("North" if onset.north_h2s_ppb >= onset.south_h2s_ppb else "South"),
                "onset_h2s_ppb": round(float(onset.system_h2s_max),2),
                "forecast_detected": first is not None,
                "first_warning_utc": first.timestamp_utc.isoformat() if first is not None else None,
                "lead_minutes": int((onset_ts - first.timestamp_utc).total_seconds()/60) if first is not None else None,
                "max_prior_forecast_ppb": round(float(prior.prediction.max()),2) if not prior.empty else None,
                "prior_forecast_slots": len(prior),
            })
    intervals = []
    for threshold in THRESHOLDS:
        positive = scored.actual_future_max >= threshold
        predicted = scored.prediction >= threshold
        tp = int((positive & predicted).sum())
        intervals.append({
            "threshold_ppb": threshold,
            "actual_positive_intervals": int(positive.sum()),
            "forecast_positive_intervals": int(predicted.sum()),
            "recall": tp / int(positive.sum()) if positive.any() else None,
            "precision": tp / int(predicted.sum()) if predicted.any() else None,
        })
    return {
        "available": True, "analysis_type": "retrospective_model_replay_not_logged_live_forecasts",
        "model_version": artifact.get("version"),
        "start_date_local": start_date, "end_date_local": end_date,
        "observation_rows_in_window": len(selected), "scored_complete_horizons": len(scored),
        "event_count": len(events), "events": events,
        "threshold_interval_metrics": intervals,
        "notes": [
            "Replays the currently bundled model on historical features; it does not establish what the dashboard actually displayed.",
            "Forecasts are issued at observation timestamps and cover the following 60 minutes.",
            "The observed 30/60 ppb live risk override is not counted as advance warning.",
            "No event match is claimed when the preceding forecast window has no complete 60-minute horizons.",
            "This audit assumes observations were available at their recorded timestamps; historical ingestion delays are not reconstructed.",
        ],
    }
