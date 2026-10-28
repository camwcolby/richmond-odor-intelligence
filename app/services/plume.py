"""
Indicative odor footprint around the treatment plant.

Shape: a ground-level Gaussian plume from the plant using Briggs rural
dispersion coefficients, with a Pasquill stability class picked from wind
speed and day/night. In calm air (< 1 m/s) odor pools around the plant
instead of travelling, so the footprint becomes a near-circle that drifts
slightly downwind.

Strength and color: taken from the risk nowcast. Elevated draws red, Normal
draws yellow, and the footprint grows with the risk percentile.

This is a visualization of where odor would travel under current conditions.
It is not a regulatory dispersion model and does not predict concentrations.
"""
from __future__ import annotations

from datetime import datetime
from math import cos, exp, log, radians, sin, sqrt
from zoneinfo import ZoneInfo

PLANT_LAT, PLANT_LON = 37.9204070, -122.3785459
TZ = ZoneInfo("America/Los_Angeles")
M_PER_DEG_LAT = 111_320.0
CALM_MPS = 1.0

# Briggs (1973) rural sigma_y, sigma_z as functions of downwind distance x (m)
_BRIGGS = {
    "B": (lambda x: 0.16 * x / sqrt(1 + 0.0001 * x), lambda x: 0.12 * x),
    "C": (lambda x: 0.11 * x / sqrt(1 + 0.0001 * x), lambda x: 0.08 * x / sqrt(1 + 0.0002 * x)),
    "D": (lambda x: 0.08 * x / sqrt(1 + 0.0001 * x), lambda x: 0.06 * x / sqrt(1 + 0.0015 * x)),
    "E": (lambda x: 0.06 * x / sqrt(1 + 0.0001 * x), lambda x: 0.03 * x / (1 + 0.0003 * x)),
    "F": (lambda x: 0.04 * x / sqrt(1 + 0.0001 * x), lambda x: 0.016 * x / (1 + 0.0003 * x)),
}
STABILITY_TEXT = {
    "B": "unstable (daytime mixing)", "C": "slightly unstable", "D": "neutral",
    "E": "slightly stable", "F": "stable (night, poor mixing)",
}

# Bands from outer to inner, as fractions of the centerline index 50 m downwind in
# neutral air at 3 m/s with full source strength.
BAND_LEVELS = [0.001, 0.004, 0.016]
BAND_OPACITY = [0.14, 0.22, 0.32]
COLORS = {"Elevated": "#C8102E", "Normal": "#E6B800"}
MAX_REACH_M = 6000.0


def stability_class(wind_mps: float, local_hour: int) -> str:
    night = local_hour >= 19 or local_hour < 7
    if night:
        return "F" if wind_mps < 2 else "E" if wind_mps < 3 else "D"
    return "B" if wind_mps < 2 else "C" if wind_mps < 5 else "D"


def _strength(risk_percentile: float) -> float:
    """Relative source strength from the nowcast percentile (0.01 to 1); steep so the
    footprint grows sharply as risk approaches the elevated range."""
    p = max(0.0, min(100.0, float(risk_percentile)))
    return max(0.01, ((p - 40.0) / 60.0) ** 4)


def _to_latlon(east_m: float, north_m: float):
    lat = PLANT_LAT + north_m / M_PER_DEG_LAT
    lon = PLANT_LON + east_m / (M_PER_DEG_LAT * cos(radians(PLANT_LAT)))
    return round(lat, 6), round(lon, 6)


