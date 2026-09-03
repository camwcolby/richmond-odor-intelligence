
import os
import httpx
from datetime import datetime, timedelta

STATION = os.getenv("NOAA_STATION", "9414863")
BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

async def get_tide_predictions():
    now = datetime.utcnow()
    begin = now.strftime("%Y%m%d")
    end = (now + timedelta(days=1)).strftime("%Y%m%d")
    params = {
        "begin_date": begin,
        "end_date": end,
        "station": STATION,
        "product": "predictions",
        "datum": "MLLW",
        "time_zone": "lst_ldt",
        "interval": "h",
        "units": "english",
        "format": "json",
        "application": "richmond_odor_intelligence"
    }
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        return r.json()
