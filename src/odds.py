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


def _starts_soon(event, hours):
    start = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=4) < start < now + timedelta(hours=hours)


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
    cache_key = f"odds_{sport}_{market}_{BOOKMAKER}"
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
