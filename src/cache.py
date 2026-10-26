"""Tiny SQLite cache: one JSON blob per key, valid for the day it was saved.

This is how we avoid refetching data we already have today.
"""
import json
import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cache.db"


def _connect(db_path=None):
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, day TEXT, value TEXT)"
    )
    return conn


def get(key, db_path=None):
    """Return the cached value for key if it was saved today, else None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM cache WHERE key = ? AND day = ?",
            (key, date.today().isoformat()),
        ).fetchone()
    return json.loads(row[0]) if row else None


def put(key, value, db_path=None):
    """Save value (must be JSON-serializable) under key, stamped with today's date."""
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, day, value) VALUES (?, ?, ?)",
            (key, date.today().isoformat(), json.dumps(value)),
        )
