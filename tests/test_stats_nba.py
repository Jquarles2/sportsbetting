from src import cache, stats_nba


def fake_rows(n=15):
    return [
        {"GAME_DATE": f"2026-01-{i + 1:02d}", "MATCHUP": "BOS vs. NYK", "WL": "W",
         "MIN": 35, "PTS": 20 + i, "REB": 5, "AST": 4, "FG3M": 2, "EXTRA": 0}
        for i in range(n)
    ]


def test_cache_roundtrip(tmp_path):
    db = tmp_path / "c.db"
    assert cache.get("k", db) is None
    cache.put("k", {"a": 1}, db)
    assert cache.get("k", db) == {"a": 1}


def test_find_player_known_and_unknown():
    assert stats_nba.find_player("LeBron James")["full_name"] == "LeBron James"
    assert stats_nba.find_player("Not A Real Playerzzz") is None


def test_get_game_logs_limits_rows_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    calls = []
    monkeypatch.setattr(stats_nba, "_fetch_log", lambda pid: calls.append(pid) or fake_rows())

    df = stats_nba.get_game_logs("LeBron James", n=10)
    assert len(df) == 10
    assert list(df.columns) == stats_nba.LOG_COLUMNS

    stats_nba.get_game_logs("LeBron James", n=5)
    assert len(calls) == 1  # second call came from the cache


def test_unknown_player_returns_none():
    assert stats_nba.get_game_logs("Not A Real Playerzzz") is None
