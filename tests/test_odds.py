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
