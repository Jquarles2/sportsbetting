import pandas as pd

from src import cache, games, stats_nba, stats_nfl


def test_scan_teams_collects_form_and_errors():
    lines = pd.DataFrame({"HOME": ["A", "B"], "AWAY": ["C", "D"]})
    data = {"A": [{"for": 1, "against": 0}], "B": [{"for": 2, "against": 1}], "C": None}

    def get(team):
        if team == "D":
            raise RuntimeError("boom")
        return data[team]

    seen = []
    form, errors = games.scan_teams(lines, get, progress=lambda d, t: seen.append((d, t)), pause=0)
    assert set(form) == {"A", "B"}  # C isn't found and D failed, so neither is included
    assert errors == ["D: boom"] and seen[-1] == (4, 4)


def test_nba_team_games(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    calls = []

    def fake_get(path, params):
        calls.append(path)
        if path == "/teams":
            return {"data": [{"id": 2, "full_name": "Boston Celtics"}]}
        final = {"status": "Final", "home_team": {"id": 2}, "date": "2026-01-02T00:00:00Z",
                 "home_team_score": 110, "visitor_team_score": 100}
        away_win = {**final, "date": "2026-01-03T00:00:00Z", "home_team": {"id": 9},
                    "home_team_score": 90, "visitor_team_score": 105}
        not_played = {**final, "status": "7:30 pm ET", "date": "2026-01-04T00:00:00Z"}
        return {"data": [final, away_win, not_played], "meta": {}}

    monkeypatch.setattr(stats_nba, "_get", fake_get)
    monkeypatch.setattr(stats_nba, "_current_season", lambda: 2025)
    got = stats_nba.get_team_games("boston celtics", n=2)
    assert got == [{"for": 105, "against": 90}, {"for": 110, "against": 100}]  # newest first
    assert stats_nba.get_team_games("Nowhere Nobodies") is None
    assert calls.count("/games") == 1  # 2 finished games is enough, so no last-season fetch
    before = len(calls)
    stats_nba.get_team_games("Boston Celtics", n=2)
    assert len(calls) == before


def test_nfl_team_games(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    rows = [
        {"season": 2026, "week": 1, "home": "Kansas City Chiefs", "away": "Denver Broncos",
         "home_score": 27, "away_score": 20},
        {"season": 2026, "week": 2, "home": "Las Vegas Raiders", "away": "Kansas City Chiefs",
         "home_score": 10, "away_score": 31},
    ]
    monkeypatch.setattr(stats_nfl, "_download_results", lambda: rows)
    stats_nfl._load_results.cache_clear()
    assert stats_nfl.get_team_games("Kansas City Chiefs") == [
        {"for": 31, "against": 10}, {"for": 27, "against": 20}]
    assert stats_nfl.get_team_games("Denver Broncos") == [{"for": 20, "against": 27}]
    assert stats_nfl.get_team_games("Nobody") is None


def test_nba_injury_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    calls = []

    def fake_get(path, params):
        calls.append(path)
        return {"data": [{"player": {"first_name": "Jayson", "last_name": "Tatum"},
                          "status": "Day-To-Day", "description": "Sore ankle"}], "meta": {}}

    monkeypatch.setattr(stats_nba, "_get", fake_get)
    assert stats_nba.get_injury("jayson  TATUM") == {"status": "Day-To-Day", "injury": "Sore ankle"}
    assert stats_nba.get_injury("Healthy Player") is None  # not on the list means healthy
    assert calls == ["/player_injuries"]  # the list is fetched once and cached
