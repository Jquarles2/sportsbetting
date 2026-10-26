"""Your own no-bet list: teams, players or games you never want in a BetGuru parlay.

Stored in a small SQLite file (data/state.db). Everyone using the same running app shares one
list. On Streamlit Cloud the file is wiped when the app restarts, so treat the list as
short-term until we add a hosted database.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "state.db"
KINDS = ("team", "player", "game")


def _connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS nobet (kind TEXT, name TEXT, PRIMARY KEY (kind, name))")
    return conn


def list_items():
    """Every entry as a list of (kind, name) tuples, oldest first."""
    with _connect() as conn:
        return conn.execute("SELECT kind, name FROM nobet ORDER BY rowid").fetchall()


def add(kind, name):
    """Add an entry. Returns False if the name was blank or the kind is unknown."""
    name = " ".join(name.split())
    if kind not in KINDS or not name:
        return False
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO nobet (kind, name) VALUES (?, ?)", (kind, name))
    return True


def remove(kind, name):
    with _connect() as conn:
        conn.execute("DELETE FROM nobet WHERE kind = ? AND name = ?", (kind, name))


def names(kind, items=None):
    """Lowercased names of one kind, for case-insensitive matching."""
    return {n.lower() for k, n in (items if items is not None else list_items()) if k == kind}
