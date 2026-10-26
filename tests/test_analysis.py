import pandas as pd

from src import analysis


def make_logs(pts_list):
    # Alternate Home/Away, newest first.
    return pd.DataFrame({
        "PTS": pts_list,
        "HOME_AWAY": ["Home" if i % 2 == 0 else "Away" for i in range(len(pts_list))],
    })


def test_hit_rates_windows_and_splits():
    # 20 games: newest 5 are 30s (over a 25.5 line), the other 15 are 20s (under).
    logs = make_logs([30] * 5 + [20] * 15)
    out = analysis.hit_rates(logs, 25.5).set_index("SPLIT")
    assert out.loc["Last 5", "OVERS"] == 5 and out.loc["Last 5", "HIT_RATE"] == 100.0
    assert out.loc["Last 10", "OVERS"] == 5 and out.loc["Last 10", "HIT_RATE"] == 50.0
    assert out.loc["Last 20", "GAMES"] == 20 and out.loc["Last 20", "HIT_RATE"] == 25.0
    # Home = even positions 0,2,4 (30s) + 10 more at 20 -> 3 overs of 10 games.
    assert out.loc["Home (last 20)", "GAMES"] == 10
    assert out.loc["Home (last 20)", "OVERS"] == 3
    assert out.loc["Away (last 20)", "OVERS"] == 2


def test_push_is_not_an_over():
    out = analysis.hit_rates(make_logs([25, 26]), 25).set_index("SPLIT")
    assert out.loc["Last 5", "OVERS"] == 1  # 26 only; 25 is a push


def test_fewer_games_than_window_and_empty():
    out = analysis.hit_rates(make_logs([30, 30, 30]), 20.5).set_index("SPLIT")
    assert out.loc["Last 20", "GAMES"] == 3
    empty = analysis.hit_rates(pd.DataFrame(columns=["PTS", "HOME_AWAY"]), 20.5)
    assert empty["HIT_RATE"].isna().all()


def test_rate_and_props_table():
    pts = [30, 30, 10, 10, 30]
    assert analysis.rate(pts, 20.5, 5) == 60.0
    assert analysis.rate(pts, 20.5, 5, "Under") == 40.0
    assert analysis.rate(pts, 20.5, 2) == 100.0
    assert analysis.rate([], 20.5, 5) is None
    scan = pd.DataFrame({"PLAYER": ["A"], "GAME": ["x"], "LINE": [20.5], "VALUES": [pts]})
    row = analysis.props_table(scan).iloc[0]
    assert (row["L5"], row["L10"], row["L20"]) == (60.0, 60.0, 60.0)


def lines_df():
    return pd.DataFrame([{"GAME": "Away @ Home", "HOME": "Home", "AWAY": "Away", "ML_HOME": -200,
                          "ML_AWAY": 170, "SPREAD_HOME": -4.5, "TOTAL": 45.5}])


def test_win_cover_over_rates():
    games = [{"for": 30, "against": 20}, {"for": 24, "against": 20}, {"for": 10, "against": 14},
             {"for": 20, "against": 20}]
    assert analysis.win_rate(games, 4) == 50.0
    # Margins are +10, +4, -4, 0. Favored by 4.5 -> only the +10 win covers. Pushes don't count.
    assert analysis.cover_rate(games, -4.5, 4) == 25.0
    assert analysis.cover_rate(games, -4.0, 4) == 25.0  # the +4 game pushes
    assert analysis.cover_rate(games, 4.5, 4) == 100.0  # as a 4.5-point underdog even the -4 loss covers
    assert analysis.over_rate(games, 45.5, 4) == 25.0  # totals: 50, 44, 24, 40
    assert analysis.win_rate([], 5) is None


def test_sides_and_totals_tables():
    form = {"Home": [{"for": 30, "against": 20}] * 10, "Away": [{"for": 10, "against": 20}] * 10}
    sides = analysis.sides_table(lines_df(), form).set_index("TEAM")
    assert sides.loc["Home", "SPREAD"] == -4.5 and sides.loc["Away", "SPREAD"] == 4.5
    assert sides.loc["Home", "COVER_L10"] == 100.0  # +10 margin beats -4.5
    assert sides.loc["Away", "COVER_L10"] == 0.0    # -10 margin loses even with +4.5
    assert sides.loc["Home", "WIN_L5"] == 100.0
    totals = analysis.totals_table(lines_df(), form).iloc[0]
    assert totals["HOME_OVER_L10"] == 100.0 and totals["AWAY_OVER_L10"] == 0.0  # 50 vs 30
    assert totals["AVG_COMBINED"] == 40.0


def test_tables_cope_with_missing_data():
    lines = lines_df().assign(SPREAD_HOME=float("nan"), TOTAL=float("nan"))
    sides = analysis.sides_table(lines, {})
    assert sides["COVER_L10"].isna().all() and sides["WIN_L10"].isna().all()
    assert analysis.totals_table(lines, {}).iloc[0]["AVG_COMBINED"] is None
