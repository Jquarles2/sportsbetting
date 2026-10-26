import pandas as pd

from src import picks, stats_nba


def test_five_of_five_over_under_and_miss():
    over = picks.five_of_five("A", "g", 20.5, [25, 22, 30, 21, 24])
    assert over["SIDE"] == "Over" and over["CUSHION"] == 0.5
    under = picks.five_of_five("A", "g", 20.5, [10, 12, 15, 9, 18])
    assert under["SIDE"] == "Under" and under["CUSHION"] == 2.5
    assert picks.five_of_five("A", "g", 20.5, [25, 22, 30, 20, 24]) is None
    assert picks.five_of_five("A", "g", 20.0, [25, 20, 30, 21, 24]) is None  # push
    assert picks.five_of_five("A", "g", 20.5, [25, 22, 30]) is None  # too few games


def test_find_picks_sorts_by_cushion_and_collects_errors(monkeypatch):
    props = pd.DataFrame({
        "PLAYER": ["Hot", "Hot", "Safe", "Cold", "Broken"],
        "GAME": ["x"] * 5,
        "LINE": [20.5, 21.5, 10.5, 20.5, 5.5],
    })
    logs = {"Hot": [25] * 5, "Safe": [30] * 5, "Cold": [10, 30, 10, 30, 10]}

    def fake_logs(name, n):
        if name == "Broken":
            raise RuntimeError("boom")
        return pd.DataFrame({"PTS": logs[name]})

    monkeypatch.setattr(stats_nba, "get_game_logs", fake_logs)
    seen = []
    df, errors = picks.find_picks(props, progress=lambda d, t: seen.append((d, t)), pause=0)
    assert list(df["PLAYER"]) == ["Safe", "Hot"]  # Hot's median line is 21.0 -> cushion 4
    assert errors == ["Broken: boom"] and seen[-1] == (4, 4)
