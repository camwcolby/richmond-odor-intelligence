
from fastapi import FastAPI, HTTPException
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

@app.get("/api/risk")
async def risk():
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
