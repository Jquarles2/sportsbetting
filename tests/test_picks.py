import pandas as pd

from src import picks


def test_five_of_five_over_under_and_miss():
    over = picks.five_of_five("A", "g", 20.5, [25, 22, 30, 21, 24])
    assert over["SIDE"] == "Over" and over["CUSHION"] == 0.5
    under = picks.five_of_five("A", "g", 20.5, [10, 12, 15, 9, 18])
    assert under["SIDE"] == "Under" and under["CUSHION"] == 2.5
    assert picks.five_of_five("A", "g", 20.5, [25, 22, 30, 20, 24]) is None
    assert picks.five_of_five("A", "g", 20.0, [25, 20, 30, 21, 24]) is None  # push
    assert picks.five_of_five("A", "g", 20.5, [25, 22, 30]) is None  # too few games


def test_scan_and_find_picks():
    props = pd.DataFrame({
        "PLAYER": ["Hot", "Hot", "Safe", "Cold", "Broken"],
        "GAME": ["x"] * 5,
        "LINE": [20.5, 21.5, 10.5, 20.5, 5.5],
    })
    logs = {"Hot": [25] * 5, "Safe": [30] * 5, "Cold": [10, 30, 10, 30, 10]}

    def fake_values(name):
        if name == "Broken":
            raise RuntimeError("boom")
        return logs[name]

    seen = []
    scan, errors = picks.scan_players(props, fake_values, progress=lambda d, t: seen.append((d, t)), pause=0)
    assert errors == ["Broken: boom"] and seen[-1] == (4, 4)
    assert scan.set_index("PLAYER").loc["Hot", "LINE"] == 21.0  # median of the two books
    # Hot's cushion is 4, Safe's 19.5; Cold isn't 5/5.
    assert list(picks.find_picks(scan)["PLAYER"]) == ["Safe", "Hot"]
