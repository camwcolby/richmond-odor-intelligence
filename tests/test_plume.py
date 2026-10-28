from datetime import datetime
from math import atan2, degrees, cos, radians
from zoneinfo import ZoneInfo

from app.services.plume import PLANT_LAT, PLANT_LON, build_odor_plume

TZ = ZoneInfo("America/Los_Angeles")


def _bearing_to(lon, lat):
    dx = (lon - PLANT_LON) * cos(radians(PLANT_LAT))
    dy = lat - PLANT_LAT
    return degrees(atan2(dx, dy)) % 360


def test_plume_points_downwind():
    p = build_odor_plume(270, 3.0, "Elevated", 95, datetime(2026, 10, 23, 2, tzinfo=TZ))
    assert p["properties"]["mode"] == "downwind plume"
    ring = p["features"][0]["geometry"]["coordinates"][0]
    far = max(ring, key=lambda c: abs(c[0] - PLANT_LON) + abs(c[1] - PLANT_LAT))
    assert abs(_bearing_to(*far) - 90) < 20        # wind from the west carries odor east


def test_color_and_reach_follow_risk_and_stability():
    night = datetime(2026, 10, 23, 2, tzinfo=TZ)
    day = datetime(2026, 10, 23, 14, tzinfo=TZ)
    hi = build_odor_plume(250, 1.5, "Elevated", 97, night)["properties"]
    lo = build_odor_plume(250, 5.0, "Normal", 60, day)["properties"]
    assert hi["color"] != lo["color"]
    assert hi["reach_m"] > 3 * lo["reach_m"]


def test_calm_air_pools():
    p = build_odor_plume(None, 0.4, "Elevated", 96)
    assert p["properties"]["mode"] == "calm pooling"
    assert len(p["features"]) == 3
