from datetime import datetime, timezone

import pandas as pd
import pytest

from src import cache, results, stats_nba, stats_nfl, store, talks

START = "2026-01-01T18:00:00Z"
LATER = datetime(2026, 1, 2, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "state.db")
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.db")


def legs(*rows):
    cols = ["GAME", "START", "MARKET", "PICK", "TEAM", "LINE", "PRICE", "P"]
    return pd.DataFrame(rows, columns=cols)


def leg(market, pick, team, line, p=0.6, price=-110, game="Owls @ Hawks"):
    return (game, START, market, pick, team, line, price, p)


def test_grading_each_market():
    g = results.grade_leg
    # Hawks (home) beat Owls 27-20
    assert g("Moneyline", "Hawks to win", "Hawks", None, "Hawks", "Owls", 27, 20) == "win"
    assert g("Moneyline", "Owls to win", "Owls", None, "Hawks", "Owls", 27, 20) == "loss"
    assert g("Moneyline", "Owls to win", "Owls", None, "Hawks", "Owls", 20, 20) == "push"
    assert g("Spread", "Hawks -6.5", "Hawks", -6.5, "Hawks", "Owls", 27, 20) == "win"
    assert g("Spread", "Hawks -7", "Hawks", -7.0, "Hawks", "Owls", 27, 20) == "push"
    assert g("Spread", "Hawks -7.5", "Hawks", -7.5, "Hawks", "Owls", 27, 20) == "loss"
    assert g("Spread", "Owls +7.5", "Owls", 7.5, "Hawks", "Owls", 27, 20) == "win"


def test_totals_grading():
    g = results.grade_leg
    assert g("Total", "Over 46.5", None, 46.5, "H", "A", 27, 20) == "win"   # 47 points
    assert g("Total", "Under 46.5", None, 46.5, "H", "A", 27, 20) == "loss"
    assert g("Total", "Over 47", None, 47.0, "H", "A", 27, 20) == "push"
    assert g("Total", "Under 47.5", None, 47.5, "H", "A", 27, 20) == "win"


def test_log_grade_and_record():
    parlay = legs(leg("Moneyline", "Hawks to win", "Hawks", None, p=0.7),
                  leg("Total", "Over 50", None, 50.0, p=0.5, game="Bears @ Lions"))
    results.log_parlay("nfl", "Balanced", parlay)
    results.log_parlay("nfl", "Balanced", parlay)  # same parlay again: ignored
    assert len(results._legs()) == 2

    seen = []
    def get_final(sport, home, away, start):
        seen.append((sport, home, away))
        return (27, 20) if home == "Hawks" else None  # the Lions game isn't final yet
    assert results.grade_pending(get_final, now=LATER) == 1
    assert seen == [("nfl", "Hawks", "Owls"), ("nfl", "Lions", "Bears")]
    rec = results.record().set_index("MARKET")
    assert rec.loc["Moneyline", "WINS"] == 1 and rec.loc["Moneyline", "HIT_RATE"] == 100.0
    assert rec.loc["Moneyline", "MODEL_AVG_P"] == 70.0 and "Total" not in rec.index
    assert results.parlay_record() == {"won": 0, "lost": 0, "pending": 1}


def test_games_that_just_started_are_left_alone():
    results.log_parlay("nfl", "Safe", legs(leg("Moneyline", "Hawks to win", "Hawks", None)))
    soon = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)  # 2 hours after the start
    assert results.grade_pending(lambda *a: (1, 0), now=soon) == 0


def test_parlay_record_and_calibration():
    results.log_parlay("nfl", "Safe", legs(leg("Moneyline", "Hawks to win", "Hawks", None, p=0.65),
                                           leg("Moneyline", "Bears to win", "Bears", None, p=0.62, game="Lions @ Bears")))
    results.log_parlay("nba", "Balanced", legs(leg("Moneyline", "Hawks to win", "Hawks", None, p=0.61)))
    scores = {("Hawks", "Owls"): (27, 20), ("Bears", "Lions"): (10, 20)}
    results.grade_pending(lambda sport, home, away, start: scores.get((home, away)), now=LATER)
    # NFL Safe: Hawks won, Bears lost -> parlay lost. NBA Balanced: Hawks won -> parlay won.
    assert results.parlay_record() == {"won": 1, "lost": 1, "pending": 0}
    cal = results.calibration().set_index("MODEL_SAID")
    assert cal.loc["60-70%", "LEGS"] == 3 and cal.loc["60-70%", "ACTUALLY_HIT"] == "67%"


def test_empty_log_is_fine():
    assert results.record().empty and results.calibration().empty
    assert results.parlay_record() == {"won": 0, "lost": 0, "pending": 0}


