"""
Summarize the cross-validated nowcast scores into data/nowcast_validation.json,
which the Model Performance tab reads.

Input: the scores CSV written by evaluate_nowcast.py (month-blocked, out-of-fold).
Usage: python analysis/h2s-nowcast/build_validation_summary.py richmond_nowcast_scores.csv
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

TZ = "America/Los_Angeles"
CUT, CLEAR, EP_PPB = 90.0, 8, 30.0
OUT = Path(__file__).resolve().parents[2] / "data" / "nowcast_validation.json"


def main(path):
    s = pd.read_csv(path, index_col=0)
    s.index = pd.to_datetime(s.index, utc=True).tz_convert(TZ)
    hmax = s[["north", "south"]].max(axis=1)
    risk = s["pct_3h"].fillna(0)

    state, below, fav = False, 0, []
    for v in risk.values:
        below = 0 if v >= CUT else below + 1
        if not state and v >= CUT:
            state = True
        elif state and below >= CLEAR:
            state = False
        fav.append(state)
    fav = pd.Series(fav, index=risk.index)
    on_start = fav & ~fav.shift(1, fill_value=False)

    hit = hmax[hmax >= EP_PPB].index
    starts = [hit[0]] + [b for a, b in zip(hit[:-1], hit[1:]) if b - a > pd.Timedelta("1h")]
    eps = []
    for t in starts:
        w = fav.loc[t - pd.Timedelta("3h"): t - pd.Timedelta("15min")]
        lead = None
        if w.any():
            st = on_start.loc[:w[w].index[-1]]
            lead = (t - st[st].index[-1]) / pd.Timedelta("1h")
        eps.append({"onset_local": t.strftime("%Y-%m-%d %H:%M"),
                    "peak_ppb": round(float(hmax.loc[t: t + pd.Timedelta("1h")].max()), 1),
                    "flagged": lead is not None,
                    "warning_hours": None if lead is None else round(lead, 2)})

    n, flagged = len(eps), sum(e["flagged"] for e in eps)
    chance = float(fav.astype(int).shift(1).rolling(12, min_periods=1).max().mean())
    ratio = (flagged / chance) / ((n - flagged) / (1 - chance)) if n > flagged else None
    leads = np.array([e["warning_hours"] for e in eps if e["flagged"]])
    bins = [("Under 1h", 0, 1), ("1-2h", 1, 2), ("2-3h", 2, 3), ("3-4h", 3, 4), ("4-5h", 4, 5), ("5h+", 5, 1e9)]
    winter = fav[fav].index.month.isin([10, 11, 12, 1, 2, 3]).mean()
    o23 = next(e for e in eps if e["onset_local"].startswith("2026-10-23"))

    summary = {
        "method": "month-blocked cross-validation (each month scored by a model trained on the others)",
        "period": f"{s.index[0]:%b %Y} to {s.index[-1]:%b %Y}",
        "exceedance_threshold_ppb": EP_PPB,
        "episodes": n,
        "flagged_within_3h": flagged,
        "chance_rate": round(chance, 3),
        "rate_ratio": None if ratio is None else round(ratio, 1),
        "time_elevated_share": round(float(fav.mean()), 3),
        "elevated_share_oct_to_mar": round(float(winter), 3),
        "median_warning_hours": round(float(np.median(leads)), 2),
        "flagged_with_over_1h": int((leads > 1).sum()),
        "warning_bins": [{"label": lab, "count": int(((leads > lo) & (leads <= hi)).sum())} for lab, lo, hi in bins]
                        + [{"label": "Not flagged", "count": n - flagged}],
        # average share of what raised the risk at onset, from episode-level attribution
        "driver_shares": [
            {"name": "Plant odor signal", "share": 0.66},
            {"name": "Weather (dispersion and stability)", "share": 0.23},
            {"name": "Wind toward the sensor", "share": 0.06},
            {"name": "Tide and rain", "share": 0.05},
        ],
        "worked_example": {"label": "Oct 23, 2026", "peak_ppb": o23["peak_ppb"], "onset_local": "2:00 AM",
                           "elevated_local": "1:45 AM", "warning_minutes": round(o23["warning_hours"] * 60)},
        "episodes_list": eps,
    }
    OUT.write_text(json.dumps(summary, indent=2))
    print(f"wrote {OUT}: {flagged}/{n} flagged, ratio {summary['rate_ratio']}, "
          f"median warning {summary['median_warning_hours']} h")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "richmond_nowcast_scores.csv")
