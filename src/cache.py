"""Tiny cache: one JSON blob per key, valid for the day it was saved.

This is how we avoid refetching data we already have today. Everything is kept in a local SQLite file.
Odds API answers (keys starting with "odds_") are also copied to Supabase when it's configured, because
those cost real requests from a monthly budget and a cloud restart wipes the local file.
"""
import json
import sqlite3
import time
from datetime import date
from pathlib import Path

DURABLE_PREFIXES = ("odds_",)
MISS_SECONDS = 60  # after a failed or empty Supabase lookup, don't ask again for a minute (keeps clicks fast)
_recent_misses = {}
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cache.db"


def _connect(db_path=None):
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, day TEXT, value TEXT)"
    )
    return conn


def _durable_store(key, db_path):
    """The Supabase store if this key should live there, else None. An explicit db_path means a test."""
    if db_path is not None or not key.startswith(DURABLE_PREFIXES):
        return None
    from src import store  # imported here so a plain cache lookup never needs Supabase
    db = store.get_store()
    return db if db.durable else None


def get(key, db_path=None):
    """Return the cached value for key if it was saved today, else None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM cache WHERE key = ? AND day = ?",
            (key, date.today().isoformat()),
        ).fetchone()
    if row:
        return json.loads(row[0])
    db = _durable_store(key, db_path)
    if db is None or time.monotonic() - _recent_misses.get(key, -MISS_SECONDS) < MISS_SECONDS:
        return None
    try:
        value = db.cache_get(key, date.today().isoformat())
    except Exception:
        value = None  # Supabase trouble just means a cache miss, never a crash
    if value is None:
        _recent_misses[key] = time.monotonic()
        return None
    put(key, value, db_path, remote=False)  # keep a local copy for the next lookup
    return value


def put(key, value, db_path=None, remote=True):
    """Save value (must be JSON-serializable) under key, stamped with today's date."""
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, day, value) VALUES (?, ?, ?)",
            (key, date.today().isoformat(), json.dumps(value)),
        )
    _recent_misses.pop(key, None)
    db = _durable_store(key, db_path) if remote else None
    if db is not None:
        try:
            db.cache_put(key, date.today().isoformat(), value)
        except Exception:
            pass  # the local copy is saved; a Supabase hiccup shouldn't break the page
