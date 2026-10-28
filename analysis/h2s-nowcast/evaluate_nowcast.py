# ============================================================
# RICHMOND H2S NOWCAST  (15-minute rolling)
# At each 15-minute issue time t, uses only data observed at or
# before t to score the risk of a reading >= LABEL_PPB in the next
# 1 hour and next 3 hours. Evaluated by month-blocked CV, with
# warning lead time measured for every >= 30 ppb episode.
#
# Notebook: paste as a cell after Cell 5 (uses FULL_CSV and OUT_DIR).
# Command line: python richmond_h2s_nowcast.py path/to/history.csv
# ============================================================

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score

TZ = "America/Los_Angeles"
LABEL_PPB = 20.0
STEPS_PER_H = 4
HORIZONS = {"1h": 4, "3h": 12}          # in 15-minute steps
SENSORS = {"north": 155.0, "south": 336.0}   # bearing from sensor to plant
TIERS = [0, 0.80, 0.90, 0.97, 1.0]
TIER_LABELS = ["normal", "watch", "elevated", "high"]
BLEND_MODEL_W = 0.7      # final score = 0.7 model + 0.3 persistence (last-hour max), re-ranked
ALERT_ON_CUT = 0.90      # "elevated" percentile
ALERT_HOLD_STEPS = 1     # steps at/above cut before the alert turns on
ALERT_OFF_STEPS = 8      # steps below cut (2 h) before it clears

if "FULL_CSV" in globals():
    CSV = str(FULL_CSV)
elif len(sys.argv) > 1 and sys.argv[1].lower().endswith(".csv"):
    CSV = sys.argv[1]
else:
    CSV = "richmond_h2s_environmental_history.csv"
OUT = Path(OUT_DIR) if "OUT_DIR" in globals() else Path(".")
RISK_OUT = OUT / "richmond_nowcast_scores.csv"
PAGE_CUT = 0.98          # push alert when the 3h risk score reaches the top 2%
PAGE_COOLDOWN_H = 24     # at most one page per 24 hours; dashboard tiers update every 15 min
DRIFT_CORRECT = True     # remove upward sensor zero drift (rolling 7-day floor) before modeling


# ------------------------------------------------------------
# 1. DATA (native 15-minute grid)
# ------------------------------------------------------------
def load_15min(path):
    d = pd.read_csv(path)
    d["t"] = pd.to_datetime(d["timestamp_utc"], utc=True).dt.tz_convert(TZ)
    d = d.sort_values("t").drop_duplicates("t").set_index("t")
    q = d.resample("15min").first()
    met = ["wind_speed_mps", "wind_direction_deg", "temperature_f",
           "relative_humidity_pct", "rain_24h_in", "tide_ft_mllw"]
    q[met] = q[met].ffill(limit=4)
    return q


# ------------------------------------------------------------
# 2. FEATURES  (everything uses rows <= t)
# ------------------------------------------------------------
def build_features(q):
    f = pd.DataFrame(index=q.index)
    H = STEPS_PER_H
    ws, wd = q["wind_speed_mps"], q["wind_direction_deg"]

    # transport / dilution
    f["ws"] = ws
    f["log_ws"] = np.log1p(ws)
    f["stagnant"] = (ws < 1.0).astype(int)
    calm = ws < 1.0
    f["calm_run_h"] = calm.astype(int).groupby((~calm).cumsum()).cumsum() / H
    f["ws_min_3h"] = ws.rolling(3 * H, min_periods=1).min()
    f["ws_change_2h"] = ws - ws.shift(2 * H)          # negative = wind dying

    # stability
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

    # tide
    tide = q["tide_ft_mllw"]
    f["tide"] = tide
    f["tide_rate"] = tide - tide.shift(H)
    f["ebb_low"] = ((f["tide_rate"] < 0) & (tide < 3)).astype(int)
    f["rain_24h"] = q["rain_24h_in"]

    f["wd_sin"] = np.sin(np.radians(wd)) * (ws >= 1.0)
    f["wd_cos"] = np.cos(np.radians(wd)) * (ws >= 1.0)

    # per-sensor geometry + short-term sensor dynamics
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
        f[f"{s}_anom"] = x - med24                       # how far above its own normal
        f[f"{s}_n15_72h"] = (x >= 15).rolling(72 * H, min_periods=24 * H).sum()

    # the other sensor's reading can lead (a plume reaching one side first)
    f["other_max_1h_for_north"] = f["south_max_1h"]
    f["other_max_1h_for_south"] = f["north_max_1h"]
    return f


