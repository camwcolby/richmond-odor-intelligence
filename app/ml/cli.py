
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
