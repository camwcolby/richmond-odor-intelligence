
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
from app.services.h2s import get_h2s
from app.services.privacy import public_landmark, public_map_point
from app.ml.risk import risk_forecast

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
    out = []
    with open("data/sewer_hotspots.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["latitude"] = float(r["latitude"])
            r["longitude"] = float(r["longitude"])
            r["source_score"] = float(r["source_score"])
            out.append(r)
    return out

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

app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
def index():
    return FileResponse("app/static/index.html")
