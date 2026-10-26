import numpy as np
import pandas as pd

from src import backtest, ratings

P = dict(ratings.DEFAULTS["nfl"])


def games_table(rows):
    cols = ["season", "week", "game_type", "gameday", "away_team", "home_team", "away_score",
            "home_score", "spread_line", "total_line", "away_moneyline", "home_moneyline"]
    return pd.DataFrame(rows, columns=cols)


def game(day, home, away, hs, as_, spread=3.0, total=40.0, season=2024):
    return [season, 1, "REG", day, away, home, as_, hs, spread, total, 100, -120]


def test_dataset_only_uses_games_before_each_game():
    rows = [game(f"2024-09-{d:02d}", "AAA", "BBB", 30, 10) for d in range(1, 6)]  # AAA wins by 20 five times
    rows.append(game("2024-09-20", "AAA", "BBB", 17, 20, spread=-7.0))  # the game we will predict
    ds = backtest.build_dataset(games_table(rows), min_games=3)
    # Games 4, 5 and 6 have 3+ earlier games each; the last one is predicted from the five before it.
    assert len(ds["result"]) == 3
    assert ds["mh"][-1].tolist() == [20.0, 20.0, 20.0]        # AAA's earlier margins only
    assert ds["ma"][-1].tolist() == [-20.0, -20.0, -20.0]
    assert ds["spread_home"][-1] == 7.0                        # spread_line -7 -> home is a 7-point dog
    assert ds["result"][-1] == -3.0


def test_games_without_lines_or_history_are_skipped_but_still_count_as_history():
    rows = [game("2024-09-01", "AAA", "BBB", 30, 10, spread=np.nan),
            game("2024-09-02", "AAA", "BBB", 30, 10)]
    assert backtest.build_dataset(games_table(rows), min_games=1)["result"].tolist() == [20.0]


def test_evaluate_scores_a_model_that_knows_the_answer_better_than_a_coin_flip():
    n = 200
    rng = np.random.default_rng(0)
    true_margin = rng.normal(0, 7, n)
    ds = {
        "season": np.full(n, 2024),
        "mh": np.column_stack([true_margin] * 3), "ma": np.zeros((n, 3)),
        "th": np.full((n, 3), 45.0), "ta": np.full((n, 3), 45.0),
        "spread_home": np.zeros(n), "total_line": np.full(n, 45.5),
        "result": true_margin + rng.normal(0, 3, n), "total": np.full(n, 50.0),
        "home_ml": np.full(n, -110.0), "away_ml": np.full(n, -110.0),
    }
    p = {**P, "home_adv": 0.0, "shrink": 1.0, "k_spread": 0.3}
    m = backtest.evaluate(ds, p)
    assert m["games"] == n and m["spread"]["logloss"] < 0.5 and m["spread"]["accuracy"] > 0.8
    assert m["spread"]["roi"] > 0 and m["spread"]["logloss"] < 0.693  # beats a coin flip
    assert np.isfinite(m["total"]["logloss"]) and np.isfinite(m["moneyline"]["logloss"])


def test_pushes_are_excluded_from_scoring():
    ds = {"season": np.array([2024, 2024]), "mh": np.zeros((2, 3)), "ma": np.zeros((2, 3)),
          "th": np.full((2, 3), 40.0), "ta": np.full((2, 3), 40.0),
          "spread_home": np.array([-3.0, -3.0]), "total_line": np.array([40.0, 40.0]),
          "result": np.array([3.0, 10.0]), "total": np.array([40.0, 50.0]),
          "home_ml": np.array([-150.0, -150.0]), "away_ml": np.array([130.0, 130.0])}
    m = backtest.evaluate(ds, P)
    # Game 1 pushes on the spread (3 - 3 = 0) and on the total, so only game 2 counts.
    # Game 2: home won by 10 and covers -3, but the model (expects +2) leans away -> a miss.
    assert m["spread"]["accuracy"] == 0.0
    # Total is 50 vs a 40 line (over); the model expects exactly 40, p = 0.5, picks over -> a hit.
    assert m["total"]["accuracy"] == 1.0


def test_subset_filters_by_season():
    ds = {"season": np.array([2020, 2021, 2022]), "result": np.array([1, 2, 3])}
    assert backtest.subset(ds, [2021, 2022])["result"].tolist() == [2, 3]


def test_objective_is_higher_for_better_probabilities():
    n = 300
    rng = np.random.default_rng(1)
    margin = rng.normal(0, 7, n)
    ds = {"season": np.full(n, 2024), "mh": np.column_stack([margin] * 3), "ma": np.zeros((n, 3)),
          "th": np.full((n, 3), 45.0), "ta": np.full((n, 3), 45.0), "spread_home": np.zeros(n),
          "total_line": np.full(n, 44.5), "result": margin + rng.normal(0, 3, n),
          "total": rng.normal(45, 8, n), "home_ml": np.full(n, -110.0), "away_ml": np.full(n, -110.0)}
    score = backtest.objective(ds)
    good = {**P, "home_adv": 0.0, "shrink": 1.0}
    bad = {**P, "home_adv": 0.0, "shrink": 0.2, "k_spread": 0.01, "k_ml": 0.02}
    assert score(good) > score(bad)
