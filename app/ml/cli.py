
import argparse, asyncio, json
from app.ml.history import backfill_days, update_recent_history
from app.ml.pipeline import train_model, predict_latest
from app.ml.store import init_ml_db, load_metrics, load_observations

def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest="cmd",required=True)
    b=s.add_parser("bootstrap"); b.add_argument("--days",type=int,default=90)
    u=s.add_parser("update"); u.add_argument("--hours",type=int,default=12)
    s.add_parser("event-test");
    ev=s.add_parser("event-data"); ev.add_argument("--start",default="2026-10-17"); ev.add_argument("--end",default="2026-10-27"); s.add_parser("train"); s.add_parser("benchmark"); s.add_parser("predict"); s.add_parser("status")
    remote=s.add_parser("import-render")
    remote.add_argument("--url",default="https://richmond-odor-intelligence.onrender.com")
    remote.add_argument("--start",default="2026-10-17")
    remote.add_argument("--end",default="2026-10-27")
    a=p.parse_args(); init_ml_db()
    if a.cmd=="bootstrap":
        print(json.dumps(asyncio.run(backfill_days(a.days)),indent=2))
        print(json.dumps(train_model(),indent=2))
    elif a.cmd=="update": print(json.dumps(asyncio.run(update_recent_history(a.hours)),indent=2))
    elif a.cmd=="event-data":
        from datetime import datetime, timezone, timedelta
        from app.ml.history import ingest_range
        start=datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc)
        end=datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc)
        if end <= start or (end-start).days > 35: p.error("Choose a positive range no longer than 35 days")
        print(json.dumps(asyncio.run(ingest_range(start,end)),indent=2))
    elif a.cmd=="import-render":
        import os, getpass, urllib.request, urllib.parse, urllib.error
        from app.ml.store import upsert_observations
        from datetime import date
        start=date.fromisoformat(a.start); end=date.fromisoformat(a.end)
        if end <= start or (end-start).days > 35: p.error("Choose a positive range no longer than 35 days")
        token=os.environ.get("ML_EXPORT_TOKEN") or getpass.getpass("Render ML export token: ")
        if not token: p.error("Export token is required")
        url=a.url.rstrip("/")+"/api/ml/observations/export?"+urllib.parse.urlencode(
            {"start_date":a.start,"end_date":a.end})
        req=urllib.request.Request(url,headers={"X-Export-Token":token,"Accept":"application/json"})
        try:
            with urllib.request.urlopen(req,timeout=90) as response:
                payload=json.load(response)
        except urllib.error.HTTPError as exc:
            p.error(f"Render export returned HTTP {exc.code}; verify token, deployment and dates")
        rows=payload.get("rows",[])
        count=upsert_observations(rows)
        print(json.dumps({"imported_rows":count,"render_rows":payload.get("row_count"),
                          "date_start":a.start,"date_end":a.end},indent=2))
    elif a.cmd=="event-test":
        from app.ml.event_experiment import run
        print(json.dumps(run(), indent=2, default=str))
    elif a.cmd=="train": print(json.dumps(train_model(),indent=2))
    elif a.cmd=="benchmark": print(json.dumps(train_model(persist=False),indent=2))
    elif a.cmd=="predict": print(json.dumps(predict_latest(),indent=2))
    else:
        d=load_observations()
        print(json.dumps({"rows":len(d),"metrics":load_metrics()},indent=2,default=str))
if __name__=="__main__": main()
