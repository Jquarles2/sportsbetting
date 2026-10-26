"""The BetGuru team-vs-team model: from two teams' recent games, predict the margin and total.

The idea, step by step:
1. Each team's rating is its average winning margin over the last 5, 10 and 20 games, blended
   with weights (w5, w10, w20) so recent form can count more or less than the long run.
2. Expected home margin = home advantage + shrink * (home rating - away rating). "shrink" pulls the
   gap toward zero, because recent form overstates real differences between teams.
3. Expected total = the average of both teams' typical combined score.
4. Turn the gap between our number and the book's line into a probability with a logistic curve,
   p = 1 / (1 + e^-(k * gap)). Bigger k means we trust our number more. For the moneyline we start
   from the book's own win probability (with the vig removed) and tilt it by k * gap, so the
   model only moves away from the market as far as backtests say is justified.

Backtests on 14 NFL seasons show recent form adds almost nothing beyond what the lines already
price in, so the tuned k values come out small. That is expected, not a bug.

All the settings live in a params dict. Bayesian optimization (src/bayes.py) tunes them on past
NFL games; see scripts/train_weights.py.
"""
import json
from pathlib import Path

import numpy as np

WINDOWS = (5, 10, 20)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Starting settings, used when a sport hasn't been trained (the NBA has no free historical lines).
DEFAULTS = {
    "nfl": {"w5": 0.3, "w10": 0.4, "w20": 0.3, "home_adv": 2.0, "shrink": 0.8,
            "k_spread": 0.12, "k_total": 0.08, "k_ml": 0.12},
    "nba": {"w5": 0.3, "w10": 0.4, "w20": 0.3, "home_adv": 2.5, "shrink": 0.8,
            "k_spread": 0.15, "k_total": 0.06, "k_ml": 0.12},
}
# The ranges the optimizer searches.
# A k of 0 means "ignore our model and trust the market", so the search is allowed to pick it.
BOUNDS = {"w5": (0.0, 1.0), "w10": (0.0, 1.0), "w20": (0.0, 1.0), "home_adv": (0.0, 5.0),
          "shrink": (0.0, 1.2), "k_spread": (0.0, 0.3), "k_total": (0.0, 0.2), "k_ml": (0.0, 0.3)}


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def window_stats(games):
    """Average margin and average combined score over the last 5/10/20 games.

    games are {'for', 'against'} dicts, newest first. A window with no games counts as 0.
    Returns two arrays of length 3: (margins, totals).
    """
    margins, totals = [], []
    for n in WINDOWS:
        last = games[:n]
        margins.append(sum(g["for"] - g["against"] for g in last) / len(last) if last else 0.0)
        totals.append(sum(g["for"] + g["against"] for g in last) / len(last) if last else 0.0)
    return np.array(margins), np.array(totals)


def _mix(stats, params):
    """Blend the three window averages (shape (n, 3)) into one number per row."""
    w = np.array([params["w5"], params["w10"], params["w20"]], dtype=float)
    w = w / w.sum() if w.sum() > 0 else np.full(3, 1 / 3)
    return np.asarray(stats, dtype=float) @ w


def expected_margin(margins_home, margins_away, params):
    """Expected home margin (home points minus away points)."""
    return params["home_adv"] + params["shrink"] * (_mix(margins_home, params) - _mix(margins_away, params))


def expected_total(totals_home, totals_away, params):
    return (_mix(totals_home, params) + _mix(totals_away, params)) / 2


def p_home_cover(exp_margin, spread_home, params):
    """Chance the home team covers. spread_home is the home team's number: -3.5 = favored by 3.5."""
    return sigmoid(params["k_spread"] * (exp_margin + spread_home))


def p_over(exp_total, total_line, params):
    return sigmoid(params["k_total"] * (exp_total - total_line))


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def p_home_win(exp_margin, spread_home, market_p, params):
    """Home win chance: the market's probability, tilted by how far our margin is from the spread.

    The book's spread says the home team should win by -spread_home, so (exp_margin + spread_home)
    is how much more (or less) we like the home team than the book does.
    """
    return sigmoid(logit(market_p) + params["k_ml"] * (exp_margin + spread_home))


def market_home_prob(home_price, away_price, spread_home):
    """The book's home win probability with the vig removed.

    Uses the two moneylines when both exist. Otherwise estimates it from the spread: each point
    of spread is worth roughly 0.13 on the logit scale.
    """
    ok = ~(np.isnan(np.asarray(home_price, dtype=float)) | np.isnan(np.asarray(away_price, dtype=float)))
    h = np.where(ok, home_price, -110.0)
    a = np.where(ok, away_price, -110.0)
    ph, pa = _prob_arr(h), _prob_arr(a)
    return np.where(ok, ph / (ph + pa), sigmoid(-0.13 * np.asarray(spread_home, dtype=float)))


def _prob_arr(price):
    price = np.asarray(price, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):  # np.where computes both branches
        return np.where(price < 0, -price / (-price + 100), 100 / (price + 100))


def predict_game(home_games, away_games, params):
    """Expected margin and total for one game from the two teams' recent games."""
    mh, th = window_stats(home_games)
    ma, ta = window_stats(away_games)
    return {
        "exp_margin": float(expected_margin(mh[None, :], ma[None, :], params)[0]),
        "exp_total": float(expected_total(th[None, :], ta[None, :], params)[0]),
    }


def american_to_prob(price):
    """The probability a bet at American odds implies (-110 -> 0.524, +150 -> 0.4)."""
    price = float(price)
    return -price / (-price + 100) if price < 0 else 100 / (price + 100)


def american_to_decimal(price):
    price = float(price)
    return 1 + (100 / -price if price < 0 else price / 100)


def decimal_to_american(decimal):
    """Back to American odds, rounded to a whole number."""
    return round(-100 / (decimal - 1)) if decimal < 2 else round((decimal - 1) * 100)


def load_params(sport):
    """Tuned settings from data/model_<sport>.json, or the defaults if that sport isn't trained."""
    path = DATA_DIR / f"model_{sport}.json"
    if path.exists():
        saved = json.loads(path.read_text())
        return {**DEFAULTS[sport], **saved["params"]}
    return dict(DEFAULTS[sport])


def load_model_info(sport):
    """The saved training report (metrics, seasons used), or None if untrained."""
    path = DATA_DIR / f"model_{sport}.json"
    return json.loads(path.read_text()) if path.exists() else None
