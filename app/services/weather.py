
import os
import httpx

LAT = float(os.getenv("RICHMOND_LAT", "37.9358"))
LON = float(os.getenv("RICHMOND_LON", "-122.3477"))

URL = "https://api.open-meteo.com/v1/forecast"

async def get_weather():
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": ",".join([
            "temperature_2m", "relative_humidity_2m", "precipitation",
            "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"
        ]),
        "hourly": ",".join([
            "temperature_2m", "relative_humidity_2m", "precipitation",
            "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"
        ]),
        "forecast_days": 2,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "America/Los_Angeles"
    }
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(URL, params=params)
        r.raise_for_status()
        return r.json()
