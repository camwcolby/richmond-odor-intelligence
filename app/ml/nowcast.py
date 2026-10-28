"""
Odor-risk nowcast: is the plant in an odor-favorable (elevated-risk) state right now?

One logistic model per fence-line sensor predicts whether that sensor reads
>= 20 ppb at any point in the next 3 hours. The two are combined into a plant
probability, blended with recent readings (persistence), and ranked against the
training history so the score reads as a percentile of all 15-minute periods.

The dashboard shows a single state:
  * Elevated: score in the top 10% of conditions (>= 90th percentile)
  * Normal:   clears after 2 hours below the 90th percentile

Validated on two years of data (Oct 2024 to Oct 2026) with month-blocked
cross-validation: 22 of 26 exceedances >= 30 ppb were preceded by an elevated
state within 3 hours; median warning about 2.5 hours. See
analysis/h2s-nowcast/README.md for the full evaluation.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

TZ = "America/Los_Angeles"
STEPS_PER_H = 4
HORIZON_STEPS = 12                     # 3 hours of 15-minute steps
LABEL_PPB = 20.0
SENSORS = {"north": 155.0, "south": 336.0}   # bearing from sensor to plant, degrees
BLEND_MODEL_W = 0.7
ELEVATED_CUT = 0.90
CLEAR_STEPS = 8                        # 2 hours below the cut before clearing
C_REG = 0.03
QUANTILE_GRID = np.linspace(0, 1, 2001)
LOOKBACK = pd.Timedelta("10D")         # history needed for drift floor and 72h counts
MODEL_VERSION = "nowcast-logit-3h-v1"
MIN_ROWS = 6 * STEPS_PER_H              # 6 hours: enough to score; long-window features use typical values
FULL_ROWS = 3 * 24 * STEPS_PER_H        # 3 days: all features have real history
STALE_MINUTES = 90                     # flag the state if the newest observation is older than this

NOWCAST_PATH = Path(os.getenv("NOWCAST_MODEL_PATH", "data/nowcast_model.joblib"))

MET = ["wind_speed_mps", "wind_direction_deg", "temperature_f",
       "relative_humidity_pct", "rain_24h_in", "tide_ft_mllw"]

SHARED = ["ws", "log_ws", "stagnant", "calm_run_h", "ws_min_3h", "ws_change_2h",
          "dewpoint_dep_c", "rh", "dT_3h", "hr_sin", "hr_cos", "night",
          "stable_night", "tide", "tide_rate", "ebb_low", "rain_24h",
          "wd_sin", "wd_cos"]

DRIVER_GROUPS = {
    "Weather (dispersion and stability)": [
        "ws", "log_ws", "stagnant", "calm_run_h", "ws_min_3h", "ws_change_2h",
        "dewpoint_dep_c", "rh", "dT_3h", "hr_sin", "hr_cos", "night", "stable_night"],
    "Plant odor signal": [
        "{s}_last", "{s}_d15", "{s}_max_1h", "{s}_mean_1h", "{s}_max_24h", "{s}_med_24h",
        "{s}_anom", "{s}_n15_72h", "other_max_1h_for_{s}"],
    "Wind toward the sensor": ["{s}_align", "{s}_plume", "{s}_light_aligned", "wd_sin", "wd_cos"],
    "Tide and rain": ["tide", "tide_rate", "ebb_low", "rain_24h"],
}


def sensor_cols(s):
    return SHARED + [f"{s}_{c}" for c in
                     ["align", "plume", "light_aligned", "last", "d15", "max_1h",
                      "mean_1h", "max_24h", "med_24h", "anom", "n15_72h"]] \
                  + [f"other_max_1h_for_{s}"]


# ------------------------------------------------------------
# data + features (every feature uses rows at or before t)
# ------------------------------------------------------------
def to_grid(obs: pd.DataFrame) -> pd.DataFrame:
    """ml_observations rows -> regular 15-minute grid indexed in local time."""
    d = obs.copy()
    d["t"] = pd.to_datetime(d["timestamp_utc"], utc=True).dt.tz_convert(TZ)
    d = d.sort_values("t").drop_duplicates("t").set_index("t")
    cols = ["north_h2s_ppb", "south_h2s_ppb"] + MET
    q = d[cols].apply(pd.to_numeric, errors="coerce").resample("15min").first()
    q[MET] = q[MET].ffill(limit=4)
    return q


def drift_correct(q: pd.DataFrame, floor_medians: dict | None = None):
    """Remove upward zero drift: subtract the rise of each sensor's rolling 7-day
    5th-percentile floor above its long-run typical floor."""
    q = q.copy()
    medians = {}
    for s in SENSORS:
        x = q[f"{s}_h2s_ppb"]
        floor = x.rolling("7D", min_periods=2 * 24 * STEPS_PER_H).quantile(0.05).shift(1)
        med = float(floor.median()) if floor_medians is None else float(floor_medians[s])
        medians[s] = med
        q[f"{s}_h2s_ppb"] = x - (floor - med).clip(lower=0).fillna(0)
    return q, medians


def build_features(q: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=q.index)
    H = STEPS_PER_H
    ws, wd = q["wind_speed_mps"], q["wind_direction_deg"]
    f["ws"] = ws
    f["log_ws"] = np.log1p(ws)
    f["stagnant"] = (ws < 1.0).astype(int)
    calm = ws < 1.0
    f["calm_run_h"] = calm.astype(int).groupby((~calm).cumsum()).cumsum() / H
    f["ws_min_3h"] = ws.rolling(3 * H, min_periods=1).min()
    f["ws_change_2h"] = ws - ws.shift(2 * H)

    T = q["temperature_f"]
    Tc = (T - 32) * 5 / 9
    rh = q["relative_humidity_pct"].clip(1, 100)
    a_, b_ = 17.62, 243.12
    g = np.log(rh / 100) + a_ * Tc / (b_ + Tc)
    f["dewpoint_dep_c"] = Tc - b_ * g / (a_ - g)
    f["rh"] = rh
    f["dT_3h"] = T - T.shift(3 * H)
    hr = q.index.hour + q.index.minute / 60
    f["hr_sin"] = np.sin(2 * np.pi * hr / 24)
    f["hr_cos"] = np.cos(2 * np.pi * hr / 24)
    f["night"] = np.isin(q.index.hour, [21, 22, 23, 0, 1, 2, 3, 4, 5, 6]).astype(int)
    f["stable_night"] = f["night"] * f["stagnant"] * (f["dT_3h"] <= 0)

    tide = q["tide_ft_mllw"]
    f["tide"] = tide
    f["tide_rate"] = tide - tide.shift(H)
    f["ebb_low"] = ((f["tide_rate"] < 0) & (tide < 3)).astype(int)
    f["rain_24h"] = q["rain_24h_in"]
    f["wd_sin"] = np.sin(np.radians(wd)) * (ws >= 1.0)
    f["wd_cos"] = np.cos(np.radians(wd)) * (ws >= 1.0)

    for s, bearing in SENSORS.items():
        align = np.cos(np.radians(wd - bearing))
        moving = (ws >= 1.0).astype(int)
        f[f"{s}_align"] = align * moving
        f[f"{s}_plume"] = np.clip(align, 0, None) * moving / np.maximum(ws, 1.0)
        f[f"{s}_light_aligned"] = ((align > 0.7) & ws.between(1.0, 2.5)).astype(int)
        x = q[f"{s}_h2s_ppb"]
        med24 = x.rolling(24 * H, min_periods=6 * H).median()
        f[f"{s}_last"] = x
        f[f"{s}_d15"] = x.diff()
        f[f"{s}_max_1h"] = x.rolling(H, min_periods=1).max()
        f[f"{s}_mean_1h"] = x.rolling(H, min_periods=1).mean()
        f[f"{s}_max_24h"] = x.rolling(24 * H, min_periods=6 * H).max()
        f[f"{s}_med_24h"] = med24
        f[f"{s}_anom"] = x - med24
        f[f"{s}_n15_72h"] = (x >= 15).rolling(72 * H, min_periods=24 * H).sum()
    f["other_max_1h_for_north"] = f["south_max_1h"]
    f["other_max_1h_for_south"] = f["north_max_1h"]
    return f


def _future_max(x, steps):
    return x[::-1].rolling(steps, min_periods=1).max()[::-1].shift(-1)


def _rank(values, grid_q):
    """Percentile of values against a stored quantile grid (0-1)."""
    v = np.asarray(values, dtype=float)
    out = np.interp(v, grid_q, QUANTILE_GRID, left=0.0, right=1.0)
    return np.where(np.isnan(v), np.nan, out)


def _elevated_state(score: pd.Series) -> pd.Series:
    state, below, out = False, 0, []
    for v in score.fillna(0).values:
        below = 0 if v >= ELEVATED_CUT else below + 1
        if not state and v >= ELEVATED_CUT:
            state = True
        elif state and below >= CLEAR_STEPS:
            state = False
        out.append(state)
    return pd.Series(out, index=score.index)


# ------------------------------------------------------------
# training
# ------------------------------------------------------------
def train_nowcast(obs: pd.DataFrame, persist: bool = True) -> dict:
    q_raw = to_grid(obs)
    q, floor_medians = drift_correct(q_raw)
    f = build_features(q)
    models, medians = {}, {}
    for s in SENSORS:
        X = f[sensor_cols(s)]
        fut = _future_max(q[f"{s}_h2s_ppb"], HORIZON_STEPS)
        ok = fut.notna() & q[f"{s}_h2s_ppb"].notna()
        y = (fut[ok] >= LABEL_PPB).astype(int)
        med = X[ok].median()
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=C_REG, class_weight="balanced", max_iter=3000))
        m.fit(X[ok].fillna(med), y)
        models[s], medians[s] = m, med

    plant, _ = _plant_prob(models, medians, f)
    hmax = q[["north_h2s_ppb", "south_h2s_ppb"]].max(axis=1)
    persist_1h = hmax.rolling(STEPS_PER_H, min_periods=1).max()
    grid_plant = np.nanquantile(plant, QUANTILE_GRID)
    grid_persist = np.nanquantile(persist_1h, QUANTILE_GRID)
    blended = BLEND_MODEL_W * _rank(plant, grid_plant) + (1 - BLEND_MODEL_W) * _rank(persist_1h, grid_persist)
    grid_blend = np.nanquantile(blended, QUANTILE_GRID)

    artifact = {
        "version": MODEL_VERSION,
        "models": models, "medians": medians, "floor_medians": floor_medians,
        "grid_plant": grid_plant, "grid_persist": grid_persist, "grid_blend": grid_blend,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "training_start_utc": str(q.index[0].tz_convert("UTC")),
        "training_through_utc": str(q.index[-1].tz_convert("UTC")),
        "training_rows": int(len(q)),
    }
    if persist:
        NOWCAST_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(artifact, NOWCAST_PATH, compress=3)
    return {k: v for k, v in artifact.items() if k.startswith(("version", "trained", "training"))}


def _plant_prob(models, medians, f):
    probs = {}
    for s in SENSORS:
        X = f[sensor_cols(s)].fillna(medians[s])
        probs[s] = pd.Series(models[s].predict_proba(X)[:, 1], index=f.index)
        probs[s][f[f"{s}_last"].isna()] = 0.0
    plant = 1 - (1 - probs["north"]) * (1 - probs["south"])
    return plant, probs


# ------------------------------------------------------------
# scoring
# ------------------------------------------------------------
def score_history(obs: pd.DataFrame, artifact: dict) -> pd.DataFrame:
    q_raw = to_grid(obs)
    q, _ = drift_correct(q_raw, artifact["floor_medians"])
    f = build_features(q)
    plant, probs = _plant_prob(artifact["models"], artifact["medians"], f)
    hmax = q[["north_h2s_ppb", "south_h2s_ppb"]].max(axis=1)
    persist_1h = hmax.rolling(STEPS_PER_H, min_periods=1).max()
    blended = BLEND_MODEL_W * _rank(plant, artifact["grid_plant"]) \
        + (1 - BLEND_MODEL_W) * np.nan_to_num(_rank(persist_1h, artifact["grid_persist"]))
    score = pd.Series(_rank(blended, artifact["grid_blend"]), index=q.index)
    out = pd.DataFrame({"score": score, "elevated": _elevated_state(score),
                        "north_prob": probs["north"], "south_prob": probs["south"],
                        "north_raw": q_raw["north_h2s_ppb"], "south_raw": q_raw["south_h2s_ppb"]})
    out.attrs["features"] = f
    return out


def _drivers(artifact, f_row: pd.Series, sensor: str):
    m = artifact["models"][sensor]
    scaler, logit = m.named_steps["standardscaler"], m.named_steps["logisticregression"]
    cols = sensor_cols(sensor)
    x = f_row[cols].fillna(artifact["medians"][sensor]).values.astype(float)
    contrib = pd.Series(logit.coef_[0] * (x - scaler.mean_) / scaler.scale_, index=cols)
    shares = {}
    for name, pattern in DRIVER_GROUPS.items():
        names = [c.format(s=sensor) for c in pattern]
        shares[name] = max(0.0, float(contrib[names].sum()))
    total = sum(shares.values()) or 1.0
    return [{"name": k, "share": round(v / total, 3)}
            for k, v in sorted(shares.items(), key=lambda kv: -kv[1])]


def load_artifact():
    if not NOWCAST_PATH.exists():
        return None
    try:
        return joblib.load(NOWCAST_PATH)
    except Exception:
        return None


def predict_nowcast(obs: pd.DataFrame | None = None) -> dict:
    artifact = load_artifact()
    if artifact is None:
        return {"available": False, "reason": "nowcast model artifact not found"}
    if obs is None:
        from app.ml.store import load_observations
        obs = load_observations()
    if obs is None or obs.empty:
        return {"available": False, "reason": "observation history is rebuilding"}
    ts = pd.to_datetime(obs["timestamp_utc"], utc=True)
    obs = obs.loc[ts >= ts.max() - LOOKBACK]
    if len(obs) < MIN_ROWS:
        return {"available": False, "reason": "collecting the first hours of sensor data"}
    warming_up = len(obs) < FULL_ROWS

    hist = score_history(obs, artifact)
    valid = hist.dropna(subset=["score"])
    if valid.empty:
        return {"available": False, "reason": "no scoreable recent observations"}
    now = valid.index[-1]
    row = valid.iloc[-1]
    elevated = bool(row["elevated"])
    since = None
    if elevated:
        off = valid.index[~valid["elevated"]]
        off = off[off < now]
        since = (off[-1] + pd.Timedelta("15min")) if len(off) else valid.index[0]
    sensor = "north" if row["north_prob"] >= row["south_prob"] else "south"
    f = hist.attrs["features"]
    recent = valid["elevated"].resample("1h").max().tail(6)
    pct = float(row["score"]) * 100
    age_min = (pd.Timestamp.now(tz="UTC") - now.tz_convert("UTC")).total_seconds() / 60
    return {
        "available": True,
        "model_version": artifact["version"],
        "timestamp_utc": now.tz_convert("UTC").isoformat(),
        "state": "Elevated" if elevated else "Normal",
        "elevated": elevated,
        "elevated_since_utc": since.tz_convert("UTC").isoformat() if since is not None else None,
        "risk_percentile": round(pct, 1),
        "elevated_cut_percentile": ELEVATED_CUT * 100,
        "lead_sensor": sensor,
        "drivers": _drivers(artifact, f.loc[now], sensor),
        "recent_hours": [{"hour_utc": t.tz_convert("UTC").isoformat(), "elevated": bool(v)}
                         for t, v in recent.items()],
        "data_age_minutes": round(age_min),
        "stale": bool(age_min > STALE_MINUTES),
        "warming_up": bool(warming_up),
        "training_through_utc": artifact.get("training_through_utc"),
        "note": ("Elevated means conditions are in the top 10% for odor reaching the fence line "
                 "in the next 3 hours. It is a risk state, not a prediction of a specific reading."),
    }
