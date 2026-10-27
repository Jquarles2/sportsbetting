"""NFL player game logs from nflverse's public weekly player stats (https://github.com/nflverse).

This is the same data the nfl_data_py package serves. We download the CSVs directly because
nfl_data_py is no longer updated and pins an old pandas that would break the rest of the app.
No API key needed.
"""
import io
import re
import time
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
KEEP = ["player_display_name", "season", "week", "season_type", "team", "opponent_team",
        "passing_yards", "rushing_yards", "receiving_yards", "receptions"]
INJURY_COLUMNS = ["week", "team", "position", "full_name", "report_status",
                  "report_primary_injury", "practice_status"]
INJURIES_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
                "injuries/injuries_{season}.csv")
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
    df = pd.read_csv(io.StringIO(resp.text), usecols=["season", "week", "gameday", "home_team", "away_team",
                                                      "home_score", "away_score"])
    df = df[df["season"] >= _current_season() - 1].dropna(subset=["home_score", "away_score"])
    df["home"] = df["home_team"].map(names)
    df["away"] = df["away_team"].map(names)
    return df[["season", "week", "gameday", "home", "away", "home_score", "away_score"]].to_dict("records")


@lru_cache(maxsize=2)
def _load_results(day):
    rows = cache.get("nfl_results")
    if rows is None:
        rows = _download_results()
        cache.put("nfl_results", rows)
    return pd.DataFrame(rows, columns=["season", "week", "gameday", "home", "away", "home_score", "away_score"])


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


def _team_names():
    """Abbreviation -> full team name ({'KC': 'Kansas City Chiefs', ...}), cached for the day."""
    names = cache.get("nfl_team_names")
    if names is None:
        resp = requests.get(TEAMS_URL, timeout=60)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        names = dict(zip(df["team_abbr"], df["team_name"]))
        cache.put("nfl_team_names", names)
    return names


def _download_injuries(season):
    resp = requests.get(INJURIES_URL.format(season=season), timeout=60)
    if resp.status_code == 404:  # no report yet (offseason / before week 1)
        return []
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text), usecols=INJURY_COLUMNS).to_dict("records")


@lru_cache(maxsize=2)
def _load_injuries(day):
    """The latest week's injury report as a DataFrame (empty if there isn't one)."""
    season = _current_season()
    rows = cache.get(f"nfl_injuries_{season}")
    if rows is None:
        rows = _download_injuries(season)
        cache.put(f"nfl_injuries_{season}", rows)
    df = pd.DataFrame(rows, columns=INJURY_COLUMNS)
    df = df[df["week"] == df["week"].max()] if len(df) else df
    df = df.assign(KEY=df["full_name"].map(_normalize))
    return df


def get_injury(name):
    """The player's status on the latest weekly injury report.

    Returns None if there's no report or the player isn't on it (we can't say either way).
    Otherwise a dict with 'week', 'status' and 'injury'; status is None when the player is
    listed as healthy (nflverse lists most players, so being on the report isn't the same as
    being hurt). A game status like Questionable wins over the practice status, and practice
    only counts if they were limited or missed it.
    """
    df = _load_injuries(date.today().isoformat())
    if df.empty:
        return None
    week = int(df["week"].iloc[0])
    rows = df[df["KEY"] == _normalize(name)]
    if rows.empty:
        return None
    row = rows.iloc[0]
    status, practice = row["report_status"], row["practice_status"]
    if pd.isna(status) and isinstance(practice, str) and not practice.startswith("Full"):
        status = practice
    injury = row["report_primary_injury"]
    return {"week": week, "status": None if pd.isna(status) else status,
            "injury": None if pd.isna(injury) else injury}


def get_matchup(name, market, game):
    """How much of the market's stat the player's opponent allows, this season.

    game looks like 'Denver Broncos @ Kansas City Chiefs'. Returns None if we can't tell who
    the player's opponent is. Otherwise {'opponent', 'per_game', 'rank', 'teams'}, where rank 1
    means the opponent allows the MOST of that stat per game (the friendliest matchup).
    """
    column = MARKETS[market][0]
    table = _load_table(date.today().isoformat())
    table = table[table["season"] == table["season"].max()]
    names = _team_names()
    mine = table[table["KEY"] == _normalize(name)].sort_values("week", ascending=False)
    if mine.empty:
        return None
    my_team = names.get(mine["team"].iloc[0])
    teams_in_game = game.split(" @ ")
    if my_team not in teams_in_game or len(teams_in_game) != 2:
        return None
    opponent = next(t for t in teams_in_game if t != my_team)

    # Each row is one player's game. Add them up per defense per week, then average the weeks.
    table = table.assign(DEFENSE=table["opponent_team"].map(names))
    per_game = table.groupby(["DEFENSE", "week"])[column].sum().groupby("DEFENSE").mean()
    if opponent not in per_game:
        return None
    allowed = float(per_game[opponent])
    rank = int((per_game > allowed).sum()) + 1
    return {"opponent": opponent, "per_game": round(allowed, 1), "rank": rank, "teams": len(per_game)}


