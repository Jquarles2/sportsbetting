"""Hit rates: how often a player went over a points line in recent games."""
import pandas as pd

WINDOWS = (5, 10, 20)
COLUMNS = ["SPLIT", "GAMES", "OVERS", "HIT_RATE"]


def _row(label, games, line):
    """One summary row. A game counts as an 'over' only if PTS is strictly above the line,
    so a push (PTS exactly equal to the line) is not an over."""
    overs = int((games["PTS"] > line).sum())
    rate = round(100 * overs / len(games), 1) if len(games) else None
    return {"SPLIT": label, "GAMES": len(games), "OVERS": overs, "HIT_RATE": rate}


def hit_rates(logs, line):
    """Summarize game logs (newest first, as from stats_nba.get_game_logs) against a line.

    Rows: last 5/10/20 games, then home and away games within the last 20.
    """
    last20 = logs.head(max(WINDOWS))
    rows = [_row(f"Last {n}", logs.head(n), line) for n in WINDOWS]
    for side in ("Home", "Away"):
        rows.append(_row(f"{side} (last 20)", last20[last20["HOME_AWAY"] == side], line))
    return pd.DataFrame(rows, columns=COLUMNS)


def rate(pts, line, n, side="Over"):
    """Percent of the last n games (pts is newest first) that went over (or under) the line.

    Uses fewer games if the player has fewer than n. None if there are no games.
    """
    games = pts[:n]
    if not games:
        return None
    hits = sum(p > line if side == "Over" else p < line for p in games)
    return round(100 * hits / len(games), 1)


def props_table(scan, side="Over"):
    """One row per prop with hit rates over the last 5, 10 and 20 games."""
    rows = [
        {"PLAYER": r.PLAYER, "GAME": r.GAME, "LINE": r.LINE,
         **{f"L{n}": rate(r.VALUES, r.LINE, n, side) for n in WINDOWS}}
        for r in scan.itertuples()
    ]
    return pd.DataFrame(rows, columns=["PLAYER", "GAME", "LINE", "L5", "L10", "L20"])
