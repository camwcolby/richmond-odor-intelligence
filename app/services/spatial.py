
from __future__ import annotations

import csv
import json
from math import radians, degrees, sin, cos, asin, sqrt, atan2, exp
from pathlib import Path

STRUCTURES_PATH = Path("data/00_Sanitary_Structure.geojson")
HOTSPOTS_PATH = Path("data/sewer_hotspots.csv")


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = radians(lat1), radians(lat2)
    dl = radians(lon2 - lon1)
    y = sin(dl) * cos(p2)
    x = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl)
    return (degrees(atan2(y, x)) + 360) % 360


def _wind_alignment(wind_from_deg, source_to_receptor_bearing):
    if wind_from_deg is None:
        return None
    wind_toward = (float(wind_from_deg) + 180.0) % 360.0
    delta = abs((wind_toward - source_to_receptor_bearing + 180) % 360 - 180)
    return max(0.0, cos(radians(delta)))


def _source_prior(source_type: str, data_status: str | None = None) -> float:
    t = (source_type or "").lower()
    status = (data_status or "").lower()

    if "wwtp" in t or "treatment plant" in t:
        return 0.85
    if "historical sso" in t:
        return 0.72 if "placeholder" not in status else 0.45
    if "pump station" in t:
        return 0.48
    if "overflow" in t or "weir" in t:
        return 0.32
    return 0.18


def get_structures():
    if not STRUCTURES_PATH.exists():
        return {"type": "FeatureCollection", "features": []}

    raw = json.loads(STRUCTURES_PATH.read_text(encoding="utf-8"))
    features = []

    for f in raw.get("features", []):
        props = dict(f.get("properties") or {})
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]

        if len(coords) < 2:
            continue

        name = str(props.get("StructureN") or "Sanitary Structure").strip()
        sewer_struct = props.get("SewerStruc")
        asset_type_code = props.get("ASSET_TYPE")
        lname = name.lower()

        if sewer_struct == 2 or asset_type_code == 2 or "treatment plant" in lname:
            category = "WWTP"
        elif sewer_struct == 4 or asset_type_code == 4 or "pump station" in lname:
            category = "Pump Station"
        elif sewer_struct == 5 or asset_type_code == 5 or "weir" in lname:
            category = "Overflow / Weir"
        else:
            category = "Sanitary Structure"

        clean_props = {
            "asset_id": props.get("ASSET_ID") or props.get("node_id"),
            "facility_no": props.get("FacilityNo"),
            "name": name,
            "category": category,
            "status": props.get("ASSET_STATUS") or props.get("SewerStatu"),
            "system_type": props.get("SYSTEM_TYPE"),
            "source": "City of Richmond sanitary structure GeoJSON",
            "source_prior": _source_prior(category),
        }

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(coords[0]), float(coords[1])],
            },
            "properties": clean_props,
        })

    return {"type": "FeatureCollection", "features": features}


def get_hotspots():
    if not HOTSPOTS_PATH.exists():
        return []

    rows = []

    with HOTSPOTS_PATH.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["latitude"] = float(r["latitude"])
                r["longitude"] = float(r["longitude"])
                r["source_score"] = float(r.get("source_score") or 0)
            except (TypeError, ValueError):
                continue

            is_placeholder = "illustrative" in str(r.get("notes", "")).lower()

            r["semantic_type"] = "Historical SSO Location"
            r["data_status"] = (
                "SSO placeholder / replace with verified historical export"
                if is_placeholder
                else "Historical SSO"
            )
            r["source_prior"] = _source_prior("Historical SSO", r["data_status"])
            rows.append(r)

    return rows


def _sources():
    sources = []

    for f in get_structures()["features"]:
        lon, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        sources.append({
            "source_id": p.get("asset_id"),
            "source_name": p.get("name"),
            "source_type": p.get("category"),
            "latitude": lat,
            "longitude": lon,
            "source_score": p.get("source_prior"),
            "data_status": "Provided GIS asset",
        })

    for h in get_hotspots():
        sources.append({
            "source_id": h.get("hotspot_id"),
            "source_name": h.get("name"),
            "source_type": "Historical SSO",
            "latitude": h["latitude"],
            "longitude": h["longitude"],
            "source_score": h.get("source_prior"),
            "data_status": h.get("data_status"),
        })

    return sources


