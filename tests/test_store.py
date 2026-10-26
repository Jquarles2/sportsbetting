import pandas as pd
import pytest
import requests

from src import cache, nobet, results, store
from tests.fake_supabase import FakeSupabase

URL, KEY = "https://proj.supabase.co", "secret-key"


def pick(i=0, **extra):
    row = {"logged_on": "2026-10-26", "sport": "nfl", "risk": "Safe", "game": f"B{i} @ A{i}",
           "start": "2026-10-26T18:00:00Z", "market": "Moneyline", "pick": f"A{i} to win", "team": f"A{i}",
           "line": None, "price": -150.0, "p": 0.62}
    return {**row, **extra}


@pytest.fixture
def fake(monkeypatch):
    fake = FakeSupabase(URL, KEY)
    monkeypatch.setattr(store.requests, "request", fake.request)
    return fake


@pytest.fixture(params=["sqlite", "supabase"])
def db(request, tmp_path, monkeypatch):
    """Each test in this file runs against both backends, so they must behave the same."""
    if request.param == "sqlite":
        monkeypatch.setattr(store, "DB_PATH", tmp_path / "s.db")
        return store.SQLiteStore()
    monkeypatch.setattr(store.requests, "request", FakeSupabase(URL, KEY).request)
    return store.SupabaseStore(URL, KEY)


def test_nobet_roundtrip_order_and_duplicates(db):
    assert db.nobet_list() == []
    db.nobet_add("team", "Kansas City Chiefs")
    db.nobet_add("player", "Sam Qb")
    db.nobet_add("team", "Kansas City Chiefs")  # a duplicate is ignored
    assert db.nobet_list() == [("team", "Kansas City Chiefs"), ("player", "Sam Qb")]
    db.nobet_remove("team", "Kansas City Chiefs")
    assert db.nobet_list() == [("player", "Sam Qb")]
    db.nobet_remove("team", "Never Added")  # removing something absent is fine


def test_picks_add_ignores_duplicates_and_starts_pending(db):
    db.picks_add([pick(1), pick(2)])
    db.picks_add([pick(1), pick(3)])  # leg 1 again: ignored
    rows = db.picks_all()
    assert [r["pick"] for r in rows] == ["A1 to win", "A2 to win", "A3 to win"]
    assert all(r["result"] == "pending" and r["graded_on"] is None for r in rows)
    assert rows[0]["price"] == -150.0 and rows[0]["line"] is None and rows[0]["logged_on"] == "2026-10-26"
    db.picks_add([])  # nothing to save is fine


def test_same_leg_on_another_day_or_risk_is_a_new_row(db):
    db.picks_add([pick(1), pick(1, logged_on="2026-10-27"), pick(1, risk="Aggressive")])
    assert len(db.picks_all()) == 3


def test_grading_moves_a_leg_out_of_pending(db):
    db.picks_add([pick(1), pick(2)])
    first = db.picks_pending()[0]
    db.picks_grade(first["id"], "win", "2026-10-27")
    assert [r["pick"] for r in db.picks_pending()] == ["A2 to win"]
    graded = next(r for r in db.picks_all() if r["id"] == first["id"])
    assert graded["result"] == "win" and graded["graded_on"] == "2026-10-27"


def test_many_rows_are_all_returned(db):
    db.picks_add([pick(i) for i in range(2300)])  # more than Supabase's 1000-row page
    assert len(db.picks_all()) == 2300 and len(db.picks_pending()) == 2300


def test_check_passes_when_everything_is_set_up(db):
    db.check()


def test_cache_roundtrip_only_where_it_is_durable(db):
    db.cache_put("odds_x", "2026-10-26", {"rows": [1, 2]})
    if db.durable:
        assert db.cache_get("odds_x", "2026-10-26") == {"rows": [1, 2]}
        assert db.cache_get("odds_x", "2026-10-27") is None  # yesterday's answer isn't today's
        db.cache_put("odds_x", "2026-10-26", {"rows": [3]})  # saving again replaces it
        assert db.cache_get("odds_x", "2026-10-26") == {"rows": [3]}
    else:
        assert db.cache_get("odds_x", "2026-10-26") is None


# --- Supabase specifics ---

