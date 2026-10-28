
from fastapi import FastAPI, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from datetime import datetime, timezone, timedelta
import uuid
import csv

from app.db import init_db, seed_if_empty, list_complaints, insert_complaint, update_status
from app.services.weather import get_weather
from app.services.tides import get_tide_predictions
from app.services.h2s import get_h2s, get_h2s_history
from app.services.spatial import get_structures, get_hotspots as get_spatial_hotspots, source_receptor_features, build_risk_surface
from app.services.privacy import public_landmark, public_map_point
from app.ml.risk import risk_forecast

from app.ml.store import init_ml_db, load_metrics, load_observations
from app.ml.pipeline import predict_latest
from app.ml.backtest import backtest
from app.ml.history import ingest_range
from zoneinfo import ZoneInfo
from app.ml.automation import start_ml_automation

app = FastAPI(title="Richmond Odor Intelligence", version="0.1.0")

class ComplaintIn(BaseModel):
    latitude: float = Field(ge=37.7, le=38.2)
    longitude: float = Field(ge=-122.7, le=-122.0)
    odor_type: str = Field(min_length=2, max_length=50)
    intensity: int = Field(ge=1, le=5)
    comments: str = Field(default="", max_length=500)

class StatusIn(BaseModel):
    status: str

@app.on_event("startup")
def startup():
    init_db()
    init_ml_db()
    start_ml_automation()
    rows = []
    with open("data/mock_complaints.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((
                r["complaint_id"], r["reported_at"], float(r["latitude"]), float(r["longitude"]),
                r["public_location"], r["odor_type"], int(r["intensity"]), r["comments"],
                r["status"], r["cmms_work_order"]
            ))
    seed_if_empty(rows)

@app.get("/api/health")
def health():
    return {"ok": True, "service": "richmond-odor-intelligence"}

@app.get("/api/h2s")
async def h2s():
    return await get_h2s()

@app.get("/api/h2s/history")
async def h2s_history(hours: int = 24):
    return await get_h2s_history(hours=hours)

@app.get("/api/weather")
async def weather():
    try:
        return await get_weather()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Weather provider unavailable: {e}")

@app.get("/api/tides")
async def tides():
    try:
        return await get_tide_predictions()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Tide provider unavailable: {e}")

@app.get("/api/complaints")
def complaints():
    rows = list_complaints()
    for r in rows:
        p = public_map_point(r["latitude"], r["longitude"])
        r["map_latitude"] = p["lat"]
        r["map_longitude"] = p["lon"]
        r.pop("latitude", None)
        r.pop("longitude", None)
        r["comments"] = ""  # don't expose free text publicly in prototype
    return rows

@app.post("/api/complaints")
def create_complaint(c: ComplaintIn):
    cid = "OD-" + uuid.uuid4().hex[:8].upper()
    wo = "SIM-" + uuid.uuid4().hex[:6].upper()
    loc = public_landmark(c.latitude, c.longitude)
    row = (
        cid, datetime.now(timezone.utc).isoformat(), c.latitude, c.longitude, loc,
        c.odor_type, c.intensity, c.comments, "Received", wo
    )
    insert_complaint(row)
    p = public_map_point(c.latitude, c.longitude)
    return {
        "complaint_id": cid,
        "public_location": loc,
        "status": "Received",
        "cmms_work_order": wo,
        "map_latitude": p["lat"],
        "map_longitude": p["lon"]
    }

@app.patch("/api/complaints/{complaint_id}/status")
def change_status(complaint_id: str, body: StatusIn):
    allowed = {"Received","Reviewing","Investigating","Resolved"}
    if body.status not in allowed:
        raise HTTPException(400, "Invalid status")
    update_status(complaint_id, body.status)
    return {"complaint_id": complaint_id, "status": body.status}

@app.get("/api/hotspots")
def hotspots():
    return get_spatial_hotspots()

def _nowcast_risk_payload(n):
    """Shape the nowcast for the existing risk card: one state, Elevated or Normal."""
    pct = n["risk_percentile"]
    if n["elevated"]:
        narrative = (
            f"Odor risk is {pct:.0f}%, at or above the 90% elevated level: conditions favor "
            "odor reaching the fence line in the next 3 hours."
        )
    else:
        narrative = (
            f"Conditions are normal. Odor risk is {pct:.0f}%; "
            "the dashboard switches to elevated at 90%."
        )
    stale_note = None
    if n.get("stale"):
        hours = n["data_age_minutes"] / 60
        stale_note = (f"Sensor data is {hours:.1f} hours old; this state reflects the last "
                      "readings received, not current conditions.")
        narrative += " " + stale_note
    return {
        "current_level": "High" if n["elevated"] else "Low",
        "display_level": "Elevated risk" if n["elevated"] else "Normal",
        "current_probability": round(pct / 100, 3),
        "pct_label": f"{pct:.0f}% risk",
        "narrative": narrative,
        "elevated_since_utc": n["elevated_since_utc"],
        "drivers": [{"feature": d["name"], "importance": d["share"]} for d in n["drivers"]],
        "hourly": [],
        "recent_hours": n["recent_hours"],
        "method": n["model_version"],
        "model_status": "Trained nowcast, validated on two years of fence-line data",
        "stale": n.get("stale", False),
        "stale_note": stale_note,
    }


