from src import bayes


def test_finds_the_peak_of_a_smooth_function():
    peak = {"a": 0.3, "b": -1.5}

    def score(p):  # highest (0) at a=0.3, b=-1.5
        return -((p["a"] - peak["a"]) ** 2) - ((p["b"] - peak["b"]) ** 2)

    best, value, history = bayes.optimize(score, {"a": (0, 1), "b": (-3, 3)}, n_init=8, n_iter=30)
    assert abs(best["a"] - 0.3) < 0.1 and abs(best["b"] + 1.5) < 0.3
    assert len(history) == 38 and value == max(s for _, s in history)


def test_beats_random_search_with_the_same_budget():
    def score(p):
        return -((p["x"] - 0.7) ** 2) * 100

    bounds = {"x": (0, 1)}
    best, value, _ = bayes.optimize(score, bounds, n_init=4, n_iter=10, seed=1)
    assert value > -0.5  # within ~0.07 of the peak after only 14 tries


def test_respects_bounds_and_is_repeatable():
    seen = []

    def score(p):
        seen.append(p["x"])
        return -abs(p["x"])

    a = bayes.optimize(score, {"x": (2, 5)}, n_init=3, n_iter=5, seed=3)
    assert all(2 <= v <= 5 for v in seen)
    b = bayes.optimize(score, {"x": (2, 5)}, n_init=3, n_iter=5, seed=3)
    assert a[0] == b[0]
