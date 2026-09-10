
from __future__ import annotations

from datetime import datetime, timezone
import math

import joblib
import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline

from app.ml.store import MODEL_PATH, load_observations, save_metrics, load_metrics
from app.services.spatial import get_structures, get_hotspots

HIGH_THRESHOLD_PPB = 60.0
ELEVATED_THRESHOLD_PPB = 45.0
WATCH_THRESHOLD_PPB = 30.0
FORECAST_HORIZON_STEPS = 4

EXCURSION_ABS_RISE_PPB = 10.0
EXCURSION_REL_RISE = 0.50

AMBIENT_TRAIN_MAX_PPB = 30.0
MAX_FALSE_ALERTS_PER_WEEK = 2.0

SENSOR_COORDS = [
    (37.921047, -122.37995),
    (37.9205, -122.3780),
]

# Peak model intentionally returns to the v0.9 architecture.
# Environmental residual is explanatory and is NOT fed back into peak prediction.
PEAK_FEATURES = [
    "north_h2s_ppb",
    "south_h2s_ppb",
    "system_h2s_max",
    "h2s_lag15",
    "h2s_lag30",
    "h2s_lag60",
    "h2s_lag1h",
    "h2s_lag2h",
    "h2s_lag3h",
    "h2s_lag4h",
    "h2s_lag5h",
    "h2s_lag6h",
    "rollmax60",
    "rollmean60",
    "slope30",
    "wind_speed_mps",
    "wind_sin",
    "wind_cos",
    "wind_speed_delta1h",
    "wind_speed_delta3h",
    "wind_vector_shift1h",
    "wind_vector_shift3h",
    "temperature_f",
    "temperature_delta1h",
    "temperature_delta3h",
    "relative_humidity_pct",
    "humidity_delta1h",
    "humidity_delta3h",
    "precipitation_in",
    "rain_1h_in",
    "rain_24h_in",
    "rain_delta1h",
    "rain_delta3h",
    "tide_ft_mllw",
    "tide_delta1h",
    "tide_delta3h",
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos",
]

ENV_FEATURES = [
    "wind_speed_mps", "wind_sin", "wind_cos",
    "temperature_f", "relative_humidity_pct",
    "precipitation_in", "rain_1h_in", "rain_24h_in",
    "tide_ft_mllw", "tide_delta1h",
    "hour_sin", "hour_cos", "month_sin", "month_cos",
    "wwtp_alignment", "max_pump_alignment",
    "mean_pump_alignment", "max_sso_alignment",
]

EXCURSION_FEATURES = PEAK_FEATURES + [
    "wwtp_alignment", "max_pump_alignment",
    "mean_pump_alignment", "max_sso_alignment",
    "environmental_baseline_ppb",
    "excess_wastewater_contribution_ppb",
]


def _bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = np.deg2rad(lat1), np.deg2rad(lat2)
    dl = np.deg2rad(lon2 - lon1)
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.rad2deg(np.arctan2(y, x)) + 360.0) % 360.0


def _alignment_from_wind(wind_from_deg, bearing):
    if pd.isna(wind_from_deg):
        return np.nan
    wind_toward = (float(wind_from_deg) + 180.0) % 360.0
    delta = abs((wind_toward - bearing + 180.0) % 360.0 - 180.0)
    return max(0.0, math.cos(math.radians(delta)))


def _spatial_sources():
    wwtp, pumps, ssos = [], [], []

    try:
        fc = get_structures()
        for f in fc.get("features", []):
            props = f.get("properties") or {}
            coords = (f.get("geometry") or {}).get("coordinates") or []

            if len(coords) < 2:
                continue

            lon, lat = float(coords[0]), float(coords[1])
            cat = str(props.get("category") or "").lower()

            if "wwtp" in cat or "treatment plant" in cat:
                wwtp.append((lat, lon))
            elif "pump station" in cat:
                pumps.append((lat, lon))
    except Exception:
        pass

    try:
        for h in get_hotspots():
            if h.get("latitude") is not None and h.get("longitude") is not None:
                ssos.append((float(h["latitude"]), float(h["longitude"])))
    except Exception:
        pass

    return wwtp, pumps, ssos


