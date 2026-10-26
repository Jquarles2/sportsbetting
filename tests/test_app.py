"""Run the real Streamlit app headlessly with fake data, so a broken page shows up as a failing test."""
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src import cache, claude, nobet, odds, results, store, ui_betguru, ui_common
from tests.fake_supabase import FakeSupabase

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def row(home, away, ml_h, ml_a, spread, total):
    return dict(GAME=f"{away} @ {home}", HOME=home, AWAY=away, START="2099-01-01T00:00:00Z",
                ML_HOME=ml_h, ML_AWAY=ml_a, SPREAD_HOME=spread, SPREAD_HOME_PRICE=-110,
                SPREAD_AWAY_PRICE=-110, TOTAL=total, OVER=-110, UNDER=-110)


LINES = pd.DataFrame([row("Hawks", "Owls", -250, 210, -6.5, 44.5),
                      row("Bears", "Lions", -150, 130, -3.0, 47.5),
                      row("Cubs", "Reds", -200, 170, -4.5, 41.5)], columns=odds.LINE_COLUMNS)
NBA_LINES = pd.DataFrame([row("Suns", "Jazz", -300, 250, -8.5, 224.5), row("Nets", "Heat", 120, -140, 2.5, 219.5),
                          row("Kings", "Magic", -180, 155, -4.0, 228.5)], columns=odds.LINE_COLUMNS)
STRONG = [{"for": 30, "against": 17}] * 12
WEAK = [{"for": 17, "against": 30}] * 12
FORM = {"Hawks": STRONG, "Owls": WEAK, "Bears": STRONG, "Lions": WEAK, "Cubs": STRONG, "Reds": WEAK,
        "Suns": STRONG, "Jazz": WEAK, "Nets": STRONG, "Heat": WEAK, "Kings": STRONG, "Magic": WEAK}


@pytest.fixture(autouse=True)
def fakes(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "s.db")
    monkeypatch.setattr(odds, "requests_remaining", lambda: 400)
    monkeypatch.setattr(odds, "event_ids", lambda sport, hours: ["a", "b", "c"])
    monkeypatch.setattr(odds, "get_game_lines", lambda sport, hours: (NBA_LINES if sport == odds.NBA else LINES, "397"))
    monkeypatch.setattr(claude, "ask", lambda system, prompt, client=None, max_tokens=500: "A short talk.")
    for cfg in ui_betguru.SPORTS.values():
        monkeypatch.setitem(cfg, "team_games", lambda team: FORM.get(team))
    monkeypatch.setitem(ui_betguru.SPORTS["NFL"], "injuries", lambda team: (
        [{"name": "Sam Qb", "position": "QB", "status": "Out", "injury": "Knee"}] if team == "Owls" else []))
    monkeypatch.setitem(ui_betguru.SPORTS["NFL"], "player_team", lambda name: "Bears")
    ui_common.quota_left.clear()
    ui_common.games_in_window.clear()


def run():
    return AppTest.from_file(APP, default_timeout=60).run()


def has_parlay(at):
    """True if the page is showing a parlay (the lotto has similar metrics, so look for the parlay's own)."""
    return any(m.label.startswith("Expected value per $100") for m in at.metric)


def click(at, label):
    next(b for b in at.button if b.label.startswith(label)).click().run()


def test_page_loads_with_betguru_branding_and_tabs():
    at = run()
    assert not at.exception and at.title[0].value == "🎯 BetGuru"
    assert [t.label for t in at.tabs][:1] == ["🎯 BetGuru"]
    assert any("Build today's NFL slate" in b.label for b in at.button)


def test_nfl_slate_builds_a_parlay_and_flags_the_injured_qb():
    at = run()
    click(at, "Build today's NFL slate")
    assert not at.exception
    assert [m.label for m in at.metric][:3] == ["Chance every leg hits", "Pays (American odds)", "Expected value per $100 (fair odds)"]
    tables = [d.value for d in at.dataframe]
    nobets = next(t for t in tables if "SOURCE" in t.columns)
    assert nobets.iloc[0]["WHO"] == "Sam Qb (QB)" and nobets.iloc[0]["SEVERITY"] == "block"
    legs = next(t for t in tables if "USER_REASON" in t.columns)
    assert legs[legs["PICK"] == "Owls to win"]["SEVERITY"].iloc[0] == "block"  # injured QB's team


