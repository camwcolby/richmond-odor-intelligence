
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = os.getenv("DATABASE_PATH", "data/odor_demo.db")

def connect():
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id TEXT UNIQUE NOT NULL,
            reported_at TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            public_location TEXT NOT NULL,
            odor_type TEXT NOT NULL,
            intensity INTEGER NOT NULL,
            comments TEXT,
            status TEXT NOT NULL,
            cmms_work_order TEXT NOT NULL
        )
        """)
        conn.commit()

def complaint_count():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) c FROM complaints").fetchone()["c"]

def seed_if_empty(rows):
    if complaint_count():
        return
    with connect() as conn:
        conn.executemany("""
        INSERT INTO complaints
        (complaint_id, reported_at, latitude, longitude, public_location,
         odor_type, intensity, comments, status, cmms_work_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()

def list_complaints(limit=100):
    with connect() as conn:
        cur = conn.execute("""
        SELECT * FROM complaints ORDER BY reported_at DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]

def insert_complaint(row):
    with connect() as conn:
        conn.execute("""
        INSERT INTO complaints
        (complaint_id, reported_at, latitude, longitude, public_location,
         odor_type, intensity, comments, status, cmms_work_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, row)
        conn.commit()

def update_status(complaint_id, status):
    with connect() as conn:
        conn.execute(
            "UPDATE complaints SET status=? WHERE complaint_id=?",
            (status, complaint_id)
        )
        conn.commit()
