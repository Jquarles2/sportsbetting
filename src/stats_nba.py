"""NBA player game logs via the balldontlie API (https://www.balldontlie.io).

nba_api (stats.nba.com) blocks cloud hosts like Streamlit Community Cloud, so we use
balldontlie instead. It needs a free API key, stored as BALLDONTLIE_API_KEY in
.streamlit/secrets.toml locally, or in the app's Secrets settings on Streamlit Cloud.
"""
import threading
import time
from datetime import date, timedelta

import pandas as pd
import requests

from src import cache
from src.config import get_secret

BASE_URL = "https://api.balldontlie.io/v1"
# Columns we show, in order.
LOG_COLUMNS = ["GAME_DATE", "HOME_AWAY", "MIN", "PTS", "REB", "AST", "FG3M", "PRA"]
# The Odds API market -> (column in the game logs, label for the UI)
MARKETS = {
    "player_points": ("PTS", "points"),
    "player_rebounds": ("REB", "rebounds"),
    "player_assists": ("AST", "assists"),
    "player_threes": ("FG3M", "threes made"),
    "player_points_rebounds_assists": ("PRA", "points + rebounds + assists"),
}
# The $10 plan allows 60 requests a minute. Waiting 1.1 seconds between calls stays just under it.
MIN_SECONDS_BETWEEN_CALLS = 1.1
_pace_lock = threading.Lock()  # Streamlit runs each visitor in their own thread
_last_call = 0.0


def get_api_key():
    return get_secret("BALLDONTLIE_API_KEY")


def _wait_for_turn():
    """Sleep just long enough that all our calls together stay under the plan's rate limit."""
    global _last_call
    with _pace_lock:
        wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _get(path, params):
    """Call the API and return the parsed JSON. Raises a readable error on failure.

    Calls are paced to stay under the rate limit, and a 429 (too many requests) is retried
    after a short wait.
    """
    key = get_api_key()
    if not key:
        raise RuntimeError("No BALLDONTLIE_API_KEY found. Add it to your secrets.")
    for attempt in range(4):
        _wait_for_turn()
        resp = requests.get(
            f"{BASE_URL}{path}", params=params, headers={"Authorization": key}, timeout=20
        )
        if resp.status_code != 429:
            break
        time.sleep(10 * (attempt + 1))  # 10s, 20s, 30s, then give up
    if resp.status_code == 401:
        raise RuntimeError(
            f"balldontlie rejected the {path} request (401). For /players that means a bad "
            "API key; for /stats it usually means your plan doesn't include game stats."
        )
    if resp.status_code == 429:
        raise RuntimeError("balldontlie rate limit still hit after retrying. Wait a minute and try again.")
    resp.raise_for_status()
    return resp.json()


def find_player(name):
    """Return the best-matching player dict ({'id', 'first_name', 'last_name', ...}) or None."""
    words = name.strip().lower().split()
    if not words:
        return None
    key = "bdl_player_" + " ".join(words)  # a player's id never changes, so don't look them up twice
    cached = cache.get(key)
    if cached is not None:
        return cached
    # The API's search matches single words well, so search the last word, then filter.
    data = _get("/players", {"search": words[-1], "per_page": 100})["data"]
    matches = [
        p for p in data
        if all(w in f"{p['first_name']} {p['last_name']}".lower() for w in words)
    ]
    if matches:
        cache.put(key, matches[0])
    return matches[0] if matches else None


def _current_season():
    """balldontlie names a season by the year it starts (2025 = the 2025-26 season)."""
    today = date.today()
    return today.year if today.month >= 10 else today.year - 1


def _fetch_season_stats(player_id, season):
    """All of a player's game stat lines for one season."""
    params = {"player_ids[]": player_id, "seasons[]": season, "per_page": 100}
    return _get("/stats", params)["data"]


def _to_row(stat):
    game = stat["game"]
    home = stat["team"]["id"] == game["home_team_id"]
    return {
        "GAME_DATE": game["date"][:10],
        "HOME_AWAY": "Home" if home else "Away",
        "MIN": stat["min"],
        "PTS": stat["pts"],
        "REB": stat["reb"],
        "AST": stat["ast"],
        "FG3M": stat["fg3m"],
    }


def get_game_logs(name, n=10):
    """Last n games for a player (newest first) as a DataFrame.

    Returns None if the player isn't found. Raises on API errors.
    """
    player = find_player(name)
    if player is None:
        return None

    key = f"bdl_gamelog_{player['id']}"
    rows = cache.get(key)
    if rows is None:
        season = _current_season()
        stats = _fetch_season_stats(player["id"], season)
        if len(stats) < 20:  # early in a season, so also pull last season (20 = most we ever show)
            stats += _fetch_season_stats(player["id"], season - 1)
        rows = [_to_row(s) for s in stats if s.get("min")]  # skip games they didn't play
        rows.sort(key=lambda r: r["GAME_DATE"], reverse=True)
        cache.put(key, rows)

    if not rows:
        return pd.DataFrame(columns=LOG_COLUMNS)
    df = pd.DataFrame(rows).head(n).reset_index(drop=True)
    df["PRA"] = df["PTS"] + df["REB"] + df["AST"]  # points + rebounds + assists
    return df[LOG_COLUMNS]


def get_recent_values(name, market, n=20):
    """A player's last n values of the market's stat, newest first, or None if not found.

    All stats come from the same cached game logs, so switching from points to rebounds
    doesn't cost any extra balldontlie requests.
    """
    column = MARKETS[market][0]
    logs = get_game_logs(name, n=n)
    return None if logs is None else [int(v) for v in logs[column]]