def test_risk_level_changes_the_parlay():
    at = run()
    click(at, "Build today's NFL slate")
    at.select_slider(key="bg_risk").set_value("Safe").run()
    assert not at.exception
    safe_text = " ".join(m.value for m in at.markdown)
    assert "Hawks to win" in safe_text


def test_saving_and_grading_a_parlay():
    at = run()
    click(at, "Build today's NFL slate")
    click(at, "Save this parlay")
    assert len(results._legs()) >= 2
    assert not at.exception


def test_talks_are_written_for_each_game():
    at = run()
    click(at, "Build today's NFL slate")
    click(at, "Write the game talks")
    assert not at.exception
    assert sum("A short talk." in m.value for m in at.markdown) == 3


def test_your_no_bet_list_removes_a_game_and_can_be_edited():
    at = run()
    click(at, "Build today's NFL slate")
    at.radio(key="bg_nb_kind").set_value("team").run()
    at.selectbox(key="bg_nb_team").select("Hawks").run()
    click(at, "Add to my list")
    assert nobet.list_items() == [("team", "Hawks")] and not at.exception
    legs = next(d.value for d in at.dataframe if "USER_REASON" in d.value.columns)
    assert legs[legs["GAME"] == "Owls @ Hawks"]["USER_REASON"].notna().all()
    click(at, "Remove")
    assert nobet.list_items() == []


def test_nba_tab_works_and_is_marked_untrained():
    at = run()
    at.radio(key="bg_sport").set_value("NBA").run()
    click(at, "Build today's NBA slate")
    assert not at.exception
    assert any("NBA model hasn't been trained" in w.value for w in at.warning)
    assert [m.label for m in at.metric][0] == "Chance every leg hits"


def test_no_lines_yet_is_handled(monkeypatch):
    monkeypatch.setattr(odds, "get_game_lines", lambda sport, hours: (pd.DataFrame(columns=odds.LINE_COLUMNS), "397"))
    at = run()
    click(at, "Build today's NFL slate")
    assert not at.exception and any("No FanDuel game lines" in i.value for i in at.info)


def test_local_storage_warns_that_it_is_temporary():
    at = run()
    click(at, "Build today's NFL slate")
    assert any("wiped when the app restarts" in w.value for w in at.warning)
    click(at, "Check storage connection")
    assert any(m.value == "Storage works." for m in at.success)


def test_supabase_storage_is_used_and_reported(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store.requests, "request", fake.request)
    monkeypatch.setattr(store, "get_secret", lambda name: {"SUPABASE_URL": fake.url, "SUPABASE_KEY": fake.key}.get(name))
    at = run()
    click(at, "Build today's NFL slate")
    assert any("saved in Supabase" in s.value for s in at.success)
    at.radio(key="bg_nb_kind").set_value("team").run()
    at.selectbox(key="bg_nb_team").select("Hawks").run()
    click(at, "Add to my list")
    assert fake.rows["nobet"] == [{"kind": "team", "name": "Hawks"}]
    click(at, "Save this parlay")
    assert len(fake.rows["picks_log"]) >= 1 and not at.exception


def test_broken_storage_refuses_to_build_a_parlay_rather_than_ignore_your_list(monkeypatch):
    def down():
        raise store.StoreError("Couldn't reach Supabase: timeout")
    monkeypatch.setattr(nobet, "list_items", down)
    at = run()
    click(at, "Build today's NFL slate")
    assert not at.exception and not at.metric
    assert any("won't build a parlay" in e.value and "timeout" in e.value for e in at.error)


def test_loaded_props_join_the_candidates_but_only_for_todays_games(monkeypatch):
    monkeypatch.setitem(ui_betguru.SPORTS["NFL"], "player_injury", lambda name: None)
    cols = ["PLAYER", "GAME", "BOOK", "LINE", "OVER", "UNDER", "START"]
    props = pd.DataFrame([("Wide Out", "Owls @ Hawks", "FanDuel", 60.5, -200, 170, "2099-01-01T00:00:00Z"),
                          ("Other Week", "Tigers @ Bears", "FanDuel", 40.5, -110, -110, "2099-01-05T00:00:00Z")], columns=cols)
    scan = pd.DataFrame({"PLAYER": ["Wide Out", "Other Week"], "GAME": "x", "LINE": 0.0, "VALUES": [[80] * 10, [50] * 10]})
    at = run()
    at.session_state["nfl_player_reception_yds_props"] = (props, "400")
    at.session_state["nfl_player_reception_yds_scan"] = (scan, [])
    click(at, "Build today's NFL slate")
    assert not at.exception
    legs = next(d.value for d in at.dataframe if "USER_REASON" in d.value.columns)
    picks = set(legs["PICK"])
    assert "Wide Out Over 60.5 receiving yards" in picks and not any("Other Week" in p for p in picks)
    assert any("Player props in the mix: receiving yards" in c.value for c in at.caption)