KEY_POSITIONS = ("QB", "RB", "WR", "TE")  # the players who most change a team's scoring
GAME_STATUSES = {"Out": 0, "Doubtful": 1, "Questionable": 2}  # lower = more serious


def get_team_injuries(team_name):
    """Key players (QB/RB/WR/TE) on a team with a game status of Out, Doubtful or Questionable.

    Returns a list of {'name', 'position', 'status', 'injury'}, most serious first. The list is
    empty if there's no report or nobody is listed.
    """
    df = _load_injuries(date.today().isoformat())
    if df.empty:
        return []
    names = _team_names()
    team = df[df["team"].map(lambda abbr: names.get(abbr)) == team_name]
    team = team[team["position"].isin(KEY_POSITIONS) & team["report_status"].isin(GAME_STATUSES)]
    out = [{"name": r.full_name, "position": r.position, "status": r.report_status,
            "injury": None if pd.isna(r.report_primary_injury) else r.report_primary_injury}
           for r in team.itertuples()]
    return sorted(out, key=lambda p: (GAME_STATUSES[p["status"]], KEY_POSITIONS.index(p["position"])))


def get_player_team(name):
    """The full name of the team a player most recently played for, or None if unknown."""
    table = _load_table(date.today().isoformat())
    rows = table[table["KEY"] == _normalize(name)].sort_values(["season", "week"], ascending=False)
    if rows.empty:
        return None
    return _team_names().get(rows["team"].iloc[0])


RESULTS_REFRESH_SECONDS = 1800  # re-download the scores at most every 30 minutes
_results_refreshed_at = None


def _refresh_results():
    """Download the scores again, even though today's copy is cached.

    The scores file is cached for the whole day, so a copy saved Sunday morning doesn't have Sunday's games.
    When grading can't find a finished game we fetch once more, but not more often than every 30 minutes.
    Returns True if it downloaded.
    """
    global _results_refreshed_at
    if _results_refreshed_at and time.monotonic() - _results_refreshed_at < RESULTS_REFRESH_SECONDS:
        return False
    _results_refreshed_at = time.monotonic()
    cache.put("nfl_results", _download_results())
    _load_results.cache_clear()  # forget the in-memory copy too
    return True


def _find_game(home, away, start):
    """The finished game between these teams within 2 days of start, or None (refreshes the scores once)."""
    def look():
        df = _load_results(date.today().isoformat())
        games = df[(df["home"] == home) & (df["away"] == away)]
        return next((g for g in games.itertuples()
                     if abs((pd.Timestamp(g.gameday).date() - start.date()).days) <= 2), None)

    game = look()
    if game is None and _refresh_results():  # maybe today's copy was saved before this game finished
        game = look()
    return game


def get_final(home, away, start):
    """Final score (home_score, away_score) of a finished game, or None if not final or not found.

    start is the kickoff as a datetime; the game is matched by teams and a game day within 2 days.
    """
    g = _find_game(home, away, start)
    return None if g is None else (int(g.home_score), int(g.away_score))


DID_NOT_PLAY = "dnp"  # a finished game where the player has no stat line (sportsbooks void these props)


def get_player_stat(name, market, home, away, start):
    """A player's value of the market's stat in one finished game.

    Returns an int, DID_NOT_PLAY if the game's stats are published but he isn't in them, or None if the
    game's stats aren't published yet (nflverse posts them a day or so after the game, so we wait).
    """
    column = MARKETS[market][0]
    today = date.today().isoformat()
    game = _find_game(home, away, start)
    if game is None:
        return None
    abbrs = {abbr for abbr, team in _team_names().items() if team in (home, away)}
    table = _load_table(today)
    published = table[(table["season"] == game.season) & (table["week"] == game.week) & table["team"].isin(abbrs)]
    if published.empty:
        return None
    mine = published[published["KEY"] == _normalize(name)]
    return DID_NOT_PLAY if mine.empty else int(mine[column].iloc[0])
