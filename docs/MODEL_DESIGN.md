# Model design

The demo intentionally does **not** pretend a trained model exists. `app/ml/risk.py`
returns an interpretable engineering score through an interface designed to be
replaced by a supervised model.

## Proposed targets
1. H2S concentration at each monitor for +15, +30, +60, +180 minutes.
2. Probability of an odor condition at a spatial receptor.
3. Probability of a community odor complaint.

## Candidate features
- lagged H2S: 5/15/30/60/180-minute values, slope, rolling max, exceedance duration
- wind speed, gust, direction encoded as sin/cos
- source-to-receptor bearing and downwind alignment
- temperature, humidity, pressure, solar radiation/cloud cover
- instantaneous and antecedent rainfall
- tide elevation, rising/falling state, rate of change
- sewer hotspot/source score and source-receptor distance
- hour of day, day of week, month/season
- plant/collection SCADA features when available
- recent complaint count/density, with leakage-safe lagging

## Validation
Use time-aware walk-forward validation. Do not randomly shuffle observations.
Report PR-AUC, ROC-AUC, Brier score/calibration, recall at operational alert
thresholds, false alarms per day, and lead time.

## Explainability
Persist SHAP values for production forecasts. The public UI should translate
features into plain-language drivers; technical users can expose full SHAP detail.