def source_receptor_features(receptors, wind_direction_deg=None):
    sources = _sources()
    relationships = []

    for receptor in receptors:
        rlat, rlon = receptor.get("lat"), receptor.get("lon")
        if rlat is None or rlon is None:
            continue

        for s in sources:
            bearing = _bearing_deg(
                s["latitude"],
                s["longitude"],
                rlat,
                rlon,
            )

            alignment = _wind_alignment(
                wind_direction_deg,
                bearing,
            )

            relationships.append({
                "receptor_id": receptor.get("id"),
                "receptor_name": receptor.get("name"),
                "source_id": s["source_id"],
                "source_name": s["source_name"],
                "source_type": s["source_type"],
                "source_data_status": s["data_status"],
                "distance_km": round(
                    _haversine_km(
                        s["latitude"],
                        s["longitude"],
                        rlat,
                        rlon,
                    ),
                    4,
                ),
                "source_to_receptor_bearing_deg": round(bearing, 1),
                "wind_direction_from_deg": wind_direction_deg,
                "downwind_alignment": (
                    None if alignment is None else round(alignment, 4)
                ),
                "source_score": s["source_score"],
            })

    relationships.sort(
        key=lambda x: (-(x["downwind_alignment"] or 0), x["distance_km"])
    )

    return {
        "wind_direction_from_deg": wind_direction_deg,
        "source_count": len(sources),
        "receptor_count": len(receptors),
        "relationships": relationships,
    }


def build_risk_surface(
    sensors,
    wind_direction_deg=None,
    wind_speed_mps=None,
):
    sources = _sources()

    valid_h2s = [
        float(s.get("h2s_ppb"))
        for s in sensors
        if s.get("h2s_ppb") is not None
    ]

    max_h2s = max(valid_h2s) if valid_h2s else 0.0
    h2s_factor = min(1.0, max_h2s / 60.0)
    emission_factor = 0.12 + 0.88 * h2s_factor

    if wind_speed_mps is None:
        persistence = 0.55
    else:
        persistence = exp(-max(0.0, float(wind_speed_mps)) / 4.5)

    lat_min, lat_max = 37.908, 37.963
    lon_min, lon_max = -122.397, -122.329
    step = 0.0035

    cells = []
    lat = lat_min

    while lat <= lat_max:
        lon = lon_min

        while lon <= lon_max:
            total = 0.0
            dominant = None
            dominant_contribution = 0.0

            for s in sources:
                distance = max(
                    _haversine_km(
                        s["latitude"],
                        s["longitude"],
                        lat,
                        lon,
                    ),
                    0.08,
                )

                bearing = _bearing_deg(
                    s["latitude"],
                    s["longitude"],
                    lat,
                    lon,
                )

                alignment = _wind_alignment(
                    wind_direction_deg,
                    bearing,
                )

                alignment_term = 0.35 if alignment is None else alignment ** 1.8
                distance_decay = exp(-distance / 1.35)

                contribution = (
                    float(s["source_score"] or 0.0)
                    * alignment_term
                    * distance_decay
                )

                total += contribution

                if contribution > dominant_contribution:
                    dominant_contribution = contribution
                    dominant = s

            geometry_score = 1.0 - exp(-1.5 * total)
            score = geometry_score * emission_factor
            score *= 0.82 + 0.18 * persistence
            score = max(0.0, min(1.0, score))

            if score >= 0.67:
                level = "High"
            elif score >= 0.38:
                level = "Moderate"
            else:
                level = "Low"

            if score >= 0.055:
                cells.append({
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "score": round(score, 4),
                    "level": level,
                    "dominant_source": dominant.get("source_name") if dominant else None,
                    "dominant_source_type": dominant.get("source_type") if dominant else None,
                })

            lon += step

        lat += step

    return {
        "method": "prototype_engineering_spatial_surface",
        "calibrated_probability": False,
        "live_h2s_max_ppb": round(max_h2s, 3),
        "wind_direction_from_deg": wind_direction_deg,
        "wind_speed_mps": wind_speed_mps,
        "cell_radius_m": 285,
        "cells": cells,
        "notes": (
            "Visualization combines live H2S with engineering source priors, "
            "downwind alignment and distance decay. It is not a trained ML or "
            "regulatory dispersion model."
        ),
    }
