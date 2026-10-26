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
