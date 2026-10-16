
"""
Transparent prototype odor-risk engine.

This is deliberately a deterministic engineering score, not a falsely
presented trained ML model. The interface is ML-ready: replace risk_forecast()
with a serialized classifier/regressor once labeled historical data exist.
"""
from math import cos, radians, exp
from datetime import datetime, timezone, timedelta
import math

def _alignment(wind_from_deg, source_bearing_deg):
    # Wind travels toward wind_from + 180.
    toward = (wind_from_deg + 180) % 360
    delta = abs((toward - source_bearing_deg + 180) % 360 - 180)
    return max(0.0, cos(radians(delta)))

def risk_forecast(weather_current, sensors, tide_value=None):
    # Only fresh, finite, nonnegative measurements can force a risk floor.
    now = datetime.now(timezone.utc)
    valid_readings = []
    for sensor in sensors:
        try:
            value = float(sensor.get("h2s_ppb"))
            stamp = str(sensor.get("timestamp_utc") or "").replace("Z", "+00:00")
            observed = datetime.fromisoformat(stamp)
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            age = now - observed.astimezone(timezone.utc)
            if math.isfinite(value) and value >= 0 and timedelta(0) <= age <= timedelta(minutes=30):
                valid_readings.append(value)
        except (TypeError, ValueError, OverflowError):
            continue
    h2s = max(valid_readings, default=0.0)
    observed_floor = 0.67 if h2s >= 60 else 0.38 if h2s >= 30 else 0.0
    wind = float(weather_current.get("wind_speed_10m") or 0)
    wind_dir = float(weather_current.get("wind_direction_10m") or 0)
    temp = float(weather_current.get("temperature_2m") or 60)
    rain = float(weather_current.get("precipitation") or 0)

    # Engineering-inspired demo features.
    h2s_score = min(1, h2s / 60)
    low_wind = exp(-wind / 7)
    warm = min(1, max(0, (temp - 50) / 40))
    rain_effect = min(1, rain / 0.25)
    tide_effect = 0.5 if tide_value is None else min(1, max(0, (4 - tide_value) / 5))

    base = (
        0.44*h2s_score +
        0.22*low_wind +
        0.10*warm +
        0.08*rain_effect +
        0.08*tide_effect +
        0.08*_alignment(wind_dir, 60)
    )
    p = max(observed_floor, max(0.03, min(0.94, base)))

    hourly = []
    now_h = datetime.now().hour
    for k in range(7):
        wave = 0.06 * cos(k/2)
        prob = max(0.02, min(0.96, p + wave - 0.015*k))
        if k == 0:
            prob = max(prob, observed_floor)
        if prob >= .67:
            level = "High"
        elif prob >= .38:
            level = "Moderate"
        else:
            level = "Low"
        hourly.append({"hour_offset": k, "probability": round(prob, 3), "level": level})

    drivers = [
        {"feature":"Live H₂S", "importance": round(h2s_score,2)},
        {"feature":"Low wind / dispersion", "importance": round(low_wind,2)},
        {"feature":"Temperature", "importance": round(warm,2)},
        {"feature":"Tide proxy", "importance": round(tide_effect,2)},
        {"feature":"Recent rainfall", "importance": round(rain_effect,2)},
    ]
    drivers.sort(key=lambda x: x["importance"], reverse=True)
    return {
        "current_probability": round(p,3),
        "observed_h2s_max_ppb": max(valid_readings) if valid_readings else None,
        "observed_risk_floor": "High" if observed_floor >= .67 else "Moderate" if observed_floor >= .38 else None,
        "observed_reading_max_age_minutes": 30,
        "current_level": "High" if p>=.67 else "Moderate" if p>=.38 else "Low",
        "hourly": hourly,
        "drivers": drivers[:4],
        "method": "prototype_engineering_score",
        "model_status": "Simulated / ML-ready"
    }
