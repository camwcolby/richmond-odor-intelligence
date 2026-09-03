
from app.ml.risk import risk_forecast

def test_risk_range():
    w={"wind_speed_10m":4,"wind_direction_10m":230,"temperature_2m":70,"precipitation":0}
    sensors=[{"h2s_ppb":25},{"h2s_ppb":35}]
    r=risk_forecast(w,sensors,2.5)
    assert 0 <= r["current_probability"] <= 1
    assert r["current_level"] in {"Low","Moderate","High"}
    assert len(r["hourly"]) == 7
