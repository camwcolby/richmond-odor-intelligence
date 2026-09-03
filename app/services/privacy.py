
import csv
from pathlib import Path
from math import radians, sin, cos, asin, sqrt

LANDMARKS = []
path = Path("data/landmarks.csv")
if path.exists():
    with path.open(newline="", encoding="utf-8") as f:
        LANDMARKS = list(csv.DictReader(f))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2-lat1)
    dlon = radians(lon2-lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def public_landmark(lat, lon):
    if not LANDMARKS:
        return "Richmond area"
    nearest = min(
        LANDMARKS,
        key=lambda r: haversine(lat, lon, float(r["latitude"]), float(r["longitude"]))
    )
    return nearest["landmark"]

def public_map_point(lat, lon):
    """Snap public map display to nearest landmark, never raw complaint coordinates."""
    if not LANDMARKS:
        return {"lat": round(lat, 2), "lon": round(lon, 2)}
    nearest = min(
        LANDMARKS,
        key=lambda r: haversine(lat, lon, float(r["latitude"]), float(r["longitude"]))
    )
    return {"lat": float(nearest["latitude"]), "lon": float(nearest["longitude"])}
