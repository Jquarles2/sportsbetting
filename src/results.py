"""BetGuru's memory: log the parlays it suggests, grade them against final scores, show the record.

This is how the app "learns from results": every suggested leg is stored with the chance the model
gave it, then graded once the game is final. The record and the calibration table (did "60%" legs
really hit about 60% of the time?) show whether the model deserves any trust.

Stored in data/state.db next to the no-bet list. On Streamlit Cloud that file is wiped when the app
restarts, so the record is only as durable as the running app until we add a hosted database.
"""
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from src import nobet

DB_PATH = nobet.DB_PATH
SCHEMA = """CREATE TABLE IF NOT EXISTS picks_log (
    id INTEGER PRIMARY KEY, logged_on TEXT, sport TEXT, risk TEXT, game TEXT, start TEXT,
    market TEXT, pick TEXT, team TEXT, line REAL, price REAL, p REAL,
    result TEXT DEFAULT 'pending', graded_on TEXT,
    UNIQUE (logged_on, sport, risk, game, market, pick))"""


def _connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    return conn


def log_parlay(sport, risk, legs):
    """Save a suggested parlay's legs. Logging the same parlay twice in a day does nothing."""
    with _connect() as conn:
        for leg in legs.itertuples():
            conn.execute(
                "INSERT OR IGNORE INTO picks_log (logged_on, sport, risk, game, start, market, pick, team, line, price, p)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (date.today().isoformat(), sport, risk, leg.GAME, leg.START, leg.MARKET, leg.PICK,
                 leg.TEAM, None if pd.isna(leg.LINE) else float(leg.LINE), float(leg.PRICE), float(leg.P)))


def grade_leg(market, pick, team, line, home, away, home_score, away_score):
    """'win', 'loss' or 'push' for one leg given the final score."""
    if market == "Total":
        total = home_score + away_score
        diff = total - line if pick.startswith("Over") else line - total
    else:
        mine, theirs = (home_score, away_score) if team == home else (away_score, home_score)
        diff = mine - theirs + (line if market == "Spread" else 0)
    return "win" if diff > 0 else "loss" if diff < 0 else "push"


def grade_pending(get_final, now=None):
    """Grade every logged leg whose game is over. Returns how many were graded.

    get_final(sport, home, away, start) returns (home_score, away_score), or None if the game
    isn't final (or can't be found). Games that started under 5 hours ago are left alone.
    """
    now = now or datetime.now(timezone.utc)
    graded = 0
    finals = {}
    with _connect() as conn:
        pending = conn.execute(
            "SELECT id, sport, game, start, market, pick, team, line FROM picks_log WHERE result = 'pending'"
        ).fetchall()
        for pid, sport, game, start, market, pick, team, line in pending:
            started = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if now - started < timedelta(hours=5):
                continue
            away, home = game.split(" @ ")
            if (sport, game) not in finals:  # several legs can share a game; look it up once
                finals[(sport, game)] = get_final(sport, home, away, started)
            final = finals[(sport, game)]
            if final is None:
                continue
            result = grade_leg(market, pick, team, line, home, away, *final)
            conn.execute("UPDATE picks_log SET result = ?, graded_on = ? WHERE id = ?",
                         (result, date.today().isoformat(), pid))
            graded += 1
    return graded


def _legs():
    with _connect() as conn:
        return pd.read_sql_query("SELECT * FROM picks_log", conn)


def record():
    """Record by market: wins, losses, pushes, hit rate, and the average chance the model gave."""
    df = _legs()
    done = df[df["result"].isin(["win", "loss", "push"])]
    rows = []
    for market, g in done.groupby("market"):
        wins, losses = int((g["result"] == "win").sum()), int((g["result"] == "loss").sum())
        rows.append({"MARKET": market, "WINS": wins, "LOSSES": losses,
                     "PUSHES": int((g["result"] == "push").sum()),
                     "HIT_RATE": round(100 * wins / (wins + losses), 1) if wins + losses else None,
                     "MODEL_AVG_P": round(100 * g[g["result"] != "push"]["p"].mean(), 1)})
    return pd.DataFrame(rows, columns=["MARKET", "WINS", "LOSSES", "PUSHES", "HIT_RATE", "MODEL_AVG_P"])


def calibration():
    """Do legs the model rated 50-60%, 60-70% and so on really win that often?"""
    df = _legs()
    df = df[df["result"].isin(["win", "loss"])]
    if df.empty:
        return pd.DataFrame(columns=["MODEL_SAID", "LEGS", "ACTUALLY_HIT"])
    df = df.assign(bucket=(df["p"] * 10).astype(int) / 10)
    out = df.groupby("bucket").agg(LEGS=("p", "size"), HIT=("result", lambda r: (r == "win").mean()))
    return pd.DataFrame({"MODEL_SAID": [f"{int(b * 100)}-{int(b * 100) + 10}%" for b in out.index],
                         "LEGS": out["LEGS"].values, "ACTUALLY_HIT": [f"{h:.0%}" for h in out["HIT"]]})


def parlay_record():
    """How many logged parlays hit, missed or are still waiting. A parlay is one sport, risk and day."""
    df = _legs()
    if df.empty:
        return {"won": 0, "lost": 0, "pending": 0}
    counts = {"won": 0, "lost": 0, "pending": 0}
    for _, g in df.groupby(["logged_on", "sport", "risk"]):
        if (g["result"] == "loss").any():
            counts["lost"] += 1
        elif (g["result"] == "pending").any():
            counts["pending"] += 1
        else:
            counts["won"] += 1  # every leg won or pushed
    return counts
