"""Player prop lines (NBA points, NFL yards, ...) from The Odds API (https://the-odds-api.com).

The free plan is ~500 requests/month. Listing games is free, but each game's props cost
1 request per market, so we only fetch when asked and cache the result for the day.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from src import cache
from src.config import get_secret

BASE_URL = "https://api.the-odds-api.com/v4"
NBA = "basketball_nba"
NFL = "americanfootball_nfl"
BOOKMAKER = "fanduel"  # the only book we use
COLUMNS = ["PLAYER", "GAME", "BOOK", "LINE", "OVER", "UNDER", "START"]
LINE_COLUMNS = ["GAME", "HOME", "AWAY", "START", "ML_HOME", "ML_AWAY", "SPREAD_HOME",
                "SPREAD_HOME_PRICE", "SPREAD_AWAY_PRICE", "TOTAL", "OVER", "UNDER"]


def _get(path, params):
    """Call the API. Returns (json, requests_remaining)."""
    key = get_secret("ODDS_API_KEY")
    if not key:
        raise RuntimeError("No ODDS_API_KEY found. Add it to your secrets.")
    resp = requests.get(
        f"{BASE_URL}{path}", params={"apiKey": key, **params}, timeout=20
    )
    if resp.status_code == 401:
        raise RuntimeError("The Odds API rejected the key (401). Check ODDS_API_KEY.")
    if resp.status_code == 429:
        raise RuntimeError("The Odds API quota or rate limit hit (429).")
    resp.raise_for_status()
    return resp.json(), resp.headers.get("x-requests-remaining")


def props_cache_key(sport, market):
    return f"odds_{sport}_{market}_{BOOKMAKER}"


def lines_cache_key(sport):
    return f"odds_{sport}_lines_{BOOKMAKER}"


def _in_window(start_iso, hours, grace_hours=4):
    """True if a game starting at start_iso (like '2026-10-26T01:15:00Z') is within the window.

    The window runs from `grace_hours` ago (so a game that just tipped off still counts) to `hours` ahead.
    """
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=grace_hours) < start < now + timedelta(hours=hours)


def _starts_soon(event, hours):
    return _in_window(event["commence_time"], hours)


def parse_event_props(event, odds, market="player_points"):
    """Turn one game's odds JSON into flat rows: one per player, book and line."""
    game = f"{event['away_team']} @ {event['home_team']}"
    rows = {}  # (player, book, line) -> row, so Over and Under land in the same row
    for book in odds.get("bookmakers", []):
        for m in book.get("markets", []):
            if m["key"] != market:
                continue
            for o in m["outcomes"]:
                row = rows.setdefault(
                    (o["description"], book["title"], o.get("point")),
                    {"PLAYER": o["description"], "GAME": game, "BOOK": book["title"],
                     "LINE": o.get("point"), "OVER": None, "UNDER": None,
                     "START": event["commence_time"]},
                )
                if o["name"] in ("Over", "Under"):
                    row[o["name"].upper()] = o["price"]
    return list(rows.values())


def get_todays_props(sport=NBA, market="player_points", hours=24):
    """Return (DataFrame of props for games in the next `hours`, requests_remaining).

    Cached for the day, separately for each sport and market.
    """
    cache_key = props_cache_key(sport, market)
    cached = cache.get(cache_key)
    if cached is None:
        events, remaining = _get(f"/sports/{sport}/events", {})  # listing is free
        rows = []
        for event in events:
            if not _starts_soon(event, hours):
                continue
            try:
                odds, remaining = _get(
                    f"/sports/{sport}/events/{event['id']}/odds",
                    {"bookmakers": BOOKMAKER, "markets": market, "oddsFormat": "american"},
                )
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in (404, 422):
                    continue  # no props posted for this game yet
                raise
            rows += parse_event_props(event, odds, market)
        cached = {"rows": rows, "remaining": remaining}
        cache.put(cache_key, cached)

    df = pd.DataFrame(cached["rows"], columns=COLUMNS)
    return df.sort_values(["PLAYER", "BOOK"]).reset_index(drop=True), cached["remaining"]


def parse_game_lines(event):
    """Turn one game from the /odds endpoint into a flat row of moneyline, spread and total.

    SPREAD_HOME is the home team's number (e.g. -3.5 means home is favored by 3.5); the away
    team's number is the opposite. Returns None if the book has no odds for the game yet.
    """
    books = event.get("bookmakers", [])
    if not books:
        return None
    home, away = event["home_team"], event["away_team"]
    row = dict.fromkeys(LINE_COLUMNS)
    row.update(GAME=f"{away} @ {home}", HOME=home, AWAY=away, START=event["commence_time"])
    for market in books[0]["markets"]:
        for o in market["outcomes"]:
            side = "HOME" if o["name"] == home else "AWAY"
            if market["key"] == "h2h":
                row[f"ML_{side}"] = o["price"]
            elif market["key"] == "spreads":
                row[f"SPREAD_{side}_PRICE"] = o["price"]
                if side == "HOME":
                    row["SPREAD_HOME"] = o["point"]
            elif market["key"] == "totals":
                row["TOTAL"] = o["point"]
                row[o["name"].upper()] = o["price"]
    return row


def get_game_lines(sport=NBA, hours=24, include_started=False):
    """Return (DataFrame of moneyline/spread/total per game, requests_remaining).

    One call covers every game, but it costs 1 request per market (3 here). Every upcoming game is
    cached for the day, and the time window is applied when reading, so asking for a different window
    never costs requests. Games that have already started are left out unless include_started is set:
    their pre-game lines can't be bet anymore.
    """
    cache_key = lines_cache_key(sport)
    cached = cache.get(cache_key)
    if cached is None:
        events, remaining = _get(
            f"/sports/{sport}/odds",
            {"bookmakers": BOOKMAKER, "markets": "h2h,spreads,totals", "oddsFormat": "american"},
        )
        rows = [parse_game_lines(e) for e in events]  # keep them all; the window is applied below
        cached = {"rows": [r for r in rows if r], "remaining": remaining}
        cache.put(cache_key, cached)

    grace = 4 if include_started else 0
    rows = [r for r in cached["rows"] if _in_window(r["START"], hours, grace)]
    df = pd.DataFrame(rows, columns=LINE_COLUMNS)
    return df.sort_values("START").reset_index(drop=True), cached["remaining"]


# --- Free calls: The Odds API doesn't charge for /sports or for listing a sport's events. ---

def requests_remaining():
    """Requests left this month as an int, or None if the API didn't say."""
    _, remaining = _get("/sports", {})
    return int(remaining) if remaining is not None else None


def count_games(sport, hours):
    """How many games start within `hours` (these are the games a props load would pay for)."""
    events, _ = _get(f"/sports/{sport}/events", {})
    return sum(_starts_soon(e, hours) for e in events)


def estimate_cost(sport, hours, market=None, count=count_games):
    """Requests a load would use right now. Pass market for props, or leave it out for game lines.

    It's 0 when today's result is already cached. Props cost 1 request per game; game lines
    cost 3 (one per market: moneyline, spread, total) however many games there are.
    `count` is the function that counts games; the app passes a cached one.
    """
    if market:
        if cache.get(props_cache_key(sport, market)) is not None:
            return 0
        return count(sport, hours)
    if cache.get(lines_cache_key(sport)) is not None:
        return 0
    return 3
