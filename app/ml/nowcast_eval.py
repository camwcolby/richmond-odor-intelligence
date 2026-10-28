"""
Live validation of the risk nowcast, recomputed from the observation history
at every retrain. Nothing here is hard-coded: every number on the Model
Performance tab comes from the latest run.

Method (same as analysis/h2s-nowcast):
  * month-blocked cross-validation: each calendar month is scored by models
    trained on all other months
  * scores are blended with persistence and ranked as percentiles
  * the dashboard state (90% on, clears after 2 h below) is replayed
  * every exceedance (30+ ppb, readings within 1 h merged) is checked for an
    elevated state in the 3 h before onset, and its warning time measured
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.ml import nowcast as nc

VALIDATION_PATH = Path(os.getenv("NOWCAST_VALIDATION_PATH", "data/nowcast_validation.json"))
EXCEEDANCE_PPB = 30.0
MIN_MONTHS = 6


def _episodes(hmax, thr=EXCEEDANCE_PPB, merge_gap="1h"):
    hit = hmax[hmax >= thr].index
    if len(hit) == 0:
        return []
    starts = [hit[0]]
    for a, b in zip(hit[:-1], hit[1:]):
        if b - a > pd.Timedelta(merge_gap):
            starts.append(b)
    return starts


def _oof(X, y, groups):
    p = pd.Series(np.nan, index=X.index)
    for g in groups.unique():
        te = groups == g
        tr = ~te
        if y[tr].sum() < 5:
            continue
        med = X[tr].median()
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=nc.C_REG, class_weight="balanced", max_iter=3000))
        m.fit(X[tr].fillna(med), y[tr])
        p[te] = m.predict_proba(X[te].fillna(med))[:, 1]
    return p


def _group_shares(model, medians, f_row, sensor):
    scaler, logit = model.named_steps["standardscaler"], model.named_steps["logisticregression"]
    cols = nc.sensor_cols(sensor)
    x = f_row[cols].fillna(medians).values.astype(float)
    contrib = pd.Series(logit.coef_[0] * (x - scaler.mean_) / scaler.scale_, index=cols)
    out = {}
    for name, pattern in nc.DRIVER_GROUPS.items():
        out[name] = max(0.0, float(contrib[[c.format(s=sensor) for c in pattern]].sum()))
    tot = sum(out.values())
    return {k: v / tot for k, v in out.items()} if tot > 0 else None


def evaluate(obs: pd.DataFrame, artifact: dict | None = None) -> dict:
    q_raw = nc.to_grid(obs)
    months = pd.Index(q_raw.index.strftime("%Y-%m")).nunique()
    if months < MIN_MONTHS:
        return {"available": False,
                "reason": f"validation needs {MIN_MONTHS}+ months of history (have {months})"}

    q, _ = nc.drift_correct(q_raw)
    f = nc.build_features(q)
    groups = pd.Series(q.index.strftime("%Y-%m"), index=q.index)
    probs = {}
    for s in nc.SENSORS:
        fut = nc._future_max(q[f"{s}_h2s_ppb"], nc.HORIZON_STEPS)
        ok = fut.notna() & q[f"{s}_h2s_ppb"].notna()
        y = (fut[ok] >= nc.LABEL_PPB).astype(int)
        probs[s] = _oof(f.loc[ok, nc.sensor_cols(s)], y, groups[ok]).reindex(q.index)
    plant = 1 - (1 - probs["north"].fillna(0)) * (1 - probs["south"].fillna(0))
    hmax_model = q[["north_h2s_ppb", "south_h2s_ppb"]].max(axis=1)
    persist = hmax_model.rolling(nc.STEPS_PER_H, min_periods=1).max().rank(pct=True)
    score = (nc.BLEND_MODEL_W * plant.rank(pct=True)
             + (1 - nc.BLEND_MODEL_W) * persist.fillna(0)).rank(pct=True)
    fav = nc._elevated_state(score)
    on_start = fav & ~fav.shift(1, fill_value=False)

    hmax = q_raw[["north_h2s_ppb", "south_h2s_ppb"]].max(axis=1)
    eps = []
    for t in _episodes(hmax):
        w = fav.loc[t - pd.Timedelta("3h"): t - pd.Timedelta("15min")]
        lead = None
        if w.any():
            st = on_start.loc[:w[w].index[-1]]
            lead = (t - st[st].index[-1]) / pd.Timedelta("1h")
        sensor = "north" if (q_raw["north_h2s_ppb"].loc[t: t + pd.Timedelta("1h")].max()
                             >= q_raw["south_h2s_ppb"].loc[t: t + pd.Timedelta("1h")].max()) else "south"
        eps.append({"onset": t, "sensor": sensor,
                    "peak_ppb": round(float(hmax.loc[t: t + pd.Timedelta("1h")].max()), 1),
                    "flagged": lead is not None,
                    "warning_hours": None if lead is None else round(lead, 2)})

    n = len(eps)
    flagged = sum(e["flagged"] for e in eps)
    chance = float(fav.astype(int).shift(1).rolling(12, min_periods=1).max().mean())
    ratio = None
    if n and flagged < n and 0 < chance < 1:
        ratio = (flagged / chance) / ((n - flagged) / (1 - chance))
    leads = np.array([e["warning_hours"] for e in eps if e["flagged"]], dtype=float)
    bins = [("Under 1h", 0, 1), ("1-2h", 1, 2), ("2-3h", 2, 3), ("3-4h", 3, 4),
            ("4-5h", 4, 5), ("5h+", 5, 1e9)]

    # what raised the risk at each onset (model fit on all history), averaged
    shares = []
    model_src = artifact or {}
    for e in eps:
        s, t0 = e["sensor"], e["onset"] - pd.Timedelta("15min")
        if t0 not in f.index or s not in model_src.get("models", {}):
            continue
        sh = _group_shares(model_src["models"][s], model_src["medians"][s], f.loc[t0], s)
        if sh:
            shares.append(sh)
    driver_shares = []
    if shares:
        avg = pd.DataFrame(shares).mean()
        driver_shares = [{"name": k, "share": round(float(v), 3)}
                         for k, v in avg.sort_values(ascending=False).items()]

    latest = None
    if eps:
        e = eps[-1]
        on = e["onset"]
        latest = {"onset_local": on.strftime("%Y-%m-%d %H:%M"),
                  "peak_ppb": e["peak_ppb"], "flagged": e["flagged"],
                  "warning_minutes": None if not e["flagged"] else round(e["warning_hours"] * 60)}
        if e["flagged"]:
            flag_t = on - pd.Timedelta(hours=e["warning_hours"])
            latest["elevated_local"] = flag_t.strftime("%Y-%m-%d %H:%M")

    elevated_time = fav[fav].index
    return {
        "available": True,
        "computed_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "month-blocked cross-validation (each month scored by models trained on the other months)",
        "period": f"{q.index[0]:%b %Y} to {q.index[-1]:%b %Y}",
        "history_start_utc": str(q.index[0].tz_convert("UTC")),
        "history_end_utc": str(q.index[-1].tz_convert("UTC")),
        "months": int(months),
        "exceedance_threshold_ppb": EXCEEDANCE_PPB,
        "episodes": n,
        "flagged_within_3h": int(flagged),
        "chance_rate": round(chance, 3),
        "rate_ratio": None if ratio is None else round(ratio, 1),
        "time_elevated_share": round(float(fav.mean()), 3),
        "elevated_share_oct_to_mar": (round(float(elevated_time.month.isin([10, 11, 12, 1, 2, 3]).mean()), 3)
                                      if len(elevated_time) else None),
        "median_warning_hours": round(float(np.median(leads)), 2) if len(leads) else None,
        "flagged_with_over_1h": int((leads > 1).sum()) if len(leads) else 0,
        "warning_bins": [{"label": lab, "count": int(((leads > lo) & (leads <= hi)).sum())}
                         for lab, lo, hi in bins] + [{"label": "Not flagged", "count": n - int(flagged)}],
        "driver_shares": driver_shares,
        "latest_exceedance": latest,
        "episodes_list": [{"onset_local": e["onset"].strftime("%Y-%m-%d %H:%M"), "peak_ppb": e["peak_ppb"],
                           "flagged": e["flagged"], "warning_hours": e["warning_hours"]} for e in eps],
    }


def save_validation(summary: dict):
    VALIDATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    VALIDATION_PATH.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")


def load_validation():
    if not VALIDATION_PATH.exists():
        return None
    try:
        return json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def retrain_and_validate(obs: pd.DataFrame) -> dict:
    """Weekly job: retrain the served model on all history, then recompute validation."""
    info = nc.train_nowcast(obs, persist=True)
    summary = evaluate(obs, nc.load_artifact())
    if summary.get("available"):
        summary["model"] = info
        save_validation(summary)
    return {"model": info, "validation_available": summary.get("available"),
            "validation_reason": summary.get("reason")}
