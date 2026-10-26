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
