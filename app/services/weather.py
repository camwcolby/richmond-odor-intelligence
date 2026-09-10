
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

LAT = float(os.getenv("RICHMOND_LAT", "37.9358"))
LON = float(os.getenv("RICHMOND_LON", "-122.3477"))

URL = os.getenv(
    "OPEN_METEO_URL",
    "https://api.open-meteo.com/v1/forecast",
)


def _ssl_verify_setting() -> bool | str:
    ca_bundle = os.getenv("OPEN_METEO_CA_BUNDLE", "").strip()

    if ca_bundle:
        path = Path(ca_bundle)
        if not path.exists():
            raise RuntimeError(f"OPEN_METEO_CA_BUNDLE does not exist: {ca_bundle}")
        return str(path)

    raw = os.getenv(
        "OPEN_METEO_SSL_VERIFY",
        os.getenv("SONOMA_SSL_VERIFY", "true"),
    ).strip().lower()

    return False if raw in {"false", "0", "no", "off"} else True


def _sum_precip(times, values, start, end) -> float:
    total = 0.0
    for t, v in zip(times, values):
        if v is None:
            continue
        try:
            dt = datetime.fromisoformat(t)
            val = float(v)
        except (TypeError, ValueError):
            continue
        if start <= dt <= end:
            total += val
    return total


def _cardinal(deg):
    if deg is None:
        return None

    directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW",
    ]
    return directions[int((float(deg) + 11.25) // 22.5) % 16]


async def get_weather() -> dict[str, Any]:
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "rain",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
            "surface_pressure",
            "cloud_cover",
        ]),
        "hourly": ",".join([
            "precipitation",
            "rain",
            "temperature_2m",
            "relative_humidity_2m",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
        ]),
        "past_days": 1,
        "forecast_days": 2,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "America/Los_Angeles",
    }

    async with httpx.AsyncClient(
        timeout=20.0,
        verify=_ssl_verify_setting(),
        follow_redirects=True,
    ) as client:
        response = await client.get(URL, params=params)

    response.raise_for_status()

    raw = response.json()
    current = raw.get("current") or {}
    hourly = raw.get("hourly") or {}

    try:
        current_time = datetime.fromisoformat(current.get("time"))
    except (TypeError, ValueError):
        current_time = datetime.now()

    hourly_times = hourly.get("time") or []
    hourly_precip = hourly.get("precipitation") or []

    rain_1h = _sum_precip(
        hourly_times,
        hourly_precip,
        current_time - timedelta(hours=1),
        current_time,
    )

    rain_24h = _sum_precip(
        hourly_times,
        hourly_precip,
        current_time - timedelta(hours=24),
        current_time,
    )

    wind_dir = current.get("wind_direction_10m")

    return {
        "source": "Open-Meteo",
        "provider_status": "live",
        "latitude": raw.get("latitude"),
        "longitude": raw.get("longitude"),
        "timezone": raw.get("timezone"),
        "current": current,
        "derived": {
            "wind_cardinal": _cardinal(wind_dir),
            "rain_1h_in": round(rain_1h, 4),
            "rain_24h_in": round(rain_24h, 4),
        },
        "current_units": raw.get("current_units") or {},
        "hourly_units": raw.get("hourly_units") or {},
    }