def _teams():
    """All NBA teams as dicts with 'id' and 'full_name' (cached for the day)."""
    teams = cache.get("bdl_teams")
    if teams is None:
        teams = _get("/teams", {})["data"]
        cache.put("bdl_teams", teams)
    return teams


def _fetch_team_games(team_id, season):
    """Finished games for one team and season as {'date', 'for', 'against'} dicts."""
    games, cursor = [], None
    for _ in range(3):  # a season can run past one page of 100 games with the playoffs
        params = {"team_ids[]": team_id, "seasons[]": season, "per_page": 100}
        if cursor:
            params["cursor"] = cursor
        data = _get("/games", params)
        for g in data["data"]:
            if g.get("status") != "Final":
                continue
            home = g["home_team"]["id"] == team_id
            mine, theirs = g["home_team_score"], g["visitor_team_score"]
            games.append({"date": g["date"][:10],
                          "for": mine if home else theirs, "against": theirs if home else mine})
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
    return games


def get_team_games(team_name, n=20):
    """A team's last n finished games (newest first) as {'for', 'against'} point totals.

    team_name is the full name, like 'Boston Celtics'. Returns None if the team isn't found.
    """
    team = next((t for t in _teams() if t["full_name"].lower() == team_name.lower()), None)
    if team is None:
        return None
    key = f"bdl_teamgames_{team['id']}"
    games = cache.get(key)
    if games is None:
        season = _current_season()
        games = _fetch_team_games(team["id"], season)
        if len(games) < n:  # early in a season, so also pull last season
            games += _fetch_team_games(team["id"], season - 1)
        games.sort(key=lambda g: g["date"], reverse=True)
        cache.put(key, games)
    return [{"for": g["for"], "against": g["against"]} for g in games[:n]]


_injuries_failed_at = None
INJURY_RETRY_SECONDS = 300  # after a failed call, don't try again for 5 minutes


def _injuries():
    """Everyone on balldontlie's injury list as {'name', 'status', 'detail'} dicts, cached for the day.

    If the call fails (say the plan doesn't include injuries), later calls fail instantly for a few minutes
    instead of each waiting for another doomed request.
    """
    global _injuries_failed_at
    rows = cache.get("bdl_injuries")
    if rows is None and _injuries_failed_at and time.monotonic() - _injuries_failed_at < INJURY_RETRY_SECONDS:
        raise RuntimeError("balldontlie injuries unavailable (a recent request failed)")
    if rows is None:
        try:
            rows = _fetch_injuries()
        except Exception:
            _injuries_failed_at = time.monotonic()
            raise
        cache.put("bdl_injuries", rows)
    return rows


def _fetch_injuries():
    """Ask balldontlie for the injury list (follows its pages) as {'name', 'status', 'detail'} dicts."""
    rows, cursor = [], None
    for _ in range(5):
        params = {"per_page": 100}
        if cursor:
            params["cursor"] = cursor
        data = _get("/player_injuries", params)
        for item in data["data"]:
            player = item.get("player") or {}
            rows.append({
                "name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                "status": item.get("status"),
                "detail": item.get("description") or item.get("comment"),
            })
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
    return rows


def get_injury(name):
    """The player's entry on the injury list as {'status', 'injury'}, or None if they aren't on it.

    The list only has hurt players, so unlike the NFL report, being absent means healthy. Raises
    if the API call fails (for example if the plan doesn't include injuries).
    """
    wanted = " ".join(name.lower().split())
    for row in _injuries():
        if " ".join(row["name"].lower().split()) == wanted:
            return {"status": row["status"], "injury": row["detail"]}
    return None


def get_final(home, away, start):
    """Final score (home_score, away_score) of a finished NBA game, or None if not final or not found.

    start is the tip-off as a datetime. NBA dates are in US time while ours are UTC, so we look at
    the day before as well.
    """
    dates = [(start - timedelta(days=d)).date().isoformat() for d in (0, 1)]
    data = _get("/games", {"dates[]": dates, "per_page": 100})["data"]
    for g in data:
        if (g.get("status") == "Final" and g["home_team"]["full_name"] == home
                and g["visitor_team"]["full_name"] == away):
            return g["home_team_score"], g["visitor_team_score"]
    return None


DID_NOT_PLAY = "dnp"  # a finished game where the player didn't play (sportsbooks void these props)


def get_player_stat(name, market, home, away, start):
    """A player's value of the market's stat in one finished NBA game.

    Returns an int, DID_NOT_PLAY if there's no stat line with minutes for him in that game, or None if
    we can't identify the player or the teams (so the leg stays waiting instead of being voided wrongly).
    """
    column = MARKETS[market][0]
    player = find_player(name)
    team_ids = {t["full_name"]: t["id"] for t in _teams()}
    if player is None or home not in team_ids or away not in team_ids:
        return None
    dates = [(start - timedelta(days=d)).date().isoformat() for d in (0, 1)]
    data = _get("/stats", {"player_ids[]": player["id"], "dates[]": dates, "per_page": 100})["data"]
    for stat in data:
        game = stat["game"]
        if game["home_team_id"] == team_ids[home] and game["visitor_team_id"] == team_ids[away]:
            if not stat.get("min"):
                return DID_NOT_PLAY
            row = _to_row(stat)
            row["PRA"] = row["PTS"] + row["REB"] + row["AST"]
            return int(row[column])
    return DID_NOT_PLAY
