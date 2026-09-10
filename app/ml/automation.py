
import asyncio, os, threading, time
from datetime import datetime, timezone
from app.ml.history import update_recent_history
from app.ml.pipeline import train_model
from app.ml.store import load_metrics
_started=False

def _age():
    m=load_metrics()
    if not m: return None
    try:
        d=datetime.fromisoformat(m["trained_at_utc"].replace("Z","+00:00"))
        return (datetime.now(timezone.utc)-d).total_seconds()/3600
    except: return None

def _loop():
    minutes=max(5,int(os.getenv("ML_INGEST_MINUTES","15")))
    retrain=max(1,int(os.getenv("ML_RETRAIN_HOURS","24")))
    time.sleep(8)
    while True:
        try:
            asyncio.run(update_recent_history(12))
            age=_age()
            if age is None or age>=retrain:
                try: train_model()
                except Exception as e: print("[ML] retrain skipped:",e)
        except Exception as e: print("[ML] ingest failed:",e)
        time.sleep(minutes*60)

def start_ml_automation():
    global _started
    if os.getenv("ML_AUTOMATION_ENABLED","true").lower() not in {"true","1","yes","on"} or _started: return
    _started=True
    threading.Thread(target=_loop,daemon=True,name="richmond-ml").start()
