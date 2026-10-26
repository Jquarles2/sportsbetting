"""Scan the teams in today's game lines so we can compare their recent results to the lines."""
import time


def scan_teams(lines, get_team_games, progress=None, pause=1.0):
    """Fetch recent results for every team in the game lines.

    get_team_games(team_name) returns the team's recent {'for', 'against'} games, or None.
    Returns (dict of team name -> games, errors). Teams that fail are skipped and listed in errors.
    """
    teams = sorted(set(lines["HOME"]) | set(lines["AWAY"]))
    form, errors = {}, []
    for i, team in enumerate(teams, start=1):
        try:
            games = get_team_games(team)
            if games:
                form[team] = games
        except Exception as e:
            errors.append(f"{team}: {e}")
        if progress:
            progress(i, len(teams))
        time.sleep(pause)
    return form, errors
