"""NFL player game logs from nflverse's public weekly player stats (https://github.com/nflverse).

This is the same data the nfl_data_py package serves. We download the CSVs directly because
nfl_data_py is no longer updated and pins an old pandas that would break the rest of the app.
No API key needed.
"""
import io
import re
from datetime import date
from functools import lru_cache

import pandas as pd
import requests

from src import cache

URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
       "stats_player/stats_player_week_{season}.csv")
# The Odds API market -> (column in the weekly data, label for the UI)
MARKETS = {
    "player_pass_yds": ("passing_yards", "passing yards"),
    "player_rush_yds": ("rushing_yards", "rushing yards"),
    "player_reception_yds": ("receiving_yards", "receiving yards"),
    "player_receptions": ("receptions", "receptions"),
}
KEEP = ["player_display_name", "season", "week", "season_type", "passing_yards",
        "rushing_yards", "receiving_yards", "receptions"]
GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
TEAMS_URL = "https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.csv"
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _current_season():
    """The NFL season is named for the year it starts; March-August still counts as last season."""
    today = date.today()
    return today.year if today.month >= 9 else today.year - 1


def _normalize(name):
    """'Marvin Harrison Jr.' and 'marvin harrison' should match, so drop punctuation and suffixes."""
    words = re.sub(r"[^a-z ]", "", name.lower().replace("-", " ")).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def _download_season(season):
    """One season of weekly stats as a list of dicts (regular season + playoffs, slimmed down)."""
    resp = requests.get(URL.format(season=season), timeout=60)
    if resp.status_code == 404:  # season not published yet (offseason / before week 1)
        return []
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), usecols=KEEP)
    df = df[df["season_type"].isin(["REG", "POST"])].dropna(subset=["player_display_name"])
    df = df.fillna(0)  # a stat that's blank means 0 (e.g. a QB with no receptions)
    return df.to_dict("records")


def _season_rows(season):
    rows = cache.get(f"nfl_weekly_{season}")
    if rows is None:
        rows = _download_season(season)
        cache.put(f"nfl_weekly_{season}", rows)
    return rows


@lru_cache(maxsize=2)
def _load_table(day):
    """This season plus last season, as one table with a lookup column. `day` only keys the
    in-memory cache so a long-running app reloads each morning."""
    season = _current_season()
    rows = _season_rows(season) + _season_rows(season - 1)
    df = pd.DataFrame(rows, columns=KEEP)
    df["KEY"] = df["player_display_name"].map(_normalize)
    return df.sort_values(["season", "week"], ascending=False).reset_index(drop=True)


def get_recent_values(name, market, n=20):
    """A player's last n values of the market's stat, newest first, or None if not found."""
    column = MARKETS[market][0]
    table = _load_table(date.today().isoformat())
    rows = table[table["KEY"] == _normalize(name)]
    if rows.empty:
        return None
    return [int(v) for v in rows[column].head(n)]


def _download_results():
    """Every finished NFL game since last season as dicts: season, week, home, away, scores.

    nflverse's schedule uses abbreviations like 'KC', so we swap them for full team names
    to match The Odds API.
    """
    names = pd.read_csv(io.StringIO(requests.get(TEAMS_URL, timeout=60).text))
    names = dict(zip(names["team_abbr"], names["team_name"]))
    resp = requests.get(GAMES_URL, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), usecols=["season", "week", "home_team", "away_team",
                                                      "home_score", "away_score"])
    df = df[df["season"] >= _current_season() - 1].dropna(subset=["home_score", "away_score"])
    df["home"] = df["home_team"].map(names)
    df["away"] = df["away_team"].map(names)
    return df[["season", "week", "home", "away", "home_score", "away_score"]].to_dict("records")


@lru_cache(maxsize=2)
def _load_results(day):
    rows = cache.get("nfl_results")
    if rows is None:
        rows = _download_results()
        cache.put("nfl_results", rows)
    return pd.DataFrame(rows, columns=["season", "week", "home", "away", "home_score", "away_score"])


def get_team_games(team_name, n=20):
    """A team's last n finished games (newest first) as {'for', 'against'} point totals.

    team_name is the full name, like 'Kansas City Chiefs'. Returns None if the team isn't found.
    """
    df = _load_results(date.today().isoformat())
    df = df[(df["home"] == team_name) | (df["away"] == team_name)]
    if df.empty:
        return None
    df = df.sort_values(["season", "week"], ascending=False).head(n)
    at_home = df["home"] == team_name
    mine = df["home_score"].where(at_home, df["away_score"])
    theirs = df["away_score"].where(at_home, df["home_score"])
    return [{"for": int(m), "against": int(t)} for m, t in zip(mine, theirs)]
