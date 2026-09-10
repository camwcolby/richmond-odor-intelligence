
"""
Live Richmond H2S / wind adapter for Sonoma Insight DMS.

Design goals
------------
- Keep Sonoma-specific request/response quirks inside this module.
- Never hard-code tokens.
- Preserve QC metadata, including Below MDL.
- Ignore Sonoma's -999 missing-value padding.
- Use secure SSL verification by default.
- Allow an explicit local development override for corporate TLS interception.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from app.services.live_cache import cached_async
from app.services.h2s_fallback import h2s_fallback_from_ml_store
from app.services.h2s_recent_recovery import recent_h2s_from_history
from app.services.sonoma_auth import raise_for_sonoma_application_error, SonomaAuthorizationError

load_dotenv()

SONOMA_URL = os.getenv(
    "SONOMA_DMS_URL",
    "https://insightdms.sonomatech.com/api/TimeSeriesData/filterAsTimeSeriesJson",
)

NORTH_H2S_STREAM = int(os.getenv("SONOMA_NORTH_H2S_STREAM", "9950"))
SOUTH_H2S_STREAM = int(os.getenv("SONOMA_SOUTH_H2S_STREAM", "9963"))
WIND_SPEED_STREAM = int(os.getenv("SONOMA_WIND_SPEED_STREAM", "9986"))
WIND_DIRECTION_STREAM = int(os.getenv("SONOMA_WIND_DIRECTION_STREAM", "9987"))

INTERVAL_SECONDS = int(os.getenv("SONOMA_INTERVAL_SECONDS", "300"))
LOOKBACK_HOURS = int(os.getenv("SONOMA_LOOKBACK_HOURS", "2"))

# Known coordinates from the Sonoma response already observed for North Side.
# Other coordinates are populated from live response metadata whenever available.
DEFAULT_SENSOR_COORDS = {
    NORTH_H2S_STREAM: {"lat": 37.921047, "lon": -122.37995},
}

MISSING_SENTINELS = {-999, -999.0, -9999, -9999.0}


class SonomaConfigurationError(RuntimeError):
    """Raised when required Sonoma configuration is missing."""


class SonomaResponseError(RuntimeError):
    """Raised when Sonoma returns an unexpected or unsuccessful response."""


def _token() -> str:
    token = os.getenv("SONOMA_DMS_TOKEN", "").strip()
    if not token:
        raise SonomaConfigurationError(
            "SONOMA_DMS_TOKEN is not configured. Add it to the local .env file."
        )
    return token


def _ssl_verify_setting() -> bool | str:
    """
    Secure by default.

    Supported .env settings:
      SONOMA_SSL_VERIFY=true
      SONOMA_SSL_VERIFY=false                  # local diagnostic only
      SONOMA_CA_BUNDLE=C:\\path\\corp-ca.pem   # preferred corporate TLS solution
    """
    ca_bundle = os.getenv("SONOMA_CA_BUNDLE", "").strip()
    if ca_bundle:
        path = Path(ca_bundle)
        if not path.exists():
            raise SonomaConfigurationError(
                f"SONOMA_CA_BUNDLE does not exist: {ca_bundle}"
            )
        return str(path)

    raw = os.getenv("SONOMA_SSL_VERIFY", "true").strip().lower()

    if raw in {"false", "0", "no", "off"}:
        return False

    return True


def _build_form_data(start_utc: datetime, end_utc: datetime) -> dict[str, str]:
    start_string = start_utc.strftime("%Y-%m-%dT%H:%M:%S")
    end_string = end_utc.strftime("%Y-%m-%dT%H:%M:%S")

    inner = {
        "sc": "TimeSeries",
        "dataStreams": [
            SOUTH_H2S_STREAM,
            NORTH_H2S_STREAM,
        ],
        "publicDataOnly": False,
        "primaryDataOnly": False,
        "isUtc": True,
        "isMulticolorSeries": True,
        "durationId": 2,
        "aggregateId": 0,
        "startDateTime": start_string,
        "endDateTime": end_string,
        "validDataOnly": False,
        "wsDataStreamId": WIND_SPEED_STREAM,
        "wdDataStreamId": WIND_DIRECTION_STREAM,
        "windDurationId": 5,
        "windAggregateId": 0,
        "intervalSeconds": INTERVAL_SECONDS,
        "percentComplete": 60,
    }

    return {
        "input": json.dumps(inner),
        "token": _token(),
        "type": "highchartsJson",
        "isMulticolorSeries": "true",
        "fillMissingPoints": "true",
        "useUtc": "true",
        "wsDataStreamId": str(WIND_SPEED_STREAM),
        "wdDataStreamId": str(WIND_DIRECTION_STREAM),
        "windDurationId": "5",
        "windAggregateId": "-1",
        "intervalSeconds": str(INTERVAL_SECONDS),
    }


def _is_valid_observation(obs: dict[str, Any]) -> bool:
    value = obs.get("value")

    if value is None:
        return False

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False

    if numeric in MISSING_SENTINELS:
        return False

    if str(obs.get("qcName", "")).lower() == "missing":
        return False

    return True


def _latest_valid(observations: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [obs for obs in observations if _is_valid_observation(obs)]
    return valid[-1] if valid else None


def _series_stream_id(series: dict[str, Any]) -> int | None:
    raw = series.get("dataStreamId") or series.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _series_name(series: dict[str, Any]) -> str:
    return str(series.get("name") or "").strip()


def _normalized_sensor(series: dict[str, Any]) -> dict[str, Any] | None:
    stream_id = _series_stream_id(series)
    if stream_id not in {NORTH_H2S_STREAM, SOUTH_H2S_STREAM}:
        return None

    latest = _latest_valid(series.get("data", []) or [])
    if not latest:
        return None

    site_info = latest.get("siteInfo") or {}
    coords = DEFAULT_SENSOR_COORDS.get(stream_id, {})

    lat = (
        latest.get("latitude")
        or site_info.get("latitude")
        or series.get("latitude")
        or coords.get("lat")
    )
    lon = (
        latest.get("longitude")
        or site_info.get("longitude")
        or series.get("longitude")
        or coords.get("lon")
    )

    site_name = (
        site_info.get("siteName")
        or _series_name(series).replace("Hydrogen Sulfide (PPB)", "").strip()
        or f"Sensor {stream_id}"
    )

    unit = latest.get("unitName") or series.get("unitName") or "PPB"

    return {
        "id": str(stream_id),
        "data_stream_id": stream_id,
        "name": site_name,
        "lat": float(lat) if lat is not None else None,
        "lon": float(lon) if lon is not None else None,
        "h2s_ppb": float(latest["value"]),
        "unit": unit,
        "timestamp_utc": latest.get("utc"),
        "timestamp_local": latest.get("lst"),
        "qc": latest.get("qcName"),
        "operation_qc": latest.get("opName"),
        "below_mdl": str(latest.get("opName", "")).lower() == "below mdl",
        "mdl_ppb": latest.get("mdl"),
        "simulated": False,
        "source": "Sonoma Insight DMS",
    }


def _extract_wind_point(point: dict[str, Any]) -> dict[str, Any]:
    """
    Sonoma's wind payload is not shaped exactly like the H2S observation payload.
    Pull defensively from several likely field names.

    Unknown fields remain None rather than being guessed.
    """
    speed = (
        point.get("value")
        if point.get("value") is not None
        else point.get("speed")
    )

    direction = None
    for key in (
        "windDirection",
        "wind_direction",
        "direction",
        "wd",
        "degrees",
        "degree",
    ):
        if point.get(key) is not None:
            direction = point.get(key)
            break

    timestamp = (
        point.get("utc")
        or point.get("timestamp")
        or point.get("dateTime")
        or point.get("datetime")
        or point.get("time")
    )

    return {
        "speed_mps": float(speed) if speed is not None else None,
        "direction_deg": float(direction) if direction is not None else None,
        "timestamp_utc": timestamp,
    }


def _normalize_wind(series_list: list[dict[str, Any]]) -> dict[str, Any] | None:
    for series in series_list:
        stream_id = _series_stream_id(series)
        name = _series_name(series).lower()

        if stream_id != WIND_SPEED_STREAM and "wind speed" not in name:
            continue

        points = series.get("data", []) or []
        if not points:
            return None

        # Wind points may not carry qcName, so use the last numeric, non-sentinel point.
        usable = []
        for p in points:
            value = p.get("value")
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue

            if numeric in MISSING_SENTINELS:
                continue

            usable.append(p)

        if not usable:
            return None

        latest = usable[-1]
        normalized = _extract_wind_point(latest)
        normalized.update(
            {
                "speed_stream_id": WIND_SPEED_STREAM,
                "direction_stream_id": WIND_DIRECTION_STREAM,
                "source": "Sonoma Insight DMS",
            }
        )
        return normalized

    return None


async def _fetch_raw(
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
) -> dict[str, Any]:
    if end_utc is None:
        end_utc = datetime.now(timezone.utc)

    if start_utc is None:
        start_utc = end_utc - timedelta(hours=LOOKBACK_HOURS)

    form_data = _build_form_data(start_utc, end_utc)

    verify = _ssl_verify_setting()

    async with httpx.AsyncClient(
        timeout=30.0,
        verify=verify,
        follow_redirects=True,
    ) as client:
        response = await client.post(
            SONOMA_URL,
            data=form_data,
        )

    response.raise_for_status()

    result = response.json()

    if result.get("isFailure") is True:
        raise SonomaResponseError(
            result.get("message") or "Sonoma returned isFailure=true"
        )

    if str(result.get("message", "")).lower() not in {"", "success"}:
        raise SonomaResponseError(
            f"Unexpected Sonoma response: {result.get('message')}"
        )

    return result



async def get_h2s(*args, **kwargs):
    async def _live():
        try:
            return await _get_h2s_uncached(*args, **kwargs)
        except SonomaResponseError as exc:
            recent = await recent_h2s_from_history(hours=6)
            if recent is not None:
                print("[H2S] Current Sonoma slot invalid; using latest valid Sonoma observation from recent history.")
                recent["metadata"]["live_error"] = str(exc)
                return recent
            fallback = h2s_fallback_from_ml_store()
            if fallback is not None:
                print("[H2S] Sonoma recent history unavailable; using latest ingested historical observation.")
                fallback["metadata"]["live_error"] = str(exc)
                return fallback
            raise

    return await cached_async(
        "sonoma_current_h2s",
        _live,
        ttl_seconds=120,
        stale_seconds=21600,
    )


async def _get_h2s_uncached() -> dict[str, Any]:
    """
    Public service contract consumed by the FastAPI application.

    Returns live H2S sensors plus Sonoma wind if present.
    """
    raw = await _fetch_raw()
    series_list = raw.get("timeSeriesData", []) or []

    sensors = []
    for series in series_list:
        sensor = _normalized_sensor(series)
        if sensor:
            sensors.append(sensor)

    if not sensors:
        raise SonomaResponseError(
            "Sonoma returned no valid Richmond H2S observations."
        )

    wind = _normalize_wind(series_list)

    timestamps = [
        s.get("timestamp_utc")
        for s in sensors
        if s.get("timestamp_utc")
    ]

    latest_timestamp = max(timestamps) if timestamps else None

    return {
        "timestamp": latest_timestamp,
        "source": "Sonoma Insight DMS",
        "simulated": False,
        "sensors": sensors,
        "wind": wind,
        "metadata": {
            "north_h2s_stream": NORTH_H2S_STREAM,
            "south_h2s_stream": SOUTH_H2S_STREAM,
            "wind_speed_stream": WIND_SPEED_STREAM,
            "wind_direction_stream": WIND_DIRECTION_STREAM,
            "interval_seconds": INTERVAL_SECONDS,
        },
    }


async def get_h2s_history(hours: int = 24) -> dict[str, Any]:
    """
    Normalized historical observations for later persistence/model training.

    This keeps valid and Below-MDL values, but excludes explicit Missing/-999 rows.
    """
    hours = max(1, min(int(hours), 168))

    end_utc = datetime.now(timezone.utc)
    start_utc = end_utc - timedelta(hours=hours)

    raw = await _fetch_raw(start_utc=start_utc, end_utc=end_utc)
    series_list = raw.get("timeSeriesData", []) or []

    rows: list[dict[str, Any]] = []

    for series in series_list:
        stream_id = _series_stream_id(series)

        if stream_id not in {NORTH_H2S_STREAM, SOUTH_H2S_STREAM}:
            continue

        for obs in series.get("data", []) or []:
            if not _is_valid_observation(obs):
                continue

            site_info = obs.get("siteInfo") or {}

            rows.append(
                {
                    "timestamp_utc": obs.get("utc"),
                    "timestamp_local": obs.get("lst"),
                    "data_stream_id": stream_id,
                    "site_id": obs.get("siteId") or series.get("siteId"),
                    "site_name": site_info.get("siteName"),
                    "parameter": obs.get("parameterName") or "Hydrogen Sulfide",
                    "parameter_id": obs.get("parameterId") or series.get("parameterId"),
                    "unit": obs.get("unitName") or series.get("unitName") or "PPB",
                    "value": float(obs["value"]),
                    "qc": obs.get("qcName"),
                    "operation_qc": obs.get("opName"),
                    "below_mdl": str(obs.get("opName", "")).lower() == "below mdl",
                    "mdl": obs.get("mdl"),
                    "latitude": obs.get("latitude") or site_info.get("latitude"),
                    "longitude": obs.get("longitude") or site_info.get("longitude"),
                }
            )

    rows.sort(key=lambda r: (r.get("timestamp_utc") or "", r["data_stream_id"]))

    return {
        "source": "Sonoma Insight DMS",
        "hours_requested": hours,
        "observation_count": len(rows),
        "observations": rows,
    }
