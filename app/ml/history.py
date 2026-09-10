
from __future__ import annotations
import asyncio, os
from datetime import datetime, timedelta, timezone
import httpx, pandas as pd
from app.ml.store import upsert_observations
from app.services.h2s import NORTH_H2S_STREAM, SOUTH_H2S_STREAM, _fetch_raw
from app.services.weather import _ssl_verify_setting

ARCHIVE = os.getenv("OPEN_METEO_ARCHIVE_URL","https://archive-api.open-meteo.com/v1/archive")
NOAA = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
STATION = os.getenv("NOAA_STATION","9414863")
LAT = float(os.getenv("RICHMOND_LAT","37.9358"))
LON = float(os.getenv("RICHMOND_LON","-122.3477"))

def _valid(obs):
    try: v=float(obs.get("value"))
    except: return None
    if v in {-999.0,-9999.0} or str(obs.get("qcName","")).lower()=="missing":
        return None
    return v

async def _sonoma(start,end):
    out=[]; cur=start
    while cur<end:
        nxt=min(cur+timedelta(days=7),end)
        raw=await _fetch_raw(start_utc=cur,end_utc=nxt)
        for s in raw.get("timeSeriesData",[]) or []:
            sid=s.get("dataStreamId") or s.get("id")
            try: sid=int(sid)
            except: continue
            if sid not in {NORTH_H2S_STREAM,SOUTH_H2S_STREAM}: continue
            col="north_h2s_ppb" if sid==NORTH_H2S_STREAM else "south_h2s_ppb"
            for o in s.get("data",[]) or []:
                v=_valid(o); ts=o.get("utc")
                if v is not None and ts:
                    out.append({"timestamp_utc":pd.to_datetime(ts,utc=True),col:v})
        cur=nxt
    if not out: return pd.DataFrame()
    df=pd.DataFrame(out).groupby("timestamp_utc",as_index=False).last()
    return df.sort_values("timestamp_utc")

async def _weather(start,end):
    params={
      "latitude":LAT,"longitude":LON,
      "start_date":start.date().isoformat(),"end_date":end.date().isoformat(),
      "hourly":"temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m",
      "temperature_unit":"fahrenheit","wind_speed_unit":"ms","precipitation_unit":"inch","timezone":"UTC"
    }
    async with httpx.AsyncClient(timeout=45,verify=_ssl_verify_setting(),follow_redirects=True) as c:
        r=await c.get(ARCHIVE,params=params)
    r.raise_for_status(); h=(r.json().get("hourly") or {})
    if not h.get("time"): return pd.DataFrame()
    d=pd.DataFrame({
      "timestamp_utc":pd.to_datetime(h["time"],utc=True),
      "temperature_f":h.get("temperature_2m"),
      "relative_humidity_pct":h.get("relative_humidity_2m"),
      "precipitation_in":h.get("precipitation"),
      "wind_speed_mps":h.get("wind_speed_10m"),
      "wind_direction_deg":h.get("wind_direction_10m")
    })
    d["precipitation_in"]=pd.to_numeric(d["precipitation_in"],errors="coerce").fillna(0)
    d["rain_1h_in"]=d["precipitation_in"]
    d["rain_24h_in"]=d["precipitation_in"].rolling(24,min_periods=1).sum()
    return d

async def _tide(start,end):
    frames=[]; cur=start
    while cur<end:
        nxt=min(cur+timedelta(days=31),end)
        params={"begin_date":cur.strftime("%Y%m%d"),"end_date":nxt.strftime("%Y%m%d"),
          "station":STATION,"product":"predictions","datum":"MLLW","time_zone":"gmt",
          "interval":"h","units":"english","format":"json","application":"richmond_odor_ml"}
        try:
            async with httpx.AsyncClient(timeout=30,verify=_ssl_verify_setting(),follow_redirects=True) as c:
                r=await c.get(NOAA,params=params)
            r.raise_for_status(); p=r.json().get("predictions",[]) or []
            if p:
                frames.append(pd.DataFrame({"timestamp_utc":pd.to_datetime([x["t"] for x in p],utc=True),
                                            "tide_ft_mllw":[float(x["v"]) for x in p]}))
        except Exception:
            pass
        cur=nxt
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()

async def ingest_range(start,end):
    s,w,t=await asyncio.gather(_sonoma(start,end),_weather(start,end),_tide(start,end))
    if s.empty: return {"rows":0}
    s=s.set_index("timestamp_utc").resample("15min").mean().reset_index()
    if not w.empty:
        s=pd.merge_asof(s.sort_values("timestamp_utc"),w.sort_values("timestamp_utc"),
                        on="timestamp_utc",direction="backward",tolerance=pd.Timedelta("90min"))
    if not t.empty:
        s=pd.merge_asof(s.sort_values("timestamp_utc"),t.sort_values("timestamp_utc"),
                        on="timestamp_utc",direction="nearest",tolerance=pd.Timedelta("90min"))
    s["source_updated_at"]=datetime.now(timezone.utc).isoformat()
    rows=s.where(pd.notnull(s),None).to_dict("records")
    for r in rows:
        if hasattr(r["timestamp_utc"],"isoformat"): r["timestamp_utc"]=r["timestamp_utc"].isoformat()
    return {"rows":upsert_observations(rows),"sonoma_rows":len(s),"weather_rows":len(w),"tide_rows":len(t)}

async def backfill_days(days=90):
    end=datetime.now(timezone.utc); start=end-timedelta(days=max(2,int(days)))
    return await ingest_range(start,end)

async def update_recent_history(hours=12):
    end=datetime.now(timezone.utc); start=end-timedelta(hours=max(2,int(hours)))
    return await ingest_range(start,end)
