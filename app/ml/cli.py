
import argparse, asyncio, json
from app.ml.history import backfill_days, update_recent_history
from app.ml.pipeline import train_model, predict_latest
from app.ml.store import init_ml_db, load_metrics, load_observations

def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest="cmd",required=True)
    b=s.add_parser("bootstrap"); b.add_argument("--days",type=int,default=90)
    u=s.add_parser("update"); u.add_argument("--hours",type=int,default=12)
    s.add_parser("train"); s.add_parser("predict"); s.add_parser("status")
    a=p.parse_args(); init_ml_db()
    if a.cmd=="bootstrap":
        print(json.dumps(asyncio.run(backfill_days(a.days)),indent=2))
        print(json.dumps(train_model(),indent=2))
    elif a.cmd=="update": print(json.dumps(asyncio.run(update_recent_history(a.hours)),indent=2))
    elif a.cmd=="train": print(json.dumps(train_model(),indent=2))
    elif a.cmd=="predict": print(json.dumps(predict_latest(),indent=2))
    else:
        d=load_observations()
        print(json.dumps({"rows":len(d),"metrics":load_metrics()},indent=2,default=str))
if __name__=="__main__": main()
