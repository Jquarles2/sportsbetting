"""Find props where the player cleared the line in all of their last 5 games."""
import time

import pandas as pd

from src import stats_nba

COLUMNS = ["PLAYER", "GAME", "SIDE", "LINE", "LAST_5", "CUSHION"]


def five_of_five(player, game, line, pts):
    """Return a pick dict if the last 5 games were all over (or all under) the line, else None.

    pts is newest first. CUSHION is the closest any game came to the line, so a bigger
    number means a safer pick. A push (pts == line) breaks the streak.
    """
    if len(pts) < 5:
        return None
    last5 = pts[:5]
    if all(p > line for p in last5):
        side, cushion = "Over", min(last5) - line
    elif all(p < line for p in last5):
        side, cushion = "Under", line - max(last5)
    else:
        return None
    return {"PLAYER": player, "GAME": game, "SIDE": side, "LINE": line,
            "LAST_5": ", ".join(str(p) for p in last5), "CUSHION": cushion}


def find_picks(props, progress=None, pause=1.0):
    """Scan every player in today's props (one median line each) and return 5/5 picks.

    progress(done, total) is called after each player, so the app can show a progress bar.
    pause is seconds to wait between players to stay under balldontlie's rate limit.
    Players that fail to load are skipped and listed in the returned errors.
    """
    summary = props.groupby("PLAYER").agg(GAME=("GAME", "first"), LINE=("LINE", "median"))
    summary = summary.dropna(subset=["LINE"])
    picks, errors = [], []
    for i, (player, row) in enumerate(summary.iterrows(), start=1):
        try:
            logs = stats_nba.get_game_logs(player, n=5)
            if logs is not None:
                pick = five_of_five(player, row["GAME"], row["LINE"], list(logs["PTS"]))
                if pick:
                    picks.append(pick)
        except Exception as e:
            errors.append(f"{player}: {e}")
        if progress:
            progress(i, len(summary))
        time.sleep(pause)
    df = pd.DataFrame(picks, columns=COLUMNS)
    return df.sort_values("CUSHION", ascending=False).reset_index(drop=True), errors
