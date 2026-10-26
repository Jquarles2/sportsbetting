"""Hit rates: how often a player went over a points line in recent games."""
import pandas as pd

WINDOWS = (5, 10, 20)
COLUMNS = ["SPLIT", "GAMES", "OVERS", "HIT_RATE"]


def _row(label, games, line, column):
    """One summary row. A game counts as an 'over' only if the stat is strictly above the line,
    so a push (exactly equal to the line) is not an over."""
    overs = int((games[column] > line).sum())
    rate = round(100 * overs / len(games), 1) if len(games) else None
    return {"SPLIT": label, "GAMES": len(games), "OVERS": overs, "HIT_RATE": rate}


def hit_rates(logs, line, column="PTS"):
    """Summarize game logs (newest first, as from stats_nba.get_game_logs) against a line.

    column is which stat to use: PTS, REB, AST, FG3M or PRA.

    Rows: last 5/10/20 games, then home and away games within the last 20.
    """
    last20 = logs.head(max(WINDOWS))
    rows = [_row(f"Last {n}", logs.head(n), line, column) for n in WINDOWS]
    for side in ("Home", "Away"):
        rows.append(_row(f"{side} (last 20)", last20[last20["HOME_AWAY"] == side], line, column))
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


def _pct(hits, games):
    return round(100 * hits / len(games), 1) if games else None


def win_rate(games, n):
    """Percent of a team's last n games that were wins. games are {'for', 'against'} newest first."""
    last = games[:n]
    return _pct(sum(g["for"] > g["against"] for g in last), last)


def cover_rate(games, spread, n):
    """Percent of the last n games where the team would have covered today's spread.

    spread is this team's number: -3.5 means favored by 3.5, so they must win by 4 or more.
    A push (margin exactly equals the spread) isn't a cover.
    """
    last = games[:n]
    return _pct(sum(g["for"] - g["against"] + spread > 0 for g in last), last)


def over_rate(games, total, n):
    """Percent of the last n games whose combined score went over today's total."""
    last = games[:n]
    return _pct(sum(g["for"] + g["against"] > total for g in last), last)


def sides_table(lines, form):
    """Two rows per game (one per team): moneyline, spread, and recent win and cover rates.

    form maps team name -> its recent games (or None if we couldn't load them).
    """
    rows = []
    for g in lines.itertuples():
        for team, opp, ml, spread in (
            (g.HOME, g.AWAY, g.ML_HOME, g.SPREAD_HOME),
            (g.AWAY, g.HOME, g.ML_AWAY, None if pd.isna(g.SPREAD_HOME) else -g.SPREAD_HOME),
        ):
            games = form.get(team) or []
            has_spread = spread is not None and not pd.isna(spread)
            rows.append({
                "TEAM": team, "OPP": opp, "ML": ml, "SPREAD": spread,
                "WIN_L5": win_rate(games, 5), "WIN_L10": win_rate(games, 10),
                "COVER_L5": cover_rate(games, spread, 5) if has_spread else None,
                "COVER_L10": cover_rate(games, spread, 10) if has_spread else None,
            })
    return pd.DataFrame(rows, columns=["TEAM", "OPP", "ML", "SPREAD", "WIN_L5", "WIN_L10",
                                       "COVER_L5", "COVER_L10"])


def totals_table(lines, form):
    """One row per game: the total, how often each team's recent games went over it, and the
    average combined score of both teams' last 10 games."""
    rows = []
    for g in lines.itertuples():
        home, away = form.get(g.HOME) or [], form.get(g.AWAY) or []
        has_total = not pd.isna(g.TOTAL)
        combined = [x["for"] + x["against"] for x in home[:10] + away[:10]]
        rows.append({
            "GAME": g.GAME, "TOTAL": g.TOTAL,
            "HOME_OVER_L10": over_rate(home, g.TOTAL, 10) if has_total else None,
            "AWAY_OVER_L10": over_rate(away, g.TOTAL, 10) if has_total else None,
            "AVG_COMBINED": round(sum(combined) / len(combined), 1) if combined else None,
        })
    return pd.DataFrame(rows, columns=["GAME", "TOTAL", "HOME_OVER_L10", "AWAY_OVER_L10", "AVG_COMBINED"])
