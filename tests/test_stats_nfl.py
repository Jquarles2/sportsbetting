import pandas as pd
import pytest

from src import cache, stats_nfl


def fake_rows(season):
    def row(name, week, passing=0, rushing=0, receiving=0, receptions=0, season=season):
        return {"player_display_name": name, "season": season, "week": week, "season_type": "REG",
                "passing_yards": passing, "rushing_yards": rushing,
                "receiving_yards": receiving, "receptions": receptions}
    if season == 2025:
        return [row("Marvin Harrison Jr.", w, receiving=50 + w, receptions=w) for w in (1, 2, 3)] + \
               [row("Patrick Mahomes", w, passing=250 + w) for w in (1, 2, 3)]
    return [row("Marvin Harrison Jr.", 17, receiving=10, season=season)]


@pytest.fixture(autouse=True)
def patched(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    monkeypatch.setattr(stats_nfl, "_current_season", lambda: 2025)
    monkeypatch.setattr(stats_nfl, "_download_season", fake_rows)
    stats_nfl._load_table.cache_clear()


def test_values_are_newest_first_and_span_seasons():
    vals = stats_nfl.get_recent_values("Marvin Harrison Jr.", "player_reception_yds")
    assert vals == [53, 52, 51, 10]  # this season's weeks 3,2,1 then last season's week 17


def test_each_market_reads_its_own_column():
    assert stats_nfl.get_recent_values("Patrick Mahomes", "player_pass_yds", n=2) == [253, 252]
    assert stats_nfl.get_recent_values("Marvin Harrison", "player_receptions", n=1) == [3]


def test_names_match_loosely_and_unknown_is_none():
    assert stats_nfl.get_recent_values("marvin harrison jr", "player_receptions") is not None
    assert stats_nfl.get_recent_values("Nobody Here", "player_pass_yds") is None


def test_season_is_downloaded_once_per_day(monkeypatch):
    calls = []
    monkeypatch.setattr(stats_nfl, "_download_season", lambda s: calls.append(s) or fake_rows(s))
    stats_nfl.get_recent_values("Patrick Mahomes", "player_pass_yds")
    stats_nfl._load_table.cache_clear()  # simulate an app restart; sqlite cache still has it
    stats_nfl.get_recent_values("Patrick Mahomes", "player_pass_yds")
    assert calls == [2025, 2024]


def fake_game_rows():
    """Two defenses faced Mahomes' team; DEN allowed 300 + 200 passing yards, LV allowed 100."""
    def row(name, team, opp, week, passing):
        return {"player_display_name": name, "season": 2025, "week": week, "season_type": "REG",
                "team": team, "opponent_team": opp, "passing_yards": passing, "rushing_yards": 0,
                "receiving_yards": 0, "receptions": 0}
    return [row("Patrick Mahomes", "KC", "DEN", 1, 250), row("Backup QB", "KC", "DEN", 1, 50),
            row("Patrick Mahomes", "KC", "DEN", 2, 200),
            row("Patrick Mahomes", "KC", "LV", 3, 100),
            row("Josh Allen", "BUF", "KC", 3, 400)]


@pytest.fixture
def nfl_names(monkeypatch):
    names = {"KC": "Kansas City Chiefs", "DEN": "Denver Broncos", "LV": "Las Vegas Raiders",
             "BUF": "Buffalo Bills"}
    monkeypatch.setattr(stats_nfl, "_team_names", lambda: names)


def test_matchup_adds_up_players_per_game_and_ranks(monkeypatch, nfl_names):
    monkeypatch.setattr(stats_nfl, "_download_season",
                        lambda s: fake_game_rows() if s == 2025 else [])
    m = stats_nfl.get_matchup("Patrick Mahomes", "player_pass_yds",
                              "Denver Broncos @ Kansas City Chiefs")
    # DEN allowed 300 in week 1 (250 + 50) and 200 in week 2 -> 250 a game. KC allowed 400, LV 100.
    assert m == {"opponent": "Denver Broncos", "per_game": 250.0, "rank": 2, "teams": 3}


def test_matchup_is_none_when_player_or_game_dont_fit(monkeypatch, nfl_names):
    monkeypatch.setattr(stats_nfl, "_download_season", lambda s: fake_game_rows() if s == 2025 else [])
    assert stats_nfl.get_matchup("Nobody", "player_pass_yds", "Denver Broncos @ Kansas City Chiefs") is None
    # Mahomes' team (KC) isn't in this game
    assert stats_nfl.get_matchup("Patrick Mahomes", "player_pass_yds",
                                 "Denver Broncos @ Las Vegas Raiders") is None


def test_injury_statuses(monkeypatch):
    def row(name, status=None, injury=None, practice="Full Participation in Practice", week=7):
        return {"week": week, "full_name": name, "report_status": status,
                "report_primary_injury": injury, "practice_status": practice}
    rows = [row("Hurt Guy", "Questionable", "Groin", "Limited Participation in Practice"),
            row("Healthy Guy"),
            row("Limited Guy", practice="Limited Participation in Practice"),
            row("Old Report Guy", "Out", "Knee", week=6)]
    monkeypatch.setattr(stats_nfl, "_download_injuries", lambda season: rows)
    stats_nfl._load_injuries.cache_clear()
    assert stats_nfl.get_injury("Hurt Guy") == {"week": 7, "status": "Questionable", "injury": "Groin"}
    assert stats_nfl.get_injury("Healthy Guy")["status"] is None
    assert stats_nfl.get_injury("Limited Guy")["status"] == "Limited Participation in Practice"
    assert stats_nfl.get_injury("Old Report Guy") is None  # only the latest week counts
    assert stats_nfl.get_injury("Nobody") is None


def test_injury_is_none_without_a_report(monkeypatch):
    monkeypatch.setattr(stats_nfl, "_download_injuries", lambda season: [])
    stats_nfl._load_injuries.cache_clear()
    assert stats_nfl.get_injury("Anyone") is None
