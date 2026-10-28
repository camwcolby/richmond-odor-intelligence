import numpy as np
import pandas as pd

from app.ml import nowcast as nc


def _synthetic(days=14, seed=0):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-01-01", periods=days * 96, freq="15min", tz="UTC")
    ws = np.clip(2 + np.sin(np.arange(len(t)) / 40) * 2 + rng.normal(0, 0.3, len(t)), 0, None)
    base = 5 + 10 * (ws < 1) + rng.gamma(1.5, 2, len(t))
    spikes = np.zeros(len(t))
    spikes[rng.choice(len(t), 40, replace=False)] = rng.uniform(20, 60, 40)
    return pd.DataFrame({
        "timestamp_utc": t.astype(str),
        "north_h2s_ppb": base + spikes, "south_h2s_ppb": base * 0.8,
        "wind_speed_mps": ws, "wind_direction_deg": rng.uniform(0, 360, len(t)),
        "temperature_f": 60 + 8 * np.sin(np.arange(len(t)) / 15), "relative_humidity_pct": 75.0,
        "rain_24h_in": 0.0, "tide_ft_mllw": 3 + 2 * np.sin(np.arange(len(t)) / 25),
    })


def test_train_and_predict(tmp_path, monkeypatch):
    monkeypatch.setattr(nc, "NOWCAST_PATH", tmp_path / "nowcast.joblib")
    obs = _synthetic()
    info = nc.train_nowcast(obs)
    assert info["training_rows"] == len(obs)
    p = nc.predict_nowcast(obs)
    assert p["available"] is True
    assert p["state"] in {"Elevated", "Normal"}
    assert 0 <= p["risk_percentile"] <= 100
    assert abs(sum(d["share"] for d in p["drivers"]) - 1) < 0.01 or all(d["share"] == 0 for d in p["drivers"])
    assert len(p["recent_hours"]) <= 6


def test_missing_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(nc, "NOWCAST_PATH", tmp_path / "missing.joblib")
    assert nc.predict_nowcast(_synthetic())["available"] is False


def test_elevated_state_hysteresis():
    s = pd.Series([0.5, 0.95, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5])
    st = nc._elevated_state(s)
    assert not st.iloc[0] and st.iloc[1]
    assert st.iloc[8]          # still on: fewer than 8 steps below
    assert not st.iloc[9]      # cleared after 8 steps below


def test_scores_after_a_few_hours(tmp_path, monkeypatch):
    monkeypatch.setattr(nc, "NOWCAST_PATH", tmp_path / "nowcast.joblib")
    nc.train_nowcast(_synthetic())
    short = _synthetic(days=14).tail(8 * 4)          # 8 hours only
    p = nc.predict_nowcast(short)
    assert p["available"] is True and p["warming_up"] is True


def test_live_validation_runs(tmp_path, monkeypatch):
    from app.ml import nowcast_eval as ev
    monkeypatch.setattr(nc, "NOWCAST_PATH", tmp_path / "nowcast.joblib")
    monkeypatch.setattr(ev, "VALIDATION_PATH", tmp_path / "validation.json")
    obs = _synthetic(days=200)
    result = ev.retrain_and_validate(obs)
    assert result["validation_available"] is True
    v = ev.load_validation()
    assert v["episodes"] == sum(b["count"] for b in v["warning_bins"])
    assert v["months"] >= 6 and v["computed_at_utc"]