def test_requests_carry_the_key_and_filters(fake):
    db = store.SupabaseStore(URL + "/", KEY)  # a trailing slash on the URL is fine
    db.nobet_add("team", "Chiefs")
    db.picks_add([pick(1)])
    db.picks_grade(7, "win", "2026-10-27")
    db.nobet_remove("team", "Chiefs")
    assert ("POST", "nobet", {"on_conflict": "kind,name"}) in fake.calls
    assert ("POST", "picks_log", {"on_conflict": "logged_on,sport,risk,game,market,pick"}) in fake.calls
    assert ("PATCH", "picks_log", {"id": "eq.7"}) in fake.calls
    assert ("DELETE", "nobet", {"kind": "eq.team", "name": "eq.Chiefs"}) in fake.calls


def test_wrong_key_gives_a_readable_error(fake):
    with pytest.raises(store.StoreError, match="rejected the key"):
        store.SupabaseStore(URL, "wrong").nobet_list()


def test_missing_table_points_at_the_setup_file(monkeypatch):
    monkeypatch.setattr(store.requests, "request", FakeSupabase(URL, KEY, tables=("nobet",)).request)
    with pytest.raises(store.StoreError, match="supabase_setup.sql"):
        store.SupabaseStore(URL, KEY).check()


def test_network_failure_gives_a_readable_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("no route")
    monkeypatch.setattr(store.requests, "request", boom)
    with pytest.raises(store.StoreError, match="Couldn't reach Supabase"):
        store.SupabaseStore(URL, KEY).nobet_list()


def test_get_store_uses_supabase_only_when_both_secrets_exist(monkeypatch):
    secrets = {}
    monkeypatch.setattr(store, "get_secret", lambda name: secrets.get(name))
    assert isinstance(store.get_store(), store.SQLiteStore)
    secrets["SUPABASE_URL"] = URL
    assert isinstance(store.get_store(), store.SQLiteStore)  # a key is missing, so don't half-connect
    secrets["SUPABASE_KEY"] = KEY
    assert isinstance(store.get_store(), store.SupabaseStore)


# --- the app-level pieces running on Supabase ---

@pytest.fixture
def on_supabase(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "get_secret", lambda name: {"SUPABASE_URL": URL, "SUPABASE_KEY": KEY}.get(name))
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "local-cache.db")
    cache._recent_misses.clear()
    return fake


def test_no_bet_list_and_results_survive_on_supabase(on_supabase):
    assert nobet.add("team", " Kansas   City Chiefs ") and not nobet.add("team", "  ")
    assert nobet.list_items() == [("team", "Kansas City Chiefs")]
    legs = pd.DataFrame([("Owls @ Hawks", "2026-01-01T18:00:00Z", "Moneyline", "Hawks to win", "Hawks", None, -150, 0.6)],
                        columns=["GAME", "START", "MARKET", "PICK", "TEAM", "LINE", "PRICE", "P"])
    results.log_parlay("nfl", "Safe", legs)
    results.log_parlay("nfl", "Safe", legs)
    assert len(on_supabase.rows["picks_log"]) == 1
    assert results.grade_pending(lambda *a: (27, 20), now=pd.Timestamp("2026-01-02", tz="UTC").to_pydatetime()) == 1
    assert results.record().set_index("MARKET").loc["Moneyline", "WINS"] == 1


def test_odds_cache_survives_a_restart_but_other_keys_stay_local(on_supabase, tmp_path, monkeypatch):
    cache.put("odds_nba_lines", {"rows": [1]})
    cache.put("bdl_gamelog_5", [1, 2, 3])
    assert [r["key"] for r in on_supabase.rows["cache"]] == ["odds_nba_lines"]  # only Odds API answers go remote
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "fresh-after-restart.db")  # the local file is wiped
    cache._recent_misses.clear()
    assert cache.get("odds_nba_lines") == {"rows": [1]}   # restored from Supabase
    assert cache.get("bdl_gamelog_5") is None            # not durable, so it must be refetched
    before = len(on_supabase.calls)
    assert cache.get("odds_nba_lines") == {"rows": [1]}   # now local again
    assert len(on_supabase.calls) == before


def test_missing_cache_entries_are_not_asked_for_on_every_click(on_supabase):
    assert cache.get("odds_nfl_lines") is None
    asked = len(on_supabase.calls)
    for _ in range(5):
        assert cache.get("odds_nfl_lines") is None
    assert len(on_supabase.calls) == asked  # the miss is remembered for a minute
    cache.put("odds_nfl_lines", {"rows": []})
    assert cache.get("odds_nfl_lines") == {"rows": []}


def test_a_broken_supabase_never_breaks_the_cache(on_supabase, monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(store.requests, "request", boom)
    cache.put("odds_x", {"a": 1})                 # saved locally even though the remote save fails
    assert cache.get("odds_x") == {"a": 1}
    assert cache.get("odds_never_saved") is None  # a failed lookup is just a miss
