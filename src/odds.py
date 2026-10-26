"""NBA player-points prop lines from The Odds API (https://the-odds-api.com).

The free plan is ~500 requests/month. Listing games is free, but each game's props cost
1 request, so we only fetch when asked and cache the result for the day.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from src import cache
from src.config import get_secret

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "basketball_nba"
MARKET = "player_points"
CACHE_KEY = "odds_nba_player_points"
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


def _starts_within_24h(event):
    start = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=4) < start < now + timedelta(hours=24)


def parse_event_props(event, odds):
    """Turn one game's odds JSON into flat rows: one per player, book and line."""
    game = f"{event['away_team']} @ {event['home_team']}"
    rows = {}  # (player, book, line) -> row, so Over and Under land in the same row
    for book in odds.get("bookmakers", []):
        for market in book.get("markets", []):
            if market["key"] != MARKET:
                continue
            for o in market["outcomes"]:
                row = rows.setdefault(
                    (o["description"], book["title"], o.get("point")),
                    {"PLAYER": o["description"], "GAME": game, "BOOK": book["title"],
                     "LINE": o.get("point"), "OVER": None, "UNDER": None,
                     "START": event["commence_time"]},
                )
                if o["name"] in ("Over", "Under"):
                    row[o["name"].upper()] = o["price"]
    return list(rows.values())


def get_todays_props():
    """Return (DataFrame of today's props, requests_remaining). Cached for the day."""
    cached = cache.get(CACHE_KEY)
    if cached is None:
        events, remaining = _get(f"/sports/{SPORT}/events", {})  # listing is free
        rows = []
        for event in filter(_starts_within_24h, events):
            try:
                odds, remaining = _get(
                    f"/sports/{SPORT}/events/{event['id']}/odds",
                    {"regions": "us", "markets": MARKET, "oddsFormat": "american"},
                )
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in (404, 422):
                    continue  # no props posted for this game yet
                raise
            rows += parse_event_props(event, odds)
        cached = {"rows": rows, "remaining": remaining}
        cache.put(CACHE_KEY, cached)

    df = pd.DataFrame(cached["rows"], columns=COLUMNS)
    return df.sort_values(["PLAYER", "BOOK"]).reset_index(drop=True), cached["remaining"]