def test_nfl_get_final(monkeypatch):
    rows = [{"season": 2026, "week": 7, "gameday": "2026-01-01", "home": "Hawks", "away": "Owls",
             "home_score": 27, "away_score": 20}]
    monkeypatch.setattr(stats_nfl, "_download_results", lambda: rows)
    stats_nfl._load_results.cache_clear()
    start = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)
    assert stats_nfl.get_final("Hawks", "Owls", start) == (27, 20)
    assert stats_nfl.get_final("Owls", "Hawks", start) is None
    assert stats_nfl.get_final("Hawks", "Owls", datetime(2026, 2, 1, tzinfo=timezone.utc)) is None


def test_nba_get_final(monkeypatch):
    seen = {}
    def fake_get(path, params):
        seen.update(params)
        game = {"status": "Final", "home_team": {"full_name": "Boston Celtics"},
                "visitor_team": {"full_name": "New York Knicks"}, "home_team_score": 110, "visitor_team_score": 99}
        return {"data": [game, {**game, "status": "7:30 pm ET", "visitor_team": {"full_name": "Miami Heat"}}]}
    monkeypatch.setattr(stats_nba, "_get", fake_get)
    start = datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc)
    assert stats_nba.get_final("Boston Celtics", "New York Knicks", start) == (110, 99)
    assert seen["dates[]"] == ["2026-01-02", "2026-01-01"]
    assert stats_nba.get_final("Boston Celtics", "Miami Heat", start) is None  # not final yet


def lines_row():
    df = pd.DataFrame([{"GAME": "Owls @ Hawks", "HOME": "Hawks", "AWAY": "Owls", "SPREAD_HOME": -4.5,
                        "TOTAL": 44.5, "ML_HOME": -200, "ML_AWAY": 170}])
    return next(df.itertuples())


def test_game_facts_and_talk_caching():
    from src import ratings
    form = {"Hawks": [{"for": 30, "against": 20}] * 10, "Owls": [{"for": 17, "against": 24}] * 10}
    flags = {"Owls": [{"reason": "Sam Qb (QB) Out", "severity": "block"}], "Hawks": []}
    facts = talks.game_facts(lines_row(), form, ratings.DEFAULTS["nfl"], flags)
    text = "\n".join(facts)
    assert "spread Hawks -4.5" in text and "total 44.5" in text and "moneyline Hawks -200 / Owls +170" in text
    assert "Hawks: 5-0 in the last 5, 10-0 in the last 10" in text and "+10.0 margin" in text
    assert "Owls: 0-5" in text and "Injury report, Owls: Sam Qb (QB) Out." in text
    assert "Model: Hawks by" in text

    from types import SimpleNamespace
    calls = []
    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Talk.")], stop_reason="end_turn")
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    assert talks.get_talk("Owls @ Hawks", facts, client=client) == "Talk."
    assert talks.get_talk("Owls @ Hawks", facts, client=client) == "Talk."
    assert len(calls) == 1
    talks.get_talk("Owls @ Hawks", facts + ["Injury report, Hawks: X (WR) Out."], client=client)
    assert len(calls) == 2  # a new fact means a new talk
    assert calls[0]["model"] == "claude-haiku-5-5" and "ONLY the facts" in calls[0]["system"]


def prop_leg(pick, line, p=0.6, player="Wide Out", market="Prop:player_reception_yds"):
    return pd.DataFrame([("Owls @ Hawks", START, market, pick, None, line, -110, p, player)],
                        columns=["GAME", "START", "MARKET", "PICK", "TEAM", "LINE", "PRICE", "P", "PLAYER"])


def test_prop_grading_rules():
    assert results.grade_prop("Wide Out Over 60.5 receiving yards", 60.5, 80) == "win"
    assert results.grade_prop("Wide Out Over 60.5 receiving yards", 60.5, 60) == "loss"
    assert results.grade_prop("Wide Out Under 60.5 receiving yards", 60.5, 60) == "win"
    assert results.grade_prop("Wide Out Over 60 receiving yards", 60.0, 60) == "push"
    assert results.grade_prop("Wide Out Over 60.5 receiving yards", 60.5, results.DID_NOT_PLAY) == "push"