def _source_alignment_series(wind_series, sources):
    if not sources:
        blank = pd.Series(np.nan, index=wind_series.index)
        return blank, blank.copy()

    bearings = []

    for slat, slon in sources:
        for rlat, rlon in SENSOR_COORDS:
            bearings.append(
                _bearing_deg(
                    slat,
                    slon,
                    rlat,
                    rlon,
                )
            )

    max_vals, mean_vals = [], []

    for wd in wind_series:
        vals = [
            _alignment_from_wind(wd, b)
            for b in bearings
        ]

        vals = [
            v for v in vals
            if not pd.isna(v)
        ]

        max_vals.append(
            max(vals)
            if vals
            else np.nan
        )

        mean_vals.append(
            float(np.mean(vals))
            if vals
            else np.nan
        )

    return (
        pd.Series(max_vals, index=wind_series.index),
        pd.Series(mean_vals, index=wind_series.index),
    )


def _base_features(df):
    x = df.copy().sort_values("timestamp_utc").reset_index(drop=True)

    x["north_h2s_ppb"] = pd.to_numeric(
        x["north_h2s_ppb"],
        errors="coerce",
    )

    x["south_h2s_ppb"] = pd.to_numeric(
        x["south_h2s_ppb"],
        errors="coerce",
    )

    x["system_h2s_max"] = x[
        ["north_h2s_ppb", "south_h2s_ppb"]
    ].max(axis=1)

    x["h2s_lag15"] = x["system_h2s_max"].shift(1)
    x["h2s_lag30"] = x["system_h2s_max"].shift(2)
    x["h2s_lag60"] = x["system_h2s_max"].shift(4)

    # v1.2.0: capped H2S memory, 1-6 hours only.
    # Rows are nominally 15-minute intervals.
    x["h2s_lag1h"] = x["system_h2s_max"].shift(4)
    x["h2s_lag2h"] = x["system_h2s_max"].shift(8)
    x["h2s_lag3h"] = x["system_h2s_max"].shift(12)
    x["h2s_lag4h"] = x["system_h2s_max"].shift(16)
    x["h2s_lag5h"] = x["system_h2s_max"].shift(20)
    x["h2s_lag6h"] = x["system_h2s_max"].shift(24)

    x["rollmax60"] = (
        x["system_h2s_max"]
        .rolling(4, min_periods=1)
        .max()
    )

    x["rollmean60"] = (
        x["system_h2s_max"]
        .rolling(4, min_periods=1)
        .mean()
    )

    x["slope30"] = (
        x["system_h2s_max"]
        - x["system_h2s_max"].shift(2)
    )

    wd = pd.to_numeric(
        x["wind_direction_deg"],
        errors="coerce",
    )

    x["wind_sin"] = np.sin(np.deg2rad(wd))
    x["wind_cos"] = np.cos(np.deg2rad(wd))

    tide = pd.to_numeric(
        x["tide_ft_mllw"],
        errors="coerce",
    )

    x["tide_delta1h"] = tide - tide.shift(4)

    # v1.2.0: compact environmental shifts.
    wind_speed = pd.to_numeric(x["wind_speed_mps"], errors="coerce")
    temperature = pd.to_numeric(x["temperature_f"], errors="coerce")
    humidity = pd.to_numeric(x["relative_humidity_pct"], errors="coerce")
    precipitation = pd.to_numeric(x["precipitation_in"], errors="coerce")

    x["wind_speed_delta1h"] = wind_speed - wind_speed.shift(4)
    x["wind_speed_delta3h"] = wind_speed - wind_speed.shift(12)

    x["temperature_delta1h"] = temperature - temperature.shift(4)
    x["temperature_delta3h"] = temperature - temperature.shift(12)

    x["humidity_delta1h"] = humidity - humidity.shift(4)
    x["humidity_delta3h"] = humidity - humidity.shift(12)

    x["tide_delta3h"] = tide - tide.shift(12)

    x["rain_delta1h"] = precipitation - precipitation.shift(4)
    x["rain_delta3h"] = precipitation - precipitation.shift(12)

    # Circular wind-direction movement, represented as vector distance.
    x["wind_vector_shift1h"] = np.sqrt(
        (x["wind_sin"] - x["wind_sin"].shift(4)) ** 2
        + (x["wind_cos"] - x["wind_cos"].shift(4)) ** 2
    )

    x["wind_vector_shift3h"] = np.sqrt(
        (x["wind_sin"] - x["wind_sin"].shift(12)) ** 2
        + (x["wind_cos"] - x["wind_cos"].shift(12)) ** 2
    )

    ts = pd.to_datetime(
        x["timestamp_utc"],
        utc=True,
    )

    hour = ts.dt.hour + ts.dt.minute / 60.0

    x["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    x["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    x["month_sin"] = np.sin(2 * np.pi * ts.dt.month / 12)
    x["month_cos"] = np.cos(2 * np.pi * ts.dt.month / 12)

    wwtp, pumps, ssos = _spatial_sources()

    if wwtp:
        x["wwtp_alignment"], _ = _source_alignment_series(
            wd,
            wwtp,
        )
    else:
        x["wwtp_alignment"] = np.nan

    x["max_pump_alignment"], x["mean_pump_alignment"] = (
        _source_alignment_series(
            wd,
            pumps,
        )
    )

    x["max_sso_alignment"], _ = (
        _source_alignment_series(
            wd,
            ssos,
        )
    )

    return x


def _future_targets(x):
    future = pd.concat(
        [
            x["system_h2s_max"].shift(-i)
            for i in range(
                1,
                FORECAST_HORIZON_STEPS + 1,
            )
        ],
        axis=1,
    ).max(axis=1)

    x["future_60m_max_h2s"] = future

    x.loc[
        x.index[-FORECAST_HORIZON_STEPS:],
        "future_60m_max_h2s",
    ] = np.nan

    current = x["system_h2s_max"].clip(lower=1.0)

    future_rise = (
        x["future_60m_max_h2s"]
        - x["system_h2s_max"]
    )

    valid = (
        x["system_h2s_max"].notna()
        & x["future_60m_max_h2s"].notna()
    )

    excursion = (
        (future_rise >= EXCURSION_ABS_RISE_PPB)
        & (
            (future_rise / current)
            >= EXCURSION_REL_RISE
        )
    )

    x["future_excursion"] = np.nan

    x.loc[
        valid,
        "future_excursion",
    ] = excursion.loc[
        valid
    ].astype(float)

    return x


def _peak_regressor():
    return Pipeline([
        (
            "impute",
            SimpleImputer(
                strategy="median",
                add_indicator=True,
            ),
        ),
        (
            "model",
            RandomForestRegressor(
                n_estimators=350,
                max_depth=12,
                min_samples_leaf=3,
                random_state=42,
                n_jobs=-1,
            ),
        ),
    ])


def _ambient_regressor():
    return Pipeline([
        (
            "impute",
            SimpleImputer(
                strategy="median",
                add_indicator=True,
            ),
        ),
        (
            "model",
            RandomForestRegressor(
                n_estimators=325,
                max_depth=10,
                min_samples_leaf=5,
                random_state=17,
                n_jobs=-1,
            ),
        ),
    ])


def _excursion_classifier():
    return Pipeline([
        (
            "impute",
            SimpleImputer(
                strategy="median",
                add_indicator=True,
            ),
        ),
        (
            "model",
            RandomForestClassifier(
                n_estimators=450,
                max_depth=10,
                min_samples_leaf=4,
                class_weight="balanced_subsample",
                random_state=23,
                n_jobs=-1,
            ),
        ),
    ])


def _walk_folds(frame, n_folds=6):
    n = len(frame)

    if n < 700:
        return []

    fold_size = max(
        350,
        n // (n_folds + 1),
    )

    folds = []

    for i in range(1, n_folds + 1):
        tr_end = fold_size * i
        te_end = min(
            tr_end + fold_size,
            n,
        )

        if te_end - tr_end < 100:
            break

        folds.append((
            frame.iloc[:tr_end].copy(),
            frame.iloc[tr_end:te_end].copy(),
        ))

    return folds


def _fit_ambient_and_residual(train, test):
    ordinary = train[
        train["system_h2s_max"].notna()
        & (
            train["system_h2s_max"]
            <= AMBIENT_TRAIN_MAX_PPB
        )
        & (
            train["rollmax60"].isna()
            | (
                train["rollmax60"]
                <= AMBIENT_TRAIN_MAX_PPB
            )
        )
    ].copy()

    if len(ordinary) < 200:
        ordinary = train.dropna(
            subset=["system_h2s_max"]
        ).copy()

    ambient = _ambient_regressor()

    ambient.fit(
        ordinary[ENV_FEATURES],
        ordinary["system_h2s_max"],
    )

    train = train.copy()
    test = test.copy()

    train["environmental_baseline_ppb"] = np.maximum(
        0.0,
        ambient.predict(
            train[ENV_FEATURES]
        ),
    )

    test["environmental_baseline_ppb"] = np.maximum(
        0.0,
        ambient.predict(
            test[ENV_FEATURES]
        ),
    )

    for frame in (train, test):
        frame["excess_wastewater_contribution_ppb"] = (
            frame["system_h2s_max"]
            - frame["environmental_baseline_ppb"]
        ).clip(lower=0.0)

    return ambient, train, test, len(ordinary)


def _subset_mae(y, pred, threshold):
    mask = y >= threshold

    if int(mask.sum()) == 0:
        return None

    return float(
        mean_absolute_error(
            y[mask],
            pred[mask.values],
        )
    )


def _eventize(binary):
    b = (
        pd.Series(binary)
        .fillna(0)
        .astype(int)
        .reset_index(drop=True)
    )

    starts = (
        b.eq(1)
        & b.shift(1, fill_value=0).eq(0)
    ).cumsum()

    return starts.where(
        b.eq(1),
        0,
    )


def _false_alert_events(y_true, y_pred):
    y_true = (
        pd.Series(y_true)
        .astype(int)
        .reset_index(drop=True)
    )

    y_pred = (
        pd.Series(y_pred)
        .astype(int)
        .reset_index(drop=True)
    )

    ids = _eventize(y_pred)
    false_events = 0

    for event_id in sorted(
        ids[ids > 0].unique()
    ):
        idx = ids[
            ids == event_id
        ].index

        if int(
            y_true.iloc[idx].sum()
        ) == 0:
            false_events += 1

    return false_events


def _threshold_table(validation):
    if (
        validation.empty
        or validation["actual"].nunique() < 2
    ):
        return []

    y = (
        validation["actual"]
        .astype(int)
        .reset_index(drop=True)
    )

    prob = (
        validation["probability"]
        .astype(float)
        .reset_index(drop=True)
    )

    ts = pd.to_datetime(
        validation["timestamp_utc"],
        utc=True,
    )

    total_days = max(
        1.0,
        (
            ts.max() - ts.min()
        ).total_seconds() / 86400.0,
    )

    rows = []

    for threshold in np.arange(
        0.05,
        0.76,
        0.025,
    ):
        pred = (
            prob >= threshold
        ).astype(int)

        precision = float(
            precision_score(
                y,
                pred,
                zero_division=0,
            )
        )

        recall = float(
            recall_score(
                y,
                pred,
                zero_division=0,
            )
        )

        false_events = (
            _false_alert_events(
                y,
                pred,
            )
        )

        false_per_week = (
            false_events
            / (total_days / 7.0)
        )

        rows.append({
            "threshold": float(
                round(
                    threshold,
                    3,
                )
            ),
            "precision": precision,
            "recall": recall,
            "false_alert_events": int(
                false_events
            ),
            "false_alerts_per_week": float(
                false_per_week
            ),
        })

    return rows


def _choose_operating_threshold(validation):
    """
    Operational choice:
    maximize recall subject to <= MAX_FALSE_ALERTS_PER_WEEK.

    If no candidate satisfies the nuisance ceiling, choose the candidate with
    the lowest false-alert rate and then the highest recall.
    """
    rows = _threshold_table(
        validation
    )

    if not rows:
        return {
            "threshold": 0.50,
            "precision": None,
            "recall": None,
            "false_alert_events": None,
            "false_alerts_per_week": None,
            "constraint_met": False,
        }, []

    feasible = [
        r for r in rows
        if (
            r["false_alerts_per_week"]
            <= MAX_FALSE_ALERTS_PER_WEEK
        )
    ]

    if feasible:
        best = sorted(
            feasible,
            key=lambda r: (
                -r["recall"],
                -r["precision"],
                r["false_alerts_per_week"],
            ),
        )[0]

        best = dict(best)
        best["constraint_met"] = True
    else:
        best = sorted(
            rows,
            key=lambda r: (
                r["false_alerts_per_week"],
                -r["recall"],
                -r["precision"],
            ),
        )[0]

        best = dict(best)
        best["constraint_met"] = False

    return best, rows


def train_model():
    raw = load_observations()

    if raw.empty:
        raise RuntimeError(
            "No historical observations are available."
        )

    x = _future_targets(
        _base_features(raw)
    )

    labeled = x.dropna(
        subset=[
            "future_60m_max_h2s",
            "system_h2s_max",
        ]
    ).copy()

    folds = _walk_folds(
        labeled
    )

    if not folds:
        raise RuntimeError(
            "Could not create walk-forward folds."
        )

    peak_predictions = []
    excursion_predictions = []
    ambient_fold_rows = []

    for fold_no, (
        tr_raw,
        te_raw,
    ) in enumerate(
        folds,
        1,
    ):
        _, tr, te, ordinary_rows = (
            _fit_ambient_and_residual(
                tr_raw,
                te_raw,
            )
        )

        ambient_fold_rows.append(
            int(ordinary_rows)
        )

        # Peak forecast excludes environmental baseline/residual.
        peak = _peak_regressor()

        peak.fit(
            tr[PEAK_FEATURES],
            tr["future_60m_max_h2s"],
        )

        peak_pred = np.maximum(
            0.0,
            peak.predict(
                te[PEAK_FEATURES]
            ),
        )

        peak_predictions.append(
            pd.DataFrame({
                "timestamp_utc": te[
                    "timestamp_utc"
                ].values,
                "actual": te[
                    "future_60m_max_h2s"
                ].values,
                "predicted": peak_pred,
                "fold": fold_no,
            })
        )

        # Excursion classifier can use wastewater residual diagnostics.
        if (
            tr["future_excursion"]
            .nunique(
                dropna=True
            )
            > 1
        ):
            exc = _excursion_classifier()

            exc.fit(
                tr[
                    EXCURSION_FEATURES
                ],
                tr[
                    "future_excursion"
                ].astype(int),
            )

            exc_prob = (
                exc.predict_proba(
                    te[
                        EXCURSION_FEATURES
                    ]
                )[:, 1]
            )

            excursion_predictions.append(
                pd.DataFrame({
                    "timestamp_utc": te[
                        "timestamp_utc"
                    ].values,
                    "actual": te[
                        "future_excursion"
                    ].astype(int).values,
                    "probability": exc_prob,
                    "fold": fold_no,
                })
            )

    pv = pd.concat(
        peak_predictions,
        ignore_index=True,
    )

    y = pv["actual"].astype(float)
    pp = pv["predicted"].astype(float).values

    peak_metrics = {
        "mae_ppb": float(
            mean_absolute_error(
                y,
                pp,
            )
        ),
        "rmse_ppb": float(
            math.sqrt(
                mean_squared_error(
                    y,
                    pp,
                )
            )
        ),
        "r2": float(
            r2_score(
                y,
                pp,
            )
        ) if len(y) > 1 else None,
        "mae_ge_30_ppb": _subset_mae(
            y,
            pp,
            30,
        ),
        "mae_ge_45_ppb": _subset_mae(
            y,
            pp,
            45,
        ),
        "validation_rows": int(
            len(pv)
        ),
        "rows_ge_30_ppb": int(
            (y >= 30).sum()
        ),
        "rows_ge_45_ppb": int(
            (y >= 45).sum()
        ),
    }

    if excursion_predictions:
        ev = pd.concat(
            excursion_predictions,
            ignore_index=True,
        )

        ey = ev[
            "actual"
        ].astype(int)

        eprob = ev[
            "probability"
        ].astype(float)

        operating, threshold_curve = (
            _choose_operating_threshold(
                ev
            )
        )

        threshold = operating[
            "threshold"
        ]

        epred = (
            eprob >= threshold
        ).astype(int)

        if ey.nunique() > 1:
            exc_metrics = {
                "validation_rows": int(
                    len(ev)
                ),
                "positive_rows": int(
                    ey.sum()
                ),
                "operating_threshold": float(
                    threshold
                ),
                "precision": float(
                    precision_score(
                        ey,
                        epred,
                        zero_division=0,
                    )
                ),
                "recall": float(
                    recall_score(
                        ey,
                        epred,
                        zero_division=0,
                    )
                ),
                "balanced_accuracy": float(
                    balanced_accuracy_score(
                        ey,
                        epred,
                    )
                ),
                "average_precision": float(
                    average_precision_score(
                        ey,
                        eprob,
                    )
                ),
                "roc_auc": float(
                    roc_auc_score(
                        ey,
                        eprob,
                    )
                ),
                "false_alert_events": operating[
                    "false_alert_events"
                ],
                "false_alerts_per_week": operating[
                    "false_alerts_per_week"
                ],
                "false_alert_constraint_per_week": (
                    MAX_FALSE_ALERTS_PER_WEEK
                ),
                "false_alert_constraint_met": bool(
                    operating[
                        "constraint_met"
                    ]
                ),
                "threshold_curve": threshold_curve,
            }
        else:
            exc_metrics = {
                "validation_rows": int(
                    len(ev)
                ),
                "positive_rows": int(
                    ey.sum()
                ),
                "operating_threshold": 0.50,
                "precision": None,
                "recall": None,
                "balanced_accuracy": None,
                "average_precision": None,
                "roc_auc": None,
                "false_alert_events": None,
                "false_alerts_per_week": None,
                "false_alert_constraint_per_week": (
                    MAX_FALSE_ALERTS_PER_WEEK
                ),
                "false_alert_constraint_met": False,
                "threshold_curve": [],
            }
    else:
        ev = pd.DataFrame()

        exc_metrics = {
            "validation_rows": 0,
            "positive_rows": 0,
            "operating_threshold": 0.50,
            "precision": None,
            "recall": None,
            "balanced_accuracy": None,
            "average_precision": None,
            "roc_auc": None,
            "false_alert_events": None,
            "false_alerts_per_week": None,
            "false_alert_constraint_per_week": (
                MAX_FALSE_ALERTS_PER_WEEK
            ),
            "false_alert_constraint_met": False,
            "threshold_curve": [],
        }

    # Production ambient model remains ordinary-condition and leakage-safe by design.
    ordinary = labeled[
        (
            labeled["system_h2s_max"]
            <= AMBIENT_TRAIN_MAX_PPB
        )
        & (
            labeled["rollmax60"].isna()
            | (
                labeled["rollmax60"]
                <= AMBIENT_TRAIN_MAX_PPB
            )
        )
    ].copy()

    if len(ordinary) < 200:
        ordinary = labeled.copy()

    ambient_model = _ambient_regressor()

    ambient_model.fit(
        ordinary[ENV_FEATURES],
        ordinary["system_h2s_max"],
    )

    labeled[
        "environmental_baseline_ppb"
    ] = np.maximum(
        0.0,
        ambient_model.predict(
            labeled[ENV_FEATURES]
        ),
    )

    labeled[
        "excess_wastewater_contribution_ppb"
    ] = (
        labeled["system_h2s_max"]
        - labeled[
            "environmental_baseline_ppb"
        ]
    ).clip(lower=0.0)

    # Production peak model mirrors v0.9-style architecture.
    peak_model = _peak_regressor()

    peak_model.fit(
        labeled[PEAK_FEATURES],
        labeled["future_60m_max_h2s"],
    )

    exc_model = None

    if (
        labeled["future_excursion"]
        .nunique(
            dropna=True
        )
        > 1
    ):
        exc_model = (
            _excursion_classifier()
        )

        exc_model.fit(
            labeled[
                EXCURSION_FEATURES
            ],
            labeled[
                "future_excursion"
            ].astype(int),
        )

    raw_imp = (
        peak_model
        .named_steps["model"]
        .feature_importances_[
            :len(PEAK_FEATURES)
        ]
    )

    feature_importance = sorted(
        [
            {
                "feature": n,
                "importance": float(v),
            }
            for n, v in zip(
                PEAK_FEATURES,
                raw_imp,
            )
        ],
        key=lambda r: r[
            "importance"
        ],
        reverse=True,
    )[:15]

    actual_high = (
        labeled["system_h2s_max"]
        > HIGH_THRESHOLD_PPB
    ).astype(int)

    actual_high_events = int(
        (
            actual_high.eq(1)
            & actual_high.shift(
                1,
                fill_value=0,
            ).eq(0)
        ).sum()
    )

    version = (
        datetime.now(
            timezone.utc
        ).strftime(
            "v%Y.%m.%d.%H%M"
        )
    )

    metrics = {
        "model_version": version,
        "model_type": "StabilizedTwoLayerRandomForest",
        "target": (
            "Next-60-minute maximum H2S plus "
            "separate excursion and wastewater residual layers"
        ),
        "trained_at_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "training_through_utc": str(
            labeled[
                "timestamp_utc"
            ].max()
        ),
        "training_rows": int(
            len(labeled)
        ),
        "walk_forward_folds_used": int(
            len(folds)
        ),
        "peak_forecast": peak_metrics,
        "peak_model_note": (
            "Peak model excludes environmental baseline and wastewater residual "
            "to preserve the stronger v0.9-style recent-H2S forecasting architecture."
        ),
        "excursion_definition": (
            f"Future peak rises at least {EXCURSION_ABS_RISE_PPB:.0f} ppb "
            f"and at least {EXCURSION_REL_RISE*100:.0f}% above current H2S."
        ),
        "excursion_model": exc_metrics,
        "actual_high_events": actual_high_events,
        "operational_high_threshold_ppb": (
            HIGH_THRESHOLD_PPB
        ),
        "environmental_baseline_definition": (
            f"Environment-only H2S expected from weather, tide, time and "
            f"source/wind alignment. Baseline is trained on ordinary conditions "
            f"<= {AMBIENT_TRAIN_MAX_PPB:.0f} ppb and used only for explanation."
        ),
        "excess_wastewater_definition": (
            "Observed H2S above the environment-only baseline. "
            "This inferred residual is explanatory and is not fed into the peak forecast."
        ),
        "ambient_training_rows": int(
            len(ordinary)
        ),
        "ambient_fold_training_rows": (
            ambient_fold_rows
        ),
        "feature_importance": (
            feature_importance
        ),
        "metrics_reliable": (
            len(folds) >= 3
            and len(pv) >= 1000
        ),
        "excursion_metrics_reliable": (
            exc_metrics.get(
                "positive_rows",
                0,
            ) >= 20
        ),
        "promotion_status": (
            "stabilized_two_layer_prototype"
        ),
    }

    MODEL_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    joblib.dump(
        {
            "version": version,
            "ambient_model": ambient_model,
            "peak_model": peak_model,
            "excursion_model": exc_model,
            "env_features": ENV_FEATURES,
            "peak_features": PEAK_FEATURES,
            "excursion_features": (
                EXCURSION_FEATURES
            ),
            "excursion_operating_threshold": (
                exc_metrics[
                    "operating_threshold"
                ]
            ),
        },
        MODEL_PATH,
    )

    save_metrics(
        metrics
    )

    return metrics


