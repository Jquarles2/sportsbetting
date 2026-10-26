"""Run the real Streamlit app headlessly with fake data, so a broken page shows up as a failing test."""
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src import cache, claude, nobet, odds, results, ui_betguru, ui_common

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def row(home, away, ml_h, ml_a, spread, total):
    return dict(GAME=f"{away} @ {home}", HOME=home, AWAY=away, START="2099-01-01T00:00:00Z",
                ML_HOME=ml_h, ML_AWAY=ml_a, SPREAD_HOME=spread, SPREAD_HOME_PRICE=-110,
                SPREAD_AWAY_PRICE=-110, TOTAL=total, OVER=-110, UNDER=-110)


LINES = pd.DataFrame([row("Hawks", "Owls", -250, 210, -6.5, 44.5),
                      row("Bears", "Lions", -150, 130, -3.0, 47.5),
                      row("Cubs", "Reds", -200, 170, -4.5, 41.5)], columns=odds.LINE_COLUMNS)
STRONG = [{"for": 30, "against": 17}] * 12
WEAK = [{"for": 17, "against": 30}] * 12
FORM = {"Hawks": STRONG, "Owls": WEAK, "Bears": STRONG, "Lions": WEAK, "Cubs": STRONG, "Reds": WEAK}


@pytest.fixture(autouse=True)
def fakes(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")
    monkeypatch.setattr(nobet, "DB_PATH", tmp_path / "s.db")
    monkeypatch.setattr(results, "DB_PATH", tmp_path / "s.db")
    monkeypatch.setattr(odds, "requests_remaining", lambda: 400)
    monkeypatch.setattr(odds, "count_games", lambda sport, hours: 3)
    monkeypatch.setattr(odds, "get_game_lines", lambda sport, hours: (LINES, "397"))
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
    assert [m.label for m in at.metric] == ["Chance every leg hits", "Pays (American odds)", "Expected value per $100"]
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