def test_without_loaded_props_the_tab_says_how_to_add_them():
    at = run()
    click(at, "Build today's NFL slate")
    assert any("No props loaded for today's games" in c.value for c in at.caption)


def test_lotto_combines_both_slates_and_is_saved_as_one_ticket_with_each_legs_sport():
    at = run()
    click(at, "Build today's NFL slate")
    at.radio(key="bg_sport").set_value("NBA").run()
    click(at, "Build today's NBA slate")
    assert not at.exception
    assert any(sh.value.startswith("Pay $0.50 to win $") for sh in at.subheader)
    assert any("can't reach $1,000" in i.value for i in at.info)   # six games can't pay 2,000 to 1: it says so
    click(at, "Save this ticket")
    logged = results._legs()
    assert set(logged["risk"]) == {"Lotto"} and set(logged["sport"]) == {"nfl", "nba"}
    assert results.parlay_record() == {"won": 0, "lost": 0, "pending": 1}  # one ticket, not one per sport



def test_page_warns_when_injury_status_could_not_be_checked(monkeypatch):
    def dead(name):
        raise RuntimeError("injury feed down")
    monkeypatch.setitem(ui_betguru.SPORTS["NFL"], "player_injury", dead)
    cols = ["PLAYER", "GAME", "BOOK", "LINE", "OVER", "UNDER", "START"]
    props = pd.DataFrame([(f"Player {i}", "Owls @ Hawks", "FanDuel", 60.5, -110, -110, "2099-01-01T00:00:00Z") for i in range(6)],
                         columns=cols)
    scan = pd.DataFrame({"PLAYER": props["PLAYER"], "GAME": "x", "LINE": 0.0, "VALUES": [[80] * 10] * 6})
    at = run()
    at.session_state["nfl_player_reception_yds_props"] = (props, "400")
    at.session_state["nfl_player_reception_yds_scan"] = (scan, [])
    click(at, "Build today's NFL slate")
    assert not at.exception
    assert any("Couldn't check injury status for 6 prop players" in w.value for w in at.warning)


def test_a_one_game_slate_explains_why_there_is_no_parlay(monkeypatch):
    monkeypatch.setattr(odds, "get_game_lines", lambda sport, hours: (LINES.head(1), "397"))
    at = run()
    click(at, "Build today's NFL slate")
    assert not at.exception and not has_parlay(at)
    assert any("Only 1 game to pick from" in i.value and "Combine with my other built slates" in i.value for i in at.info)


def test_a_parlay_can_mix_sports_and_is_saved_as_one_mixed_ticket(monkeypatch):
    monkeypatch.setattr(odds, "get_game_lines",
                        lambda sport, hours: ((NBA_LINES if sport == odds.NBA else LINES.head(1)), "397"))
    at = run()
    click(at, "Build today's NFL slate")                       # Monday night: a single game
    at.radio(key="bg_sport").set_value("NBA").run()
    click(at, "Build today's NBA slate")
    at.radio(key="bg_sport").set_value("NFL").run()
    at.select_slider(key="bg_risk").set_value("Aggressive").run()
    at.slider(key="bg_legs").set_value(4).run()
    assert not at.exception and has_parlay(at)                  # one NFL game plus three NBA games: a 4-leg parlay
    assert any("Parlay legs come from: NBA, NFL" in c.value for c in at.caption)
    click(at, "Save this parlay")
    logged = results._legs()
    assert set(logged["sport"]) == {"nfl", "nba"} and set(logged["risk"]) == {"Aggressive (mixed)"}
    assert results.parlay_record() == {"won": 0, "lost": 0, "pending": 1}


def test_combining_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(odds, "get_game_lines",
                        lambda sport, hours: ((NBA_LINES if sport == odds.NBA else LINES.head(1)), "397"))
    at = run()
    click(at, "Build today's NFL slate")
    at.radio(key="bg_sport").set_value("NBA").run()
    click(at, "Build today's NBA slate")
    at.radio(key="bg_sport").set_value("NFL").run()
    at.checkbox(key="bg_combine").set_value(False).run()
    assert not at.exception and not has_parlay(at)              # alone, the one NFL game can't make a 3-leg parlay
