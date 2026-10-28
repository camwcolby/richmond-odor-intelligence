# H2S odor-risk nowcast: method and validation

This folder holds the offline evaluation behind the dashboard's risk state
(`app/ml/nowcast.py`). The app serves the trained artifact in
`data/nowcast_model.joblib`; this script reproduces the validation.

## What the dashboard shows

One state, refreshed every 15 minutes:

- **Elevated**: the risk score is in the top 10% of all 15-minute periods in
  the training history (90th percentile or higher).
- **Normal**: the state clears after 2 hours below the 90th percentile.

There are no push notifications. Elevated means conditions favor odor reaching
the fence-line sensors in the next 3 hours. It is a risk state, not a forecast
of a specific reading.

## Model

- One logistic regression per sensor (north, south), target: any reading of
  20 ppb or more in the next 3 hours. L2, C = 0.03, balanced class weights.
- Features use only data at or before the issue time: wind speed and calm
  duration, temperature change and dewpoint depression (stability), time of
  day, tide level and rate, 24 h rain, wind alignment from the plant to each
  sensor, and each sensor's recent dynamics (last reading, 15-minute change,
  1 h max and mean, 24 h median and max, anomaly vs its own 24 h median,
  count of 15+ ppb readings in 72 h, and the other sensor's 1 h max).
- Sensor drift: each sensor's rolling 7-day 5th-percentile floor is tracked,
  and any rise above its long-run typical floor is subtracted before modeling.
- Plant probability = 1 - (1 - p_north)(1 - p_south), blended 70/30 with the
  last-hour max reading (persistence), then ranked as a percentile.

## Validation snapshot (Oct 2024 to Oct 2026, month-blocked cross-validation)

The live site recomputes these numbers weekly from its own history
(`app/ml/nowcast_eval.py`); the Model Performance tab always shows the latest run.
The table below is the original offline analysis.

Each month was scored by a model trained on the other months.

| Measure | Result |
|---|---|
| Exceedances (30+ ppb), episodes | 26 |
| Elevated state within 3 h before onset | 22 of 26 |
| Chance rate for a random moment | about 26% |
| Rate ratio (exceedance after a flag vs not) | about 16x |
| Time spent elevated | about 18%, two-thirds of it October through March |
| Median warning (flag start to onset) | 2.5 h; 16 of 22 flagged had more than 1 h |
| Oct 23, 2026 (70 ppb, 2:00 AM) | elevated at 1:45 AM, 15 minutes before the peak |

Average share of what raised the risk before an exceedance: plant odor signal
(recent sensor dynamics) 66%, weather and stability 23%, wind toward the
sensor 6%, tide and rain 5%.

Limits: 4 of 26 exceedances had no advance flag. Fast releases in dead air
give the least warning. The model uses public sensor, weather and tide data
only; plant process data would be the natural next input.

The served artifact is trained on the full two years, so its in-sample
numbers differ slightly from the cross-validated ones above (21 of 26 flagged
when the full history is replayed against the stored percentile grid).

## Reproduce

```
# export observations (ml_observations columns) to CSV, then:
python analysis/h2s-nowcast/evaluate_nowcast.py history.csv

# retrain the served artifact
python -m app.ml.cli train-nowcast --csv history.csv
# or from the local history database
python -m app.ml.cli train-nowcast
python -m app.ml.cli nowcast
```