SHARED = ["ws", "log_ws", "stagnant", "calm_run_h", "ws_min_3h", "ws_change_2h",
          "dewpoint_dep_c", "rh", "dT_3h", "hr_sin", "hr_cos", "night",
          "stable_night", "tide", "tide_rate", "ebb_low", "rain_24h",
          "wd_sin", "wd_cos"]


def sensor_cols(s):
    return SHARED + [f"{s}_{c}" for c in
                     ["align", "plume", "light_aligned", "last", "d15", "max_1h",
                      "mean_1h", "max_24h", "med_24h", "anom", "n15_72h"]] \
                  + [f"other_max_1h_for_{s}"]


def future_max(x, steps):
    """max over t+1 .. t+steps (strictly after the issue time)."""
    return x[::-1].rolling(steps, min_periods=1).max()[::-1].shift(-1)


# ------------------------------------------------------------
# 3. MONTH-BLOCKED CV
# ------------------------------------------------------------
def oof_logit(X, y, groups, C=0.03):
    p = pd.Series(np.nan, index=X.index)
    for g in groups.unique():
        te = groups == g
        tr = ~te
        if y[tr].sum() < 5:
            continue
        med = X[tr].median()
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=C, class_weight="balanced", max_iter=3000))
        m.fit(X[tr].fillna(med), y[tr])
        p[te] = m.predict_proba(X[te].fillna(med))[:, 1]
    return p


def score(q, f, horizon_steps):
    groups = pd.Series(q.index.strftime("%Y-%m"), index=q.index)
    probs = {}
    for s in SENSORS:
        fut = future_max(q[f"{s}_h2s_ppb"], horizon_steps)
        ok = fut.notna()
        y = (fut >= LABEL_PPB).astype(int)
        probs[s] = oof_logit(f.loc[ok, sensor_cols(s)], y[ok], groups[ok]).reindex(q.index)
    plant = 1 - (1 - probs["north"].fillna(0)) * (1 - probs["south"].fillna(0))
    return plant.rank(pct=True), probs


# ------------------------------------------------------------
# 4. EVALUATION
# ------------------------------------------------------------
def episodes(hmax, thr, merge_gap="1h"):
    hit = hmax[hmax >= thr].index
    if len(hit) == 0:
        return []
    starts = [hit[0]]
    for a, b in zip(hit[:-1], hit[1:]):
        if b - a > pd.Timedelta(merge_gap):
            starts.append(b)
    return starts


def lead_table(pct, hmax, starts, lookback="3h"):
    rows = []
    for t0 in starts:
        win = pct.loc[t0 - pd.Timedelta(lookback): t0 - pd.Timedelta("15min")]
        row = {"onset": t0,
               "peak": round(hmax.loc[t0: t0 + pd.Timedelta("1h")].max(), 1),
               "max_pct_before": round(win.max() * 100, 1)}
        for name, cut in [("watch", 0.80), ("elevated", 0.90)]:
            above = win[win >= cut]
            row[f"lead_min_{name}"] = (int((t0 - above.index[0]).total_seconds() / 60)
                                       if len(above) else 0)
        rows.append(row)
    return pd.DataFrame(rows)


def alert_burden(pct, hmax, cut, horizon_steps):
    on = pct >= cut
    runs = (on & ~on.shift(1, fill_value=False)).cumsum()[on]
    fut = future_max(hmax, horizon_steps)
    n_alerts = runs.nunique()
    useful = sum((fut[runs[runs == r].index] >= LABEL_PPB).any() for r in runs.unique())
    days = (pct.index[-1] - pct.index[0]).days
    return n_alerts, n_alerts / days * 30, useful / max(n_alerts, 1)


def blend(model_pct, hmax):
    naive = hmax.rolling(STEPS_PER_H, min_periods=1).max().rank(pct=True)
    return (BLEND_MODEL_W * model_pct + (1 - BLEND_MODEL_W) * naive.fillna(0)).rank(pct=True), naive


def alert_state(p, on_cut=ALERT_ON_CUT, hold=ALERT_HOLD_STEPS, off=ALERT_OFF_STEPS):
    """Hysteresis so the alert doesn't flicker every 15 minutes."""
    state, above, below, out = False, 0, 0, []
    for v in p.fillna(0).values:
        above, below = (above + 1, 0) if v >= on_cut else (0, below + 1)
        if not state and above >= hold:
            state = True
        elif state and below >= off:
            state = False
        out.append(state)
    return pd.Series(out, index=p.index)


def page_times(p, cut=PAGE_CUT, cooldown_h=PAGE_COOLDOWN_H):
    out, last = [], None
    for t, v in p.fillna(0).items():
        if v >= cut and (last is None or t - last >= pd.Timedelta(hours=cooldown_h)):
            out.append(t)
            last = t
    return pd.DatetimeIndex(out)


