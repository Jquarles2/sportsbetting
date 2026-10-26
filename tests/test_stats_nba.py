from src import cache, stats_nba


def fake_stat(i, home=True):
    return {
        "min": "34", "pts": 20 + i, "reb": 5, "ast": 4, "fg3m": 2,
        "team": {"id": 1},
        "game": {"date": f"2026-01-{i + 1:02d}T00:00:00.000Z",
                 "home_team_id": 1 if home else 2, "visitor_team_id": 2 if home else 1},
    }


def fake_players():
    return {"data": [
        {"id": 7, "first_name": "Stephen", "last_name": "Curry"},
        {"id": 8, "first_name": "Seth", "last_name": "Curry"},
    ]}


def test_cache_roundtrip(tmp_path):
    db = tmp_path / "c.db"
    assert cache.get("k", db) is None
    cache.put("k", {"a": 1}, db)
    assert cache.get("k", db) == {"a": 1}


def test_find_player_filters_by_full_name(monkeypatch):
    monkeypatch.setattr(stats_nba, "_get", lambda path, params: fake_players())
    assert stats_nba.find_player("Stephen Curry")["id"] == 7
    assert stats_nba.find_player("Seth Curry")["id"] == 8
    assert stats_nba.find_player("Nobody Curry") is None
    assert stats_nba.find_player("   ") is None


def test_get_game_logs_limits_rows_sorts_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    monkeypatch.setattr(stats_nba, "_get", lambda path, params: fake_players())
    calls = []
    monkeypatch.setattr(
        stats_nba, "_fetch_season_stats",
        lambda pid, season: calls.append(season) or [fake_stat(i) for i in range(15)],
    )

    df = stats_nba.get_game_logs("Stephen Curry", n=10)
    assert len(df) == 10
    assert list(df.columns) == stats_nba.LOG_COLUMNS
    assert df.loc[0, "GAME_DATE"] == "2026-01-15"  # newest first
    assert df.loc[0, "HOME_AWAY"] == "Home"

    stats_nba.get_game_logs("Stephen Curry", n=5)
    assert len(calls) == 1  # second lookup came from the cache


def test_early_season_also_fetches_last_season(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    monkeypatch.setattr(stats_nba, "_get", lambda path, params: fake_players())
    calls = []
    monkeypatch.setattr(
        stats_nba, "_fetch_season_stats",
        lambda pid, season: calls.append(season) or [fake_stat(i) for i in range(3)],
    )
    stats_nba.get_game_logs("Stephen Curry", n=10)
    assert len(calls) == 2 and calls[1] == calls[0] - 1


def test_unknown_player_returns_none(monkeypatch):
    monkeypatch.setattr(stats_nba, "_get", lambda path, params: {"data": []})
    assert stats_nba.get_game_logs("Not A Real Playerzzz") is None
