import numpy as np
import pytest

from src import ratings

P = dict(ratings.DEFAULTS["nfl"])


def games(*pairs):
    return [{"for": f, "against": a} for f, a in pairs]


def test_window_stats():
    margins, totals = ratings.window_stats(games((30, 20), (20, 30), (24, 24)))
    assert margins.tolist() == [0.0, 0.0, 0.0]  # +10, -10, 0
    assert totals.tolist() == pytest.approx([49.33, 49.33, 49.33], abs=0.01)  # 50, 50, 48
    margins, _ = ratings.window_stats(games(*[(30, 20)] * 5 + [(10, 20)] * 15))
    assert margins.tolist() == [10.0, 0.0, -5.0]  # last 5, 10, 20 games: +10 x5, then -10s
    assert ratings.window_stats([])[0].tolist() == [0.0, 0.0, 0.0]


def test_better_home_team_gets_a_bigger_expected_margin():
    strong = games(*[(30, 17)] * 20)
    weak = games(*[(17, 30)] * 20)
    assert ratings.predict_game(strong, weak, P)["exp_margin"] > ratings.predict_game(weak, strong, P)["exp_margin"]
    equal = ratings.predict_game(strong, strong, P)
    assert equal["exp_margin"] == pytest.approx(P["home_adv"])  # equal teams -> just home advantage


def test_expected_total_is_the_average_of_both_teams():
    a, b = games(*[(30, 20)] * 20), games(*[(20, 14)] * 20)
    assert ratings.predict_game(a, b, P)["exp_total"] == pytest.approx((50 + 34) / 2)


def test_probabilities_move_the_right_way():
    em = np.array([6.0])
    assert ratings.p_home_cover(em, -3.0, P)[0] > 0.5   # we expect +6, book says -3
    assert ratings.p_home_cover(em, -9.0, P)[0] < 0.5
    assert ratings.p_over(np.array([50.0]), 44.5, P)[0] > 0.5
    # With no tilt the moneyline probability is exactly the market's; our margin tilts it.
    market = np.array([0.65])
    assert ratings.p_home_win(np.array([3.0]), -3.0, market, P)[0] == pytest.approx(0.65)
    assert ratings.p_home_win(np.array([9.0]), -3.0, market, P)[0] > 0.65   # we like home more
    assert ratings.p_home_win(np.array([-3.0]), -3.0, market, P)[0] < 0.65
    assert ratings.p_home_win(np.array([9.0]), -3.0, market, {**P, "k_ml": 0.0})[0] == pytest.approx(0.65)


def test_market_probability_removes_the_vig_and_falls_back_to_the_spread():
    p = ratings.market_home_prob(np.array([-150.0]), np.array([130.0]), np.array([-3.0]))[0]
    assert p == pytest.approx(0.6 / (0.6 + 100 / 230), abs=1e-6) and 0.5 < p < 0.62
    fallback = ratings.market_home_prob(np.array([np.nan]), np.array([np.nan]), np.array([-6.0]))[0]
    assert fallback > 0.65 and ratings.market_home_prob(np.array([np.nan]), np.array([np.nan]), np.array([0.0]))[0] == pytest.approx(0.5)


def test_zero_weights_fall_back_to_an_equal_blend():
    p = {**P, "w5": 0, "w10": 0, "w20": 0}
    stats = np.array([[3.0, 6.0, 9.0]])
    assert ratings._mix(stats, p)[0] == pytest.approx(6.0)


def test_odds_conversions():
    assert ratings.american_to_prob(-110) == pytest.approx(0.5238, abs=1e-3)
    assert ratings.american_to_prob(150) == pytest.approx(0.4)
    assert ratings.american_to_decimal(-200) == pytest.approx(1.5)
    assert ratings.american_to_decimal(150) == pytest.approx(2.5)
    assert ratings.decimal_to_american(1.5) == -200 and ratings.decimal_to_american(2.5) == 150


def test_load_params_uses_defaults_without_a_trained_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings, "DATA_DIR", tmp_path)
    assert ratings.load_params("nba") == ratings.DEFAULTS["nba"]
    assert ratings.load_model_info("nba") is None
    (tmp_path / "model_nba.json").write_text('{"params": {"home_adv": 3.3}, "metrics": {}}')
    assert ratings.load_params("nba")["home_adv"] == 3.3 and ratings.load_params("nba")["w5"] == 0.3
    assert ratings.load_model_info("nba")["metrics"] == {}
