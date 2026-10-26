"""NBA player game logs via nba_api (the public stats.nba.com wrapper)."""
import pandas as pd
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players

from src import cache

# Columns worth showing; the API returns many more.
LOG_COLUMNS = ["GAME_DATE", "MATCHUP", "WL", "MIN", "PTS", "REB", "AST", "FG3M"]


def find_player(name):
    """Return the best-matching player dict ({'id', 'full_name', ...}) or None."""
    matches = players.find_players_by_full_name(name)
    if not matches:
        return None
    # Prefer currently active players if several share a name.
    matches.sort(key=lambda p: not p["is_active"])
    return matches[0]


def _fetch_log(player_id):
    """Call the NBA API. Returns the full season log as a list of row dicts."""
    log = playergamelog.PlayerGameLog(player_id=player_id, timeout=30)
    return log.get_data_frames()[0].to_dict("records")


def get_game_logs(name, n=10):
    """Last n games for a player (newest first) as a DataFrame.

    Returns None if the player isn't found. Raises on API errors.
    """
    player = find_player(name)
    if player is None:
        return None

    key = f"nba_gamelog_{player['id']}"
    rows = cache.get(key)
    if rows is None:
        rows = _fetch_log(player["id"])
        cache.put(key, rows)

    if not rows:  # e.g. very early in a season, before any games are played
        return pd.DataFrame(columns=LOG_COLUMNS)

    # The API already returns newest game first.
    return pd.DataFrame(rows).head(n)[LOG_COLUMNS].reset_index(drop=True)