def _plume_band(theta: float, u: float, stab: str, strength: float, level: float):
    """Polygon (list of [lon, lat]) where the relative index exceeds `level`."""
    sy0, sz = _BRIGGS[stab]
    # Wind direction wanders over a 15-minute window, more in light wind; widen the
    # crosswind spread so the footprint covers that meander, not a single instant.
    meander = radians(max(8.0, min(25.0, 30.0 / u)))
    sy = lambda x: sqrt(sy0(x) ** 2 + (x * sin(meander)) ** 2)
    syd, szd = _BRIGGS["D"]
    ref = 1.0 / (syd(50.0) * szd(50.0) * 3.0)            # fixed reference: neutral air, 3 m/s, 50 m
    dx, dy = sin(theta), cos(theta)                      # downwind unit vector (east, north)
    rx, ry = cos(theta), -sin(theta)                     # right of downwind
    left, right = [], []
    x = 15.0
    while x <= MAX_REACH_M:
        c = strength / (sy(x) * sz(x) * u) / ref
        if c <= level:
            break
        half = sy(x) * sqrt(2 * log(c / level))
        for side, sign in ((right, 1), (left, -1)):
            e = x * dx + sign * half * rx
            n = x * dy + sign * half * ry
            lat, lon = _to_latlon(e, n)
            side.append([lon, lat])
        x *= 1.12
    if not right:
        return None
    tip_lat, tip_lon = _to_latlon(x * dx, x * dy)
    back_lat, back_lon = _to_latlon(-25 * dx, -25 * dy)  # small upwind lip at the source
    ring = [[back_lon, back_lat]] + right + [[tip_lon, tip_lat]] + left[::-1] + [[back_lon, back_lat]]
    return ring


def _calm_band(theta: float | None, strength: float, level: float):
    """Odor pooling around the plant in near-calm air."""
    radius = 900.0 * sqrt(strength) * sqrt(BAND_LEVELS[0] / level)
    shift = 0.25 * radius
    cx, cy = (shift * sin(theta), shift * cos(theta)) if theta is not None else (0.0, 0.0)
    ring = []
    for k in range(49):
        a = radians(k * 7.5)
        lat, lon = _to_latlon(cx + radius * sin(a), cy + radius * cos(a))
        ring.append([lon, lat])
    return ring


def build_odor_plume(wind_from_deg, wind_mps, state: str, risk_percentile: float,
                     when: datetime | None = None) -> dict:
    when = (when or datetime.now(TZ)).astimezone(TZ)
    u = max(0.5, float(wind_mps)) if wind_mps is not None else None
    theta = radians((float(wind_from_deg) + 180.0) % 360.0) if wind_from_deg is not None else None
    strength = _strength(risk_percentile)
    color = COLORS.get(state, COLORS["Normal"])
    calm = u is None or theta is None or u < CALM_MPS
    stab = stability_class(u or 0.5, when.hour)

    features = []
    for level, opacity, band in zip(BAND_LEVELS, BAND_OPACITY, ("outer", "middle", "inner")):
        ring = _calm_band(theta, strength, level) if calm else _plume_band(theta, u, stab, strength, level)
        if ring is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"band": band, "color": color, "fill_opacity": opacity},
        })

    reach = 0.0
    if features:
        outer = features[0]["geometry"]["coordinates"][0]
        reach = max(
            sqrt(((lat - PLANT_LAT) * M_PER_DEG_LAT) ** 2
                 + ((lon - PLANT_LON) * M_PER_DEG_LAT * cos(radians(PLANT_LAT))) ** 2)
            for lon, lat in outer)

    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "state": state,
            "risk_percentile": round(float(risk_percentile), 1),
            "color": color,
            "mode": "calm pooling" if calm else "downwind plume",
            "wind_from_deg": None if wind_from_deg is None else round(float(wind_from_deg)),
            "wind_mps": None if wind_mps is None else round(float(wind_mps), 1),
            "stability_class": None if calm else stab,
            "stability_text": "calm air, odor pools near the plant" if calm else STABILITY_TEXT[stab],
            "reach_m": round(reach),
            "source": {"lat": PLANT_LAT, "lon": PLANT_LON},
            "note": ("Indicative odor footprint from the plant: Gaussian-plume shape (Briggs rural "
                     "coefficients) scaled by the risk nowcast. Not a regulatory dispersion model."),
        },
    }