def drift_correct(q):
    """Subtract upward drift in each sensor's floor (rolling 7-day 5th percentile,
    past data only) relative to its long-run typical floor. Downward moves are left
    alone. Regulatory evaluation still uses the raw readings."""
    q = q.copy()
    for s in SENSORS:
        x = q[f"{s}_h2s_ppb"]
        floor = x.rolling("7D", min_periods=2 * 24 * STEPS_PER_H).quantile(0.05).shift(1)
        q[f"{s}_floor"] = floor
        q[f"{s}_h2s_ppb"] = x - (floor - floor.median()).clip(lower=0).fillna(0)
    return q


def main():
    q_raw = load_15min(CSV)
    q = drift_correct(q_raw) if DRIFT_CORRECT else q_raw
    f = build_features(q)
    hmax = q_raw[["north_h2s_ppb", "south_h2s_ppb"]].max(axis=1)     # raw: what regulators see
    hmax_model = q[["north_h2s_ppb", "south_h2s_ppb"]].max(axis=1)   # corrected: feeds the blend

    # naive comparison: just alert on the latest reading being high
    naive = (hmax.rolling(STEPS_PER_H, min_periods=1).max()).rank(pct=True)

    results = {}
    for hname, steps in HORIZONS.items():
        model_pct, probs = score(q, f, steps)
        pct, _ = blend(model_pct, hmax_model)
        results[hname] = (pct, probs)
        fut = future_max(hmax, steps)
        v = fut.notna() & pct.notna() & naive.notna()
        print(f"\n=== next-{hname} nowcast ===")
        for thr in [20, 30, 60]:
            y = fut[v] >= thr
            print(f"  >= {thr} ppb  ROC-AUC model={roc_auc_score(y, pct[v]):.3f}  "
                  f"persistence only={roc_auc_score(y, naive[v]):.3f}  "
                  f"(positive steps {int(y.sum())})")

    pct3, probs3 = results["3h"]
    starts = episodes(hmax, 30)

    print("\nWARNING LEAD TIME before each >= 30 ppb episode (next-3h model)")
    lt = lead_table(pct3, hmax, starts)
    print(lt.to_string(index=False))
    print(f"  episodes with any 'watch' before onset:    {(lt.lead_min_watch > 0).sum()}/{len(lt)}")
    print(f"  episodes with any 'elevated' before onset: {(lt.lead_min_elevated > 0).sum()}/{len(lt)}")

    print("\nPersistence only (last-hour max), for comparison:")
    ln = lead_table(naive, hmax, starts)
    print(f"  watch before onset {(ln.lead_min_watch > 0).sum()}/{len(ln)}, "
          f"elevated before onset {(ln.lead_min_elevated > 0).sum()}/{len(ln)}")

    pg = page_times(pct3)
    months_all = (q.index[-1] - q.index[0]).days / 30.4
    fut24 = hmax[::-1].rolling("24h").max()[::-1]
    w24 = sum(((pg >= t - pd.Timedelta("24h")) & (pg < t)).any() for t in starts)
    print(f"\nPUSH ALERTS (top {100 - PAGE_CUT * 100:.0f}%, max one per {PAGE_COOLDOWN_H}h)")
    print(f"  {len(pg) / months_all:.1f} pages/month, "
          f"{np.mean([fut24.loc[t] >= LABEL_PPB for t in pg]) * 100:.0f}% followed by >= "
          f"{LABEL_PPB:.0f} ppb within 24h, page in the 24h before {w24}/{len(starts)} "
          f"of the >= 30 ppb episodes")
    print("  pages by calendar month:",
          pd.Series(1, index=pg).groupby(pg.month).sum().reindex(range(1, 13), fill_value=0).to_dict())

    al = alert_state(pct3)
    runs = (al & ~al.shift(1, fill_value=False)).cumsum()[al]
    fut3 = future_max(hmax, HORIZONS["3h"])
    useful = np.mean([(fut3[runs[runs == r].index] >= LABEL_PPB).any() for r in runs.unique()])
    months = (q.index[-1] - q.index[0]).days / 30.4
    caught = sum(al.loc[t - pd.Timedelta("3h"): t - pd.Timedelta("15min")].any() for t in starts)
    print("\nDASHBOARD ELEVATED STATE (90th pct, clears after 2h below; shown, not paged)")
    print(f"  {runs.nunique() / months:.1f} alerts/month, on {al.mean()*100:.1f}% of the time, "
          f"{useful*100:.0f}% followed by >= {LABEL_PPB:.0f} ppb within 3h "
          f"(base rate {(fut3 >= LABEL_PPB).mean()*100:.1f}%), "
          f"alert active before {caught}/{len(starts)} of the >= 30 ppb episodes")

    tier = pd.cut(pct3, TIERS, labels=TIER_LABELS)
    show = pd.DataFrame({
        "pct_1h": results["1h"][0] * 100, "pct_3h": pct3 * 100, "tier_3h": tier,
        "alert": alert_state(pct3),
        "north": q_raw["north_h2s_ppb"], "south": q_raw["south_h2s_ppb"],
        "ws": q["wind_speed_mps"], "wd": q["wind_direction_deg"],
    })
    print("\nOct 23 (held out), every 15 minutes:")
    print(show.loc["2026-10-22 23:00":"2026-10-23 02:30"].round(1).to_string())

    # interpretation: full-year coefficients for the 3h model
    for s in SENSORS:
        X = f[sensor_cols(s)]
        fut = future_max(q[f"{s}_h2s_ppb"], HORIZONS["3h"])
        ok = fut.notna()
        med = X.median()
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=0.03, class_weight="balanced", max_iter=3000))
        m.fit(X[ok].fillna(med), (fut[ok] >= LABEL_PPB).astype(int))
        coef = pd.Series(m[-1].coef_[0], index=X.columns)
        print(f"\n{s} top coefficients (3h):")
        print(coef.reindex(coef.abs().sort_values(ascending=False).index).head(10).round(2).to_string())

    # --------------------------------------------------------
    # MULTI-YEAR CHECKS (only when the history spans 2+ years)
    # --------------------------------------------------------
    span_days = (q.index[-1] - q.index[0]).days
    if span_days > 500:
        mid = q.index[0] + (q.index[-1] - q.index[0]) / 2
        yr = pd.Series(np.where(q.index < mid, "year_1", "year_2"), index=q.index)
        print("\nYEAR OVER YEAR (is the site behaving the same?)")
        print(pd.DataFrame({
            "median_h2s": hmax.groupby(yr).median(),
            "p99_h2s": hmax.groupby(yr).quantile(0.99),
            "readings_ge30": (hmax >= 30).groupby(yr).sum(),
            "episodes_ge30": pd.Series(episodes(hmax, 30)).map(
                lambda t: "year_1" if t < mid else "year_2").value_counts(),
        }).round(2).to_string())
        print("  (a big shift in median or p99 suggests sensor recalibration or an operational change;"
              " check before pooling)")

        print("\nTRAIN ON ONE YEAR, TEST ON THE OTHER (next-3h, before-onset catches)")
        for train_y, test_y in [("year_1", "year_2"), ("year_2", "year_1")]:
            probs_tt = {}
            for s in SENSORS:
                fut = future_max(q[f"{s}_h2s_ppb"], HORIZONS["3h"])
                y = (fut >= LABEL_PPB).astype(int)
                X = f[sensor_cols(s)]
                tr = (yr == train_y) & fut.notna()
                te = yr == test_y
                med = X[tr].median()
                m = make_pipeline(StandardScaler(),
                                  LogisticRegression(C=0.03, class_weight="balanced", max_iter=3000))
                m.fit(X[tr].fillna(med), y[tr])
                probs_tt[s] = pd.Series(m.predict_proba(X[te].fillna(med))[:, 1], index=X[te].index)
            plant = 1 - (1 - probs_tt["north"]) * (1 - probs_tt["south"])
            p_tt, _ = blend(plant.rank(pct=True), hmax_model[yr == test_y])
            st_te = [t for t in starts if yr.get(t) == test_y]
            months_te = (yr == test_y).sum() / (STEPS_PER_H * 24 * 30.4)
            for cut in [0.95, 0.97, 0.99]:
                al_tt = alert_state(p_tt, on_cut=cut)
                n = (al_tt & ~al_tt.shift(1, fill_value=False)).sum() / months_te
                c = sum(al_tt.loc[t - pd.Timedelta("3h"): t - pd.Timedelta("15min")].any() for t in st_te)
                print(f"  train {train_y} -> test {test_y}, top {100 - cut * 100:.0f}%: "
                      f"{n:4.1f} alerts/mo, catches {c}/{len(st_te)} of >= 30 episodes")

    show["north_prob_3h"] = probs3["north"]
    show["south_prob_3h"] = probs3["south"]
    show.to_csv(RISK_OUT)
    print(f"\nNowcast scores written to {RISK_OUT}")


if __name__ == "__main__":
    main()
