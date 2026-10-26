"""BetGuru's memory: log the parlays it suggests, grade them against final scores, show the record.

This is how the app "learns from results": every suggested leg is stored with the chance the model
gave it, then graded once the game is final. The record and the calibration table (did "60%" legs
really hit about 60% of the time?) show whether the model deserves any trust.

Saved through src/store.py: in Supabase when it's configured (survives restarts), otherwise in a local
file that a cloud restart wipes.
"""
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from src import store

COLUMNS = ["id", "logged_on", "sport", "risk", "game", "start", "market", "pick", "team", "line",
           "price", "p", "result", "graded_on"]


def log_parlay(sport, risk, legs):
    """Save a suggested parlay's legs. Logging the same parlay twice in a day does nothing."""
    today = date.today().isoformat()
    rows = [{"logged_on": today, "sport": sport, "risk": risk, "game": leg.GAME, "start": leg.START,
             "market": leg.MARKET, "pick": leg.PICK, "team": None if pd.isna(leg.TEAM) else leg.TEAM,
             "line": None if pd.isna(leg.LINE) else float(leg.LINE), "price": float(leg.PRICE),
             "p": float(leg.P)} for leg in legs.itertuples()]
    store.get_store().picks_add(rows)


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
    db = store.get_store()
    graded, finals = 0, {}
    for leg in db.picks_pending():
        started = datetime.fromisoformat(leg["start"].replace("Z", "+00:00"))
        if now - started < timedelta(hours=5):
            continue
        away, home = leg["game"].split(" @ ")
        if (leg["sport"], leg["game"]) not in finals:  # several legs can share a game; look it up once
            finals[(leg["sport"], leg["game"])] = get_final(leg["sport"], home, away, started)
        final = finals[(leg["sport"], leg["game"])]
        if final is None:
            continue
        result = grade_leg(leg["market"], leg["pick"], leg["team"], leg["line"], home, away, *final)
        db.picks_grade(leg["id"], result, date.today().isoformat())
        graded += 1
    return graded


def _legs():
    return pd.DataFrame(store.get_store().picks_all(), columns=COLUMNS)


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
