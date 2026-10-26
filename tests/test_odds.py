import requests

from src import cache, odds


def event(i="e1"):
    return {"id": i, "home_team": "Boston Celtics", "away_team": "New York Knicks",
            "commence_time": "2099-01-01T00:00:00Z"}


def props_json():
    def outcomes(point, over, under):
        return [
            {"name": "Over", "description": "Jayson Tatum", "price": over, "point": point},
            {"name": "Under", "description": "Jayson Tatum", "price": under, "point": point},
        ]
    return {"bookmakers": [
        {"title": "DraftKings", "markets": [{"key": "player_points", "outcomes": outcomes(27.5, -115, -105)}]},
        {"title": "FanDuel", "markets": [{"key": "player_points", "outcomes": outcomes(28.5, -110, -110)}]},
    ]}


def test_parse_event_props_pairs_over_and_under():
    rows = odds.parse_event_props(event(), props_json())
    assert len(rows) == 2
    dk = next(r for r in rows if r["BOOK"] == "DraftKings")
    assert (dk["PLAYER"], dk["LINE"], dk["OVER"], dk["UNDER"]) == ("Jayson Tatum", 27.5, -115, -105)
    assert dk["GAME"] == "New York Knicks @ Boston Celtics"


def test_get_todays_props_skips_far_future_games_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    calls = []

    def fake_get(path, params):
        calls.append(path)
        if path.endswith("/events"):
            return [event()], "499"
        return props_json(), "498"

    monkeypatch.setattr(odds, "_get", fake_get)
    # The sample game is in 2099, so it's outside the 24h window and no props are fetched.
    df, remaining = odds.get_todays_props()
    assert df.empty and list(df.columns) == odds.COLUMNS
    assert len(calls) == 1  # only the free events listing

    odds.get_todays_props()
    assert len(calls) == 1  # second call came from the cache


def test_get_todays_props_fetches_games_starting_soon(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    monkeypatch.setattr(odds, "_starts_soon", lambda e, hours: True)

    def fake_get(path, params):
        return ([event()], "499") if path.endswith("/events") else (props_json(), "498")

    monkeypatch.setattr(odds, "_get", fake_get)
    df, remaining = odds.get_todays_props()
    assert len(df) == 2 and remaining == "498"


def test_game_without_props_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    monkeypatch.setattr(odds, "_starts_soon", lambda e, hours: True)

    def fake_get(path, params):
        if path.endswith("/events"):
            return [event()], "499"
        resp = requests.Response()
        resp.status_code = 422
        raise requests.HTTPError(response=resp)

    monkeypatch.setattr(odds, "_get", fake_get)
    df, _ = odds.get_todays_props()
    assert df.empty


def game_json():
    def outcomes(*items):
        return [{"name": n, "price": pr, **({"point": pt} if pt is not None else {})} for n, pr, pt in items]
    return {**event(), "bookmakers": [{"title": "FanDuel", "markets": [
        {"key": "h2h", "outcomes": outcomes(("Boston Celtics", -180, None), ("New York Knicks", 150, None))},
        {"key": "spreads", "outcomes": outcomes(("Boston Celtics", -110, -4.5), ("New York Knicks", -110, 4.5))},
        {"key": "totals", "outcomes": outcomes(("Over", -105, 221.5), ("Under", -115, 221.5))},
    ]}]}


def test_parse_game_lines():
    row = odds.parse_game_lines(game_json())
    assert row["GAME"] == "New York Knicks @ Boston Celtics"
    assert (row["ML_HOME"], row["ML_AWAY"]) == (-180, 150)
    assert (row["SPREAD_HOME"], row["SPREAD_HOME_PRICE"], row["SPREAD_AWAY_PRICE"]) == (-4.5, -110, -110)
    assert (row["TOTAL"], row["OVER"], row["UNDER"]) == (221.5, -105, -115)
    assert odds.parse_game_lines({**event(), "bookmakers": []}) is None


def test_get_game_lines_filters_by_time_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    calls = []
    monkeypatch.setattr(odds, "_get", lambda path, params: calls.append(path) or ([game_json()], "497"))
    df, _ = odds.get_game_lines(odds.NBA, hours=24)
    assert df.empty and list(df.columns) == odds.LINE_COLUMNS  # the sample game is in 2099
    odds.get_game_lines(odds.NBA, hours=24)
    assert len(calls) == 1
    df, remaining = odds.get_game_lines(odds.NFL, hours=24 * 365 * 100)
    assert len(df) == 1 and remaining == "497"
