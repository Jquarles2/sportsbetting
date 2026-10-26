"""Where BetGuru keeps things that should outlive a single page view.

Two homes, same interface:
- SupabaseStore: a free hosted Postgres database (reached over plain HTTPS with `requests`).
  This survives Streamlit Cloud restarts. Used when SUPABASE_URL and SUPABASE_KEY are in secrets.
- SQLiteStore: a file in data/. Used otherwise (local runs, tests). Streamlit Cloud wipes it on restart.

What lives here: your no-bet list, the results log, and (Supabase only) the Odds API cache, so a
restart doesn't make you re-spend your monthly request budget.
"""
import json
import sqlite3
from pathlib import Path

import requests

from src.config import get_secret

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "state.db"
PICK_COLUMNS = ["logged_on", "sport", "risk", "game", "start", "market", "pick", "team", "line", "price", "p"]
PICK_KEY = ["logged_on", "sport", "risk", "game", "market", "pick"]  # one row per leg per day
TABLES = ("nobet", "picks_log", "cache")


class StoreError(RuntimeError):
    """A storage problem with a message fit to show on screen."""


class SQLiteStore:
    """Everything in one local file. Fine for development; lost when a cloud app restarts."""

    name = "a local file (it is wiped when the app restarts)"
    durable = False

    def _connect(self):
        DB_PATH.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE IF NOT EXISTS nobet (kind TEXT, name TEXT, PRIMARY KEY (kind, name))")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS picks_log (id INTEGER PRIMARY KEY, logged_on TEXT, sport TEXT, "
            "risk TEXT, game TEXT, start TEXT, market TEXT, pick TEXT, team TEXT, line REAL, price REAL, "
            "p REAL, result TEXT DEFAULT 'pending', graded_on TEXT, "
            f"UNIQUE ({', '.join(PICK_KEY)}))")
        return conn

    def check(self):
        self._connect().close()

    # --- no-bet list ---
    def nobet_list(self):
        with self._connect() as conn:
            return [(r["kind"], r["name"]) for r in conn.execute("SELECT kind, name FROM nobet ORDER BY rowid")]

    def nobet_add(self, kind, name):
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO nobet (kind, name) VALUES (?, ?)", (kind, name))

    def nobet_remove(self, kind, name):
        with self._connect() as conn:
            conn.execute("DELETE FROM nobet WHERE kind = ? AND name = ?", (kind, name))

    # --- results log ---
    def picks_add(self, rows):
        """Save legs; a leg already saved today (same sport, risk, game, market and pick) is ignored."""
        with self._connect() as conn:
            for r in rows:
                conn.execute(f"INSERT OR IGNORE INTO picks_log ({', '.join(PICK_COLUMNS)}) "
                             f"VALUES ({', '.join('?' * len(PICK_COLUMNS))})", [r[c] for c in PICK_COLUMNS])

    def picks_all(self):
        with self._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM picks_log ORDER BY id")]

    def picks_pending(self):
        with self._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM picks_log WHERE result = 'pending' ORDER BY id")]

    def picks_grade(self, pick_id, result, graded_on):
        with self._connect() as conn:
            conn.execute("UPDATE picks_log SET result = ?, graded_on = ? WHERE id = ?", (result, graded_on, pick_id))

    # --- durable cache (SQLite has no use for it: src/cache.py already keeps a local copy) ---
    def cache_get(self, key, day):
        return None

    def cache_put(self, key, day, value):
        return None


class SupabaseStore:
    """Supabase's REST API (PostgREST). The tables come from docs/supabase_setup.sql."""

    name = "Supabase (saved permanently)"
    durable = True

    def __init__(self, url, key):
        self.base = url.rstrip("/") + "/rest/v1"
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _request(self, method, table, params=None, body=None, prefer=None):
        headers = {**self.headers, **({"Prefer": prefer} if prefer else {})}
        try:
            resp = requests.request(method, f"{self.base}/{table}", params=params, headers=headers,
                                    data=None if body is None else json.dumps(body), timeout=15)
        except requests.RequestException as e:
            raise StoreError(f"Couldn't reach Supabase: {e}") from e
        if resp.status_code in (401, 403):
            raise StoreError("Supabase rejected the key (check SUPABASE_KEY: use the secret / service_role key).")
        if resp.status_code == 404 or (resp.status_code == 400 and "does not exist" in resp.text):
            raise StoreError(f"Supabase has no '{table}' table yet. Run docs/supabase_setup.sql in its SQL editor.")
        if not resp.ok:
            raise StoreError(f"Supabase {method} {table} failed ({resp.status_code}): {resp.text[:200]}")
        return resp.json() if resp.text else None

    def _get_all(self, table, params):
        """Every matching row. Supabase returns at most 1000 per request, so page through them."""
        rows, offset = [], 0
        while True:
            page = self._request("GET", table, {**params, "limit": 1000, "offset": offset})
            rows += page
            if len(page) < 1000:
                return rows
            offset += 1000

    def check(self):
        for table in TABLES:
            self._request("GET", table, {"select": "*", "limit": 1})

    # --- no-bet list ---
    def nobet_list(self):
        rows = self._get_all("nobet", {"select": "kind,name", "order": "created_at.asc"})
        return [(r["kind"], r["name"]) for r in rows]

    def nobet_add(self, kind, name):
        self._request("POST", "nobet", {"on_conflict": "kind,name"}, {"kind": kind, "name": name},
                      prefer="resolution=ignore-duplicates,return=minimal")

    def nobet_remove(self, kind, name):
        self._request("DELETE", "nobet", {"kind": f"eq.{kind}", "name": f"eq.{name}"})

    # --- results log ---
    def picks_add(self, rows):
        if rows:
            self._request("POST", "picks_log", {"on_conflict": ",".join(PICK_KEY)}, list(rows),
                          prefer="resolution=ignore-duplicates,return=minimal")

    def picks_all(self):
        return self._get_all("picks_log", {"select": "*", "order": "id.asc"})

    def picks_pending(self):
        return self._get_all("picks_log", {"select": "*", "result": "eq.pending", "order": "id.asc"})

    def picks_grade(self, pick_id, result, graded_on):
        self._request("PATCH", "picks_log", {"id": f"eq.{pick_id}"}, {"result": result, "graded_on": graded_on},
                      prefer="return=minimal")

    # --- durable cache ---
    def cache_get(self, key, day):
        rows = self._request("GET", "cache", {"select": "value", "key": f"eq.{key}", "day": f"eq.{day}"})
        return rows[0]["value"] if rows else None

    def cache_put(self, key, day, value):
        self._request("POST", "cache", {"on_conflict": "key"}, {"key": key, "day": day, "value": value},
                      prefer="resolution=merge-duplicates,return=minimal")


def get_store():
    """Supabase if SUPABASE_URL and SUPABASE_KEY are set in secrets, otherwise the local file."""
    url, key = get_secret("SUPABASE_URL"), get_secret("SUPABASE_KEY")
    if url and key:
        return SupabaseStore(url, key)
    return SQLiteStore()