def _contribution_level(excess_ppb, current_ppb):
    if current_ppb <= 0:
        return "Low"

    ratio = (
        excess_ppb
        / max(
            current_ppb,
            1.0,
        )
    )

    if (
        excess_ppb >= 15
        or ratio >= 0.60
    ):
        return "High"

    if (
        excess_ppb >= 7
        or ratio >= 0.35
    ):
        return "Elevated"

    if (
        excess_ppb >= 3
        or ratio >= 0.20
    ):
        return "Moderate"

    return "Low"


def predict_latest():
    metrics = load_metrics()

    if (
        not MODEL_PATH.exists()
        or not metrics
    ):
        return {
            "model_available": False
        }

    raw = load_observations()

    if raw.empty:
        return {
            "model_available": False
        }

    artifact = joblib.load(
        MODEL_PATH
    )

    x = _base_features(
        raw
    )

    x[
        "environmental_baseline_ppb"
    ] = np.maximum(
        0.0,
        artifact[
            "ambient_model"
        ].predict(
            x[
                artifact[
                    "env_features"
                ]
            ]
        ),
    )

    x[
        "excess_wastewater_contribution_ppb"
    ] = (
        x["system_h2s_max"]
        - x[
            "environmental_baseline_ppb"
        ]
    ).clip(lower=0.0)

    row = x.tail(
        1
    ).copy()

    peak = max(
        0.0,
        float(
            artifact[
                "peak_model"
            ].predict(
                row[
                    artifact[
                        "peak_features"
                    ]
                ]
            )[0]
        ),
    )

    exc_prob = None

    if (
        artifact.get(
            "excursion_model"
        )
        is not None
    ):
        exc_prob = float(
            artifact[
                "excursion_model"
            ].predict_proba(
                row[
                    artifact[
                        "excursion_features"
                    ]
                ]
            )[:, 1][0]
        )

    threshold = float(
        artifact.get(
            "excursion_operating_threshold",
            0.50,
        )
    )

    current = float(
        row[
            "system_h2s_max"
        ].iloc[0]
    )

    env_baseline = float(
        row[
            "environmental_baseline_ppb"
        ].iloc[0]
    )

    excess = float(
        row[
            "excess_wastewater_contribution_ppb"
        ].iloc[0]
    )

    wastewater_level = (
        _contribution_level(
            excess,
            current,
        )
    )

    excursion_alert = (
        exc_prob is not None
        and exc_prob >= threshold
    )

    # Stabilized operational risk logic.
    # Near-threshold excursion probability alone no longer upgrades overall risk.
    if peak > HIGH_THRESHOLD_PPB:
        risk = "High"
    elif (
        peak >= ELEVATED_THRESHOLD_PPB
        or excursion_alert
        or wastewater_level == "High"
    ):
        risk = "Elevated"
    elif (
        peak >= WATCH_THRESHOLD_PPB
        or wastewater_level == "Elevated"
    ):
        risk = "Watch"
    else:
        risk = "Low"

    return {
        "model_available": True,
        "model_version": artifact[
            "version"
        ],
        "timestamp_utc": str(
            row[
                "timestamp_utc"
            ].iloc[0]
        ),
        "current_system_h2s_ppb": round(
            current,
            2,
        ),
        "predicted_next_60m_max_h2s_ppb": round(
            peak,
            2,
        ),
        "excursion_probability": (
            None
            if exc_prob is None
            else round(
                exc_prob,
                4,
            )
        ),
        "excursion_operating_threshold": round(
            threshold,
            4,
        ),
        "excursion_alert": bool(
            excursion_alert
        ),
        "environmental_baseline_ppb": round(
            env_baseline,
            2,
        ),
        "excess_wastewater_contribution_ppb": round(
            excess,
            2,
        ),
        "wastewater_contribution_level": (
            wastewater_level
        ),
        "risk_level": risk,
        "operational_high_threshold_ppb": (
            HIGH_THRESHOLD_PPB
        ),
        "excess_wastewater_note": (
            "Residual above ordinary-condition environment-only expected H2S; "
            "not a plant-failure diagnosis."
        ),
    }
