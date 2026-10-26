"""NBA player game logs via the balldontlie API (https://www.balldontlie.io).

nba_api (stats.nba.com) blocks cloud hosts like Streamlit Community Cloud, so we use
balldontlie instead. It needs a free API key, stored as BALLDONTLIE_API_KEY in
.streamlit/secrets.toml locally, or in the app's Secrets settings on Streamlit Cloud.
"""
from datetime import date

import pandas as pd
import requests

from src import cache
from src.config import get_secret

BASE_URL = "https://api.balldontlie.io/v1"
# Columns we show, in order.
LOG_COLUMNS = ["GAME_DATE", "HOME_AWAY", "MIN", "PTS", "REB", "AST", "FG3M"]


def get_api_key():
    return get_secret("BALLDONTLIE_API_KEY")


def _get(path, params):
    """Call the API and return the parsed JSON. Raises a readable error on failure."""
    key = get_api_key()
    if not key:
        raise RuntimeError("No BALLDONTLIE_API_KEY found. Add it to your secrets.")
    resp = requests.get(
        f"{BASE_URL}{path}", params=params, headers={"Authorization": key}, timeout=20
    )
    if resp.status_code == 401:
        raise RuntimeError(
            f"balldontlie rejected the {path} request (401). For /players that means a bad "
            "API key; for /stats it usually means your plan doesn't include game stats."
        )
    if resp.status_code == 429:
        raise RuntimeError("balldontlie rate limit hit (free plan is 5 requests/minute). Wait a minute.")
    resp.raise_for_status()
    return resp.json()


def find_player(name):
    """Return the best-matching player dict ({'id', 'first_name', 'last_name', ...}) or None."""
    words = name.strip().lower().split()
    if not words:
        return None
    # The API's search matches single words well, so search the last word, then filter.
    data = _get("/players", {"search": words[-1], "per_page": 100})["data"]
    matches = [
        p for p in data
        if all(w in f"{p['first_name']} {p['last_name']}".lower() for w in words)
    ]
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
        if len(stats) < n:  # early in a season, so also pull last season
            stats += _fetch_season_stats(player["id"], season - 1)
        rows = [_to_row(s) for s in stats if s.get("min")]  # skip games they didn't play
        rows.sort(key=lambda r: r["GAME_DATE"], reverse=True)
        cache.put(key, rows)

    if not rows:
        return pd.DataFrame(columns=LOG_COLUMNS)
    return pd.DataFrame(rows).head(n)[LOG_COLUMNS].reset_index(drop=True)


def get_recent_points(name, n=20):
    """A player's last n point totals, newest first, or None if the player isn't found."""
    logs = get_game_logs(name, n=n)
    return None if logs is None else [int(p) for p in logs["PTS"]]