@app.get("/api/spatial/odor-plume")
async def odor_plume():
    """Indicative odor footprint from the plant, shaped by wind and colored by the nowcast."""
    from app.ml.nowcast import predict_nowcast
    from app.ml.store import load_observations
    from app.services.plume import build_odor_plume
    import pandas as pd

    try:
        n = predict_nowcast()
    except Exception as exc:
        print("[plume] nowcast unavailable:", repr(exc))
        n = {"available": False}
    if not n.get("available"):
        return {"type": "FeatureCollection", "features": [],
                "properties": {"available": False, "reason": n.get("reason", "nowcast unavailable")}}

    # Wind the model saw: newest observation with wind data, within 2 hours of the nowcast time.
    when = pd.Timestamp(n["timestamp_utc"])
    wind_from = wind_mps = None
    obs = load_observations()
    if not obs.empty:
        w = obs.dropna(subset=["wind_speed_mps", "wind_direction_deg"])
        w = w[(w.timestamp_utc <= when) & (w.timestamp_utc >= when - pd.Timedelta("2h"))]
        if not w.empty:
            wind_mps = float(w.wind_speed_mps.iloc[-1])
            wind_from = float(w.wind_direction_deg.iloc[-1])
    if wind_mps is None:
        try:
            cur = (await get_weather()).get("current", {})
            wind_from = cur.get("wind_direction_10m")
            if cur.get("wind_speed_10m") is not None:
                wind_mps = float(cur["wind_speed_10m"]) * 0.44704
        except Exception:
            pass

    out = build_odor_plume(wind_from, wind_mps, n["state"], n["risk_percentile"],
                           when=when.to_pydatetime())
    out["properties"].update({"available": True, "timestamp_utc": n["timestamp_utc"],
                              "stale": n.get("stale", False)})
    return out


@app.get("/api/ml/nowcast")
def ml_nowcast():
    from app.ml.nowcast import predict_nowcast
    return predict_nowcast()


@app.get("/api/ml/nowcast/performance")
def ml_nowcast_performance():
    """Validation summary + served-model info + current state, for the Model Performance tab."""
    import json
    from pathlib import Path
    from app.ml.nowcast import load_artifact, predict_nowcast
    path = Path("data/nowcast_validation.json")
    validation = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    art = load_artifact()
    model = None if art is None else {
        "version": art.get("version"),
        "trained_at_utc": art.get("trained_at_utc"),
        "training_start_utc": art.get("training_start_utc"),
        "training_through_utc": art.get("training_through_utc"),
        "training_rows": art.get("training_rows"),
    }
    try:
        current = predict_nowcast()
    except Exception as exc:
        current = {"available": False, "reason": f"{type(exc).__name__}"}
    return {"validation": validation, "model": model, "current": current}


@app.get("/api/risk")
async def risk():
    from app.ml.nowcast import predict_nowcast
    try:
        n = predict_nowcast()
    except Exception as exc:
        print("[nowcast] unavailable:", repr(exc))
        n = {"available": False}
    if n.get("available"):
        return _nowcast_risk_payload(n)

    h2s_data = await get_h2s()
    tide_value = None
    try:
        w = await get_weather()
        current = w["current"]
    except Exception:
        current = {
            "temperature_2m": 66,
            "relative_humidity_2m": 68,
            "precipitation": 0,
            "wind_speed_10m": 5,
            "wind_direction_10m": 235
        }
    try:
        t = await get_tide_predictions()
        preds = t.get("predictions", [])
        if preds:
            tide_value = float(preds[0]["v"])
    except Exception:
        pass
    return risk_forecast(current, h2s_data["sensors"], tide_value)


@app.get("/api/sonoma/config")
def sonoma_config():
    import os
    raw_verify = os.getenv("SONOMA_SSL_VERIFY", "true")
    token = os.getenv("SONOMA_DMS_TOKEN", "")
    normalized = raw_verify.strip().lower().strip('"').strip("'")
    return {
        "token_configured": bool(token),
        "token_length": len(token),
        "ssl_verify_raw": raw_verify,
        "ssl_verify_disabled": normalized in {"false", "0", "no", "off"},
    }

@app.get("/api/structures")
def structures():
    return get_structures()

@app.get("/api/spatial/context")
async def spatial_context():
    h2s_data = await get_h2s()
    receptors = [
        {"id": s.get("id"), "name": s.get("name"), "lat": s.get("lat"), "lon": s.get("lon")}
        for s in h2s_data.get("sensors", [])
    ]

    wind_direction = None
    wind = h2s_data.get("wind") or {}
    if wind.get("direction_deg") is not None:
        wind_direction = wind.get("direction_deg")
    else:
        try:
            weather_data = await get_weather()
            wind_direction = weather_data.get("current", {}).get("wind_direction_10m")
        except Exception:
            wind_direction = None

    return source_receptor_features(receptors, wind_direction_deg=wind_direction)

