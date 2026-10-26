"""A small Bayesian optimizer: find good settings for a function that is slow or noisy to evaluate.

How it works, in plain terms: try a few random settings, then repeat this loop. Fit a
"Gaussian process" (a smooth guess of the score everywhere, with an uncertainty band) to what has
been tried. Then test the setting where the guess says an improvement is most likely
("expected improvement"), which balances trying promising areas against unexplored ones.
That needs far fewer tries than a grid search, which is why it suits tuning a model.
Only numpy is needed.
"""
import math

import numpy as np

_erf = np.vectorize(math.erf)


def _rbf(a, b, length):
    """Similarity between every pair of points: 1 for identical points, falling toward 0 with distance."""
    d2 = ((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2)
    return np.exp(-0.5 * d2 / length**2)


def _fit_gp(x, y, noise=1e-6):
    """Fit a Gaussian process, choosing the length scale that explains the data best.

    Returns a predict(points) -> (mean, std) function. y is standardized first.
    """
    mean, std = y.mean(), y.std() or 1.0
    z = (y - mean) / std
    best = None
    for length in (0.1, 0.2, 0.4, 0.8):
        k = _rbf(x, x, length) + noise * np.eye(len(x))
        try:
            chol = np.linalg.cholesky(k)
        except np.linalg.LinAlgError:
            continue
        alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, z))
        log_lik = -0.5 * z @ alpha - np.log(np.diag(chol)).sum()
        if best is None or log_lik > best[0]:
            best = (log_lik, length, chol, alpha)
    _, length, chol, alpha = best

    def predict(points):
        ks = _rbf(points, x, length)
        mu = ks @ alpha
        v = np.linalg.solve(chol, ks.T)
        var = np.clip(1.0 - (v**2).sum(axis=0), 1e-12, None)
        return mu * std + mean, np.sqrt(var) * std

    return predict


def _expected_improvement(mu, sigma, best, xi=0.01):
    z = (mu - best - xi) / sigma
    cdf = 0.5 * (1 + _erf(z / math.sqrt(2)))
    pdf = np.exp(-0.5 * z**2) / math.sqrt(2 * math.pi)
    return (mu - best - xi) * cdf + sigma * pdf


def optimize(objective, bounds, n_init=10, n_iter=40, seed=0):
    """Maximize objective(params) over the ranges in bounds.

    objective takes a dict like {'home_adv': 2.1, ...} and returns a number (higher is better).
    bounds maps each name to (low, high). Returns (best_params, best_score, history), where
    history lists every (params, score) tried.
    """
    names = list(bounds)
    low = np.array([bounds[n][0] for n in names], dtype=float)
    high = np.array([bounds[n][1] for n in names], dtype=float)
    rng = np.random.default_rng(seed)

    def decode(unit):  # points live in the unit cube [0, 1]^d inside; map to the real ranges
        return {n: float(v) for n, v in zip(names, low + unit * (high - low))}

    x = rng.random((n_init, len(names)))
    y = np.array([objective(decode(p)) for p in x])
    for _ in range(n_iter):
        predict = _fit_gp(x, y)
        best_point = x[y.argmax()]
        # Candidates: random points, plus small nudges around the best point so far.
        candidates = np.vstack([
            rng.random((2000, len(names))),
            np.clip(best_point + rng.normal(0, 0.05, (500, len(names))), 0, 1),
        ])
        mu, sigma = predict(candidates)
        chosen = candidates[_expected_improvement(mu, sigma, y.max()).argmax()]
        x = np.vstack([x, chosen])
        y = np.append(y, objective(decode(chosen)))
    history = [(decode(p), float(s)) for p, s in zip(x, y)]
    return decode(x[y.argmax()]), float(y.max()), history