def test_prop_legs_are_logged_with_the_player_and_graded_from_the_stat_line():
    results.log_parlay("nfl", "Balanced", pd.concat([prop_leg("Wide Out Over 60.5 receiving yards", 60.5),
                                                       prop_leg("Run Back Under 70.5 rushing yards", 70.5, player="Run Back",
                                                                market="Prop:player_rush_yds")]))
    rows = results._legs()
    assert list(rows["team"]) == ["Wide Out", "Run Back"] and rows.iloc[0]["market"] == "Prop:player_reception_yds"
    asked = []
    stats = {"Wide Out": 80, "Run Back": results.DID_NOT_PLAY}

    def get_stat(sport, player, market, home, away, start):
        asked.append((sport, player, market, home, away))
        return stats[player]

    assert results.grade_pending(lambda *a: (27, 20), get_stat=get_stat, now=LATER) == 2
    assert asked[0] == ("nfl", "Wide Out", "player_reception_yds", "Hawks", "Owls")
    graded = results._legs().set_index("team")["result"]
    assert graded["Wide Out"] == "win" and graded["Run Back"] == "push"  # didn't play = voided


def test_prop_legs_wait_when_stats_are_not_published_or_no_stat_source_is_given():
    results.log_parlay("nfl", "Balanced", prop_leg("Wide Out Over 60.5 receiving yards", 60.5))
    assert results.grade_pending(lambda *a: (27, 20), now=LATER) == 0                       # no stat function
    assert results.grade_pending(lambda *a: (27, 20), get_stat=lambda *a: None, now=LATER) == 0  # not published yet
    assert results.grade_pending(lambda *a: None, get_stat=lambda *a: 99, now=LATER) == 0   # game not final
    assert results._legs().iloc[0]["result"] == "pending"


def test_nfl_player_stat(monkeypatch, tmp_path):
    start = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)
    games = [{"season": 2026, "week": 7, "gameday": "2026-01-01", "home": "Hawks", "away": "Owls",
              "home_score": 27, "away_score": 20}]
    monkeypatch.setattr(stats_nfl, "_download_results", lambda: games)
    monkeypatch.setattr(stats_nfl, "_team_names", lambda: {"SEA": "Hawks", "OWL": "Owls", "XYZ": "Others"})

    def row(name, team, week, rec_yards):
        return {"player_display_name": name, "season": 2026, "week": week, "season_type": "REG", "team": team,
                "opponent_team": "OWL", "passing_yards": 0, "rushing_yards": 0, "receiving_yards": rec_yards, "receptions": 0}
    rows = [row("Wide Out", "SEA", 7, 80), row("Other Guy", "OWL", 7, 10)]
    published = {"yes": True}
    monkeypatch.setattr(stats_nfl, "_download_season", lambda s: rows if s == 2026 and published["yes"] else [])
    stats_nfl._load_results.cache_clear()
    stats_nfl._load_table.cache_clear()
    assert stats_nfl.get_player_stat("Wide Out", "player_reception_yds", "Hawks", "Owls", start) == 80
    assert stats_nfl.get_player_stat("Benched Guy", "player_reception_yds", "Hawks", "Owls", start) == stats_nfl.DID_NOT_PLAY
    published["yes"] = False  # the game's stats haven't been posted yet
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "fresh-cache.db")  # forget the data cached above
    stats_nfl._load_table.cache_clear()
    assert stats_nfl.get_player_stat("Wide Out", "player_reception_yds", "Hawks", "Owls", start) is None
    assert stats_nfl.get_player_stat("Wide Out", "player_reception_yds", "Hawks", "Nobody", start) is None  # unknown game


def test_nba_player_stat(monkeypatch):
    start = datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc)

    def fake_get(path, params):
        if path == "/teams":
            return {"data": [{"id": 1, "full_name": "Boston Celtics"}, {"id": 2, "full_name": "New York Knicks"}]}
        if path == "/players":
            return {"data": [{"id": 7, "first_name": "Jayson", "last_name": "Tatum"}]}
        assert path == "/stats" and params["player_ids[]"] == 7
        game = {"home_team_id": 1, "visitor_team_id": 2, "date": "2026-01-01T00:00:00.000Z"}
        return {"data": [{"min": "36", "pts": 30, "reb": 8, "ast": 5, "fg3m": 4, "team": {"id": 1}, "game": game}]}

    monkeypatch.setattr(stats_nba, "_get", fake_get)
    assert stats_nba.get_player_stat("Jayson Tatum", "player_points", "Boston Celtics", "New York Knicks", start) == 30
    assert stats_nba.get_player_stat("Jayson Tatum", "player_points_rebounds_assists", "Boston Celtics", "New York Knicks", start) == 43
    # A different game that day means he has no line in this one: voided, not graded from another game.
    assert stats_nba.get_player_stat("Jayson Tatum", "player_points", "New York Knicks", "Boston Celtics", start) == stats_nba.DID_NOT_PLAY
    assert stats_nba.get_player_stat("Jayson Tatum", "player_points", "Nowhere", "New York Knicks", start) is None
    assert stats_nba.DID_NOT_PLAY == stats_nfl.DID_NOT_PLAY == results.DID_NOT_PLAY
