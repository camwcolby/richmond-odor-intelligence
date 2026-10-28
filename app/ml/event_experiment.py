"""Leakage-safe local experiment for the Oct 23 Richmond H2S event.

Usage: python -m app.ml.cli event-test
Requires a local historical database with observations before Oct 19.
Never changes the deployed model or saved artifacts.
"""
import json
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from app.ml.store import load_observations
from app.ml.pipeline import _base_features, _future_targets, PEAK_FEATURES, CHALLENGER_FEATURES, _peak_regressor

CUTOFF = pd.Timestamp("2026-10-19T00:00:00-07:00").tz_convert("UTC")
END = pd.Timestamp("2026-10-26T00:00:00-07:00").tz_convert("UTC")
ONSET = pd.Timestamp("2026-10-23T02:00:00-07:00").tz_convert("UTC")

def run():
    raw = load_observations().sort_values("timestamp_utc")
    if raw.empty:
        return {"available": False, "reason": "Local observation database empty. Backfill locally before running."}
    x = _future_targets(_base_features(raw))
    # Purge the 60-minute label horizon at the cutoff.
    train = x.loc[x.timestamp_utc < CUTOFF - pd.Timedelta(minutes=60)].dropna(
        subset=["future_60m_max_h2s", "system_h2s_max"]
    ).copy()
    test = x.loc[(x.timestamp_utc >= CUTOFF) & (x.timestamp_utc < END)].copy()
    if len(train) < 700 or len(test) < 100:
        return {"available": False, "reason": "Insufficient pre-event training or event-week observations",
                "training_rows": len(train), "test_rows": len(test),
                "training_start": str(train.timestamp_utc.min()) if len(train) else None}
    y = train["future_60m_max_h2s"]
    baseline = _peak_regressor()
    baseline.fit(train[PEAK_FEATURES], y)
    weights = np.where(y >= 60, 12., np.where(y >= 30, 5., 1.))
    def challenger(features):
        return Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(
                max_iter=90, max_leaf_nodes=15, learning_rate=0.055,
                min_samples_leaf=25, l2_regularization=2., random_state=42))
        ])
    weighted = challenger(PEAK_FEATURES)
    weighted.fit(train[PEAK_FEATURES], y, model__sample_weight=weights)
    accelerated = challenger(CHALLENGER_FEATURES)
    accelerated.fit(train[CHALLENGER_FEATURES], y, model__sample_weight=weights)
    outcomes = {}
    for name, model, features in [
        ("baseline_retrained_pre_event", baseline, PEAK_FEATURES),
        ("weighted_without_acceleration", weighted, PEAK_FEATURES),
        ("weighted_with_acceleration", accelerated, CHALLENGER_FEATURES),
    ]:
        scored = test.copy()
        scored["pred"] = np.maximum(0, model.predict(test[features]))
        before = scored.loc[
            (scored.timestamp_utc >= ONSET - pd.Timedelta(minutes=60))
            & (scored.timestamp_utc < ONSET)
            & (scored.system_h2s_max < 30)
        ]
        outcomes[name] = {
            "max_forecast_60min_before_onset_ppb": round(float(before.pred.max()), 2) if len(before) else None,
            "warned_30_before_onset": bool((before.pred >= 30).any()),
            "warned_60_before_onset": bool((before.pred >= 60).any()),
            "first_warning_30_utc": str(before.loc[before.pred >= 30, "timestamp_utc"].min()) if (before.pred >= 30).any() else None,
            "first_warning_60_utc": str(before.loc[before.pred >= 60, "timestamp_utc"].min()) if (before.pred >= 60).any() else None,
            "forecast_positive_intervals_30": int((scored.pred >= 30).sum()),
            "forecast_positive_intervals_60": int((scored.pred >= 60).sum()),
        }
    return {"available": True, "training_rows": len(train), "training_start": str(train.timestamp_utc.min()),
            "training_end": str(train.timestamp_utc.max()), "test_rows": len(test),
            "event_onset_utc": str(ONSET), "models": outcomes,
            "note": "Research experiment, not logged live forecasts; model trained strictly before event week."}

if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
