
from __future__ import annotations
import json, os, sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("ML_DATABASE_PATH", "data/ml_history.db"))
MODEL_PATH = Path(os.getenv("ML_MODEL_PATH", "data/odor_model.joblib"))
METRICS_PATH = Path(os.getenv("ML_METRICS_PATH", "data/odor_model_metrics.json"))

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_ml_db():
    with connect() as c:
        c.execute('''
        CREATE TABLE IF NOT EXISTS ml_observations (
            timestamp_utc TEXT PRIMARY KEY,
            north_h2s_ppb REAL, south_h2s_ppb REAL,
            wind_speed_mps REAL, wind_direction_deg REAL,
            temperature_f REAL, relative_humidity_pct REAL,
            precipitation_in REAL, rain_1h_in REAL, rain_24h_in REAL,
            tide_ft_mllw REAL, source_updated_at TEXT
        )''')
        c.commit()

def upsert_observations(rows):
    if not rows:
        return 0
    init_ml_db()
    vals = [(
        r.get("timestamp_utc"), r.get("north_h2s_ppb"), r.get("south_h2s_ppb"),
        r.get("wind_speed_mps"), r.get("wind_direction_deg"),
        r.get("temperature_f"), r.get("relative_humidity_pct"),
        r.get("precipitation_in"), r.get("rain_1h_in"), r.get("rain_24h_in"),
        r.get("tide_ft_mllw"), r.get("source_updated_at")
    ) for r in rows]
    with connect() as c:
        c.executemany('''
        INSERT INTO ml_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(timestamp_utc) DO UPDATE SET
          north_h2s_ppb=COALESCE(excluded.north_h2s_ppb,north_h2s_ppb),
          south_h2s_ppb=COALESCE(excluded.south_h2s_ppb,south_h2s_ppb),
          wind_speed_mps=COALESCE(excluded.wind_speed_mps,wind_speed_mps),
          wind_direction_deg=COALESCE(excluded.wind_direction_deg,wind_direction_deg),
          temperature_f=COALESCE(excluded.temperature_f,temperature_f),
          relative_humidity_pct=COALESCE(excluded.relative_humidity_pct,relative_humidity_pct),
          precipitation_in=COALESCE(excluded.precipitation_in,precipitation_in),
          rain_1h_in=COALESCE(excluded.rain_1h_in,rain_1h_in),
          rain_24h_in=COALESCE(excluded.rain_24h_in,rain_24h_in),
          tide_ft_mllw=COALESCE(excluded.tide_ft_mllw,tide_ft_mllw),
          source_updated_at=excluded.source_updated_at
        ''', vals)
        c.commit()
    return len(vals)

def load_observations():
    import pandas as pd
    init_ml_db()
    with connect() as c:
        df = pd.read_sql_query("SELECT * FROM ml_observations ORDER BY timestamp_utc", c)
    if not df.empty:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df

def save_metrics(m):
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(m, indent=2, default=str), encoding="utf-8")

def load_metrics():
    if not METRICS_PATH.exists():
        return None
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
