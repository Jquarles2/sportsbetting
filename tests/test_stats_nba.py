import pytest

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


@pytest.fixture(autouse=True)
def temp_cache(tmp_path, monkeypatch):
    """Never touch the real data/cache.db, and don't actually sleep between API calls."""
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    monkeypatch.setattr(stats_nba.time, "sleep", lambda s: None)


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
        lambda pid, season: calls.append(season) or [fake_stat(i) for i in range(25)],
    )

    df = stats_nba.get_game_logs("Stephen Curry", n=10)
    assert len(df) == 10
    assert list(df.columns) == stats_nba.LOG_COLUMNS
    assert df.loc[0, "GAME_DATE"] == "2026-01-25"  # newest first
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


def test_find_player_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(stats_nba, "_get", lambda path, params: calls.append(path) or fake_players())
    assert stats_nba.find_player("Stephen Curry")["id"] == 7
    assert stats_nba.find_player("  stephen   CURRY ")["id"] == 7
    assert len(calls) == 1


def test_recent_values_unknown_player_is_none(monkeypatch):
    monkeypatch.setattr(stats_nba, "_get", lambda path, params: {"data": []})
    assert stats_nba.get_recent_values("Nobody Here", "player_points") is None


def test_recent_values_for_each_market(monkeypatch):
    monkeypatch.setattr(stats_nba, "_get", lambda path, params: fake_players())
    monkeypatch.setattr(stats_nba, "_fetch_season_stats",
                        lambda pid, season: [fake_stat(i) for i in range(25)])
    # fake_stat: pts = 20 + i, reb 5, ast 4, fg3m 2. Newest (i=24) first.
    assert stats_nba.get_recent_values("Stephen Curry", "player_points", n=3) == [44, 43, 42]
    assert stats_nba.get_recent_values("Stephen Curry", "player_rebounds", n=2) == [5, 5]
    assert stats_nba.get_recent_values("Stephen Curry", "player_assists", n=2) == [4, 4]
    assert stats_nba.get_recent_values("Stephen Curry", "player_threes", n=2) == [2, 2]
    assert stats_nba.get_recent_values("Stephen Curry", "player_points_rebounds_assists", n=1) == [53]


def test_get_retries_after_rate_limit(monkeypatch):
    sleeps, statuses = [], iter([429, 429, 200])

    class Resp:
        def __init__(self, code):
            self.status_code = code
        def raise_for_status(self):
            pass
        def json(self):
            return {"data": []}

    monkeypatch.setattr(stats_nba, "get_api_key", lambda: "k")
    monkeypatch.setattr(stats_nba.time, "sleep", sleeps.append)
    monkeypatch.setattr(stats_nba.requests, "get", lambda *a, **k: Resp(next(statuses)))
    assert stats_nba._get("/players", {}) == {"data": []}
    assert 10 in sleeps and 20 in sleeps  # waited 10s then 20s before the third try


def test_get_gives_up_with_readable_error(monkeypatch):
    class Resp:
        status_code = 429
    monkeypatch.setattr(stats_nba, "get_api_key", lambda: "k")
    monkeypatch.setattr(stats_nba.requests, "get", lambda *a, **k: Resp())
    with pytest.raises(RuntimeError, match="rate limit still hit"):
        stats_nba._get("/players", {})


def test_calls_are_paced(monkeypatch):
    sleeps = []
    monkeypatch.setattr(stats_nba.time, "sleep", sleeps.append)
    monkeypatch.setattr(stats_nba, "_last_call", stats_nba.time.monotonic())
    stats_nba._wait_for_turn()
    assert sleeps and 0 < sleeps[0] <= stats_nba.MIN_SECONDS_BETWEEN_CALLS


def test_find_player_handles_suffixes_and_initials(monkeypatch):
    searched = []
    def fake_get(path, params):
        searched.append(params["search"])
        return {"data": [{"id": 1, "first_name": "Jaren", "last_name": "Jackson Jr."},
                         {"id": 2, "first_name": "P.J.", "last_name": "Washington"},
                         {"id": 3, "first_name": "Gary", "last_name": "Payton II"},
                         {"id": 4, "first_name": "Gary", "last_name": "Payton"}]}
    monkeypatch.setattr(stats_nba, "_get", fake_get)
    assert stats_nba.find_player("Jaren Jackson Jr")["id"] == 1
    assert searched[-1] == "jackson"  # not "jr", which matches hundreds of players
    assert stats_nba.find_player("PJ Washington")["id"] == 2
    assert stats_nba.find_player("Gary Payton")["id"] == 4  # the exact name beats "Gary Payton II"
    assert stats_nba.find_player("Gary Payton II")["id"] == 3


def test_zero_minute_lines_count_as_not_played():
    assert not stats_nba._played({"min": "00"})
    assert not stats_nba._played({"min": "0:00"})
    assert not stats_nba._played({"min": None})
    assert stats_nba._played({"min": "34"}) and stats_nba._played({"min": "12:30"})
