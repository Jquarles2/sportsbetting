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