@app.get("/api/spatial/risk-surface")
async def spatial_risk_surface():
    h2s_data = await get_h2s()

    wind = h2s_data.get("wind") or {}
    wind_direction = wind.get("direction_deg")
    wind_speed_mps = wind.get("speed_mps")

    if wind_direction is None:
        try:
            weather_data = await get_weather()
            current = weather_data.get("current", {})
            wind_direction = current.get("wind_direction_10m")

            if wind_speed_mps is None and current.get("wind_speed_10m") is not None:
                wind_speed_mps = float(current.get("wind_speed_10m")) * 0.44704
        except Exception:
            pass

    return build_risk_surface(
        sensors=h2s_data.get("sensors", []),
        wind_direction_deg=wind_direction,
        wind_speed_mps=wind_speed_mps,
    )

@app.get("/api/ml/status")
def ml_status():
    import os
    df=load_observations()
    return {"observation_rows":len(df),"metrics":load_metrics(),"latest_prediction":predict_latest(),
            "ingest_minutes":int(os.getenv("ML_INGEST_MINUTES","15")),
            "retrain_hours":int(os.getenv("ML_RETRAIN_HOURS","24"))}

@app.get("/api/ml/prediction")
def ml_prediction():
    return predict_latest()


@app.get("/api/ml/backtest")
async def ml_backtest(start_date: str = "2026-10-19", end_date: str = "2026-10-25"):
    try:
        start_local = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=ZoneInfo("America/Los_Angeles"))
        end_local = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=ZoneInfo("America/Los_Angeles"))
        if end_local < start_local or (end_local - start_local).days > 30:
            raise ValueError("Date range must be between 1 and 31 days.")
        start_utc = (start_local - timedelta(days=2)).astimezone(timezone.utc)
        end_utc = (end_local + timedelta(days=2)).astimezone(timezone.utc)
        existing = load_observations()
        if existing.empty or existing.loc[
            (existing.timestamp_utc >= start_utc) & (existing.timestamp_utc < end_utc)
        ].empty:
            recovery = await ingest_range(start_utc, end_utc)
        else:
            recovery = None
        result = backtest(start_date=start_date, end_date=end_date)
        if recovery is not None:
            result["on_demand_history_recovery"] = recovery
        return result
    except (ValueError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Historical data recovery or replay failed: {type(exc).__name__}: {exc}")



@app.get("/api/ml/observations/export")
def ml_observations_export(
    start_date: str = "2026-10-17",
    end_date: str = "2026-10-27",
    x_export_token: str | None = Header(default=None),
):
    """Token-protected, read-only transfer of observations, never credentials."""
    import os
    import secrets
    from fastapi.responses import JSONResponse
    secret = os.environ.get("ML_EXPORT_TOKEN", "")
    if not secret:
        raise HTTPException(status_code=503, detail="ML_EXPORT_TOKEN not configured")
    if not x_export_token or not secrets.compare_digest(x_export_token, secret):
        raise HTTPException(status_code=401, detail="Invalid export token")
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must use YYYY-MM-DD")
    if end <= start or (end - start).days > 35:
        raise HTTPException(status_code=400, detail="Date window must be 1-35 days")
    df = load_observations()
    if not df.empty:
        df = df.loc[(df.timestamp_utc >= start) & (df.timestamp_utc < end)].copy()
        df["timestamp_utc"] = df["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        df = df.astype(object).where(df.notna(), None)
    records = df.to_dict(orient="records")
    return JSONResponse(
        content={"rows": records, "row_count": len(records),
                 "start_date": start_date, "end_date": end_date},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )

@app.get("/api/live-cache/status")
def live_cache_status():
    from pathlib import Path
    import json, time
    cache_dir = Path("data/live_cache")
    files = sorted(cache_dir.glob("sonoma_raw_*.json"), key=lambda p:p.stat().st_mtime, reverse=True) if cache_dir.exists() else []
    if not files:
        h={"available":False,"age_seconds":None}
    else:
        p=files[0]
        try:
            payload=json.loads(p.read_text(encoding="utf-8"))
            saved=float(payload.get("saved_at",p.stat().st_mtime))
        except Exception:
            saved=p.stat().st_mtime
        h={"available":True,"age_seconds":round(max(0.0,time.time()-saved),1)}
    return {"h2s":h,"cache_ttl_seconds":120,"stale_fallback_seconds":21600}


@app.get("/api/h2s/diagnostics")
async def h2s_diagnostics():
    from app.services.h2s_diagnostics import build_h2s_diagnostics
    return await build_h2s_diagnostics()


app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
def index():
    return FileResponse("app/static/index.html")
