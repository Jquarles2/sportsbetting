"""Replay past NFL games to score (and tune) the BetGuru model against real historical lines.

nflverse's schedule file has every game's final score plus the spread, total and moneylines.
For each game we rebuild what the model would have known beforehand (each team's earlier games
only, so nothing leaks from the future), predict, and compare to what happened.
"""
import io
from collections import defaultdict

import numpy as np
import pandas as pd
import requests

from src import ratings

GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
NEEDED = ["season", "week", "game_type", "gameday", "away_team", "home_team", "away_score",
          "home_score", "spread_line", "total_line", "away_moneyline", "home_moneyline"]
EPS = 1e-4  # keep probabilities away from exactly 0 or 1 so log-loss stays finite


def download_games():
    resp = requests.get(GAMES_URL, timeout=60)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text), usecols=NEEDED)


def build_dataset(games, min_games=3):
    """Turn a games table into arrays of what the model knew before each game, plus the outcome.

    A game becomes a row only if it has a spread and total and both teams already have at least
    min_games earlier games. Returns a dict of numpy arrays (one entry per game, oldest first).
    spread_home follows the model's convention: negative means the home team is favored.
    """
    played = games.dropna(subset=["home_score", "away_score"])
    played = played.sort_values(["gameday", "week"], kind="stable")
    history = defaultdict(list)  # team -> list of {'for', 'against'}, oldest first
    rows = defaultdict(list)
    for g in played.itertuples():
        home_hist = history[g.home_team][::-1][:20]  # newest first, as ratings.window_stats expects
        away_hist = history[g.away_team][::-1][:20]
        has_lines = not (pd.isna(g.spread_line) or pd.isna(g.total_line))
        if has_lines and len(home_hist) >= min_games and len(away_hist) >= min_games:
            mh, th = ratings.window_stats(home_hist)
            ma, ta = ratings.window_stats(away_hist)
            rows["season"].append(g.season)
            rows["mh"].append(mh)
            rows["ma"].append(ma)
            rows["th"].append(th)
            rows["ta"].append(ta)
            rows["spread_home"].append(-g.spread_line)  # nflverse: positive = home favored
            rows["total_line"].append(g.total_line)
            rows["result"].append(g.home_score - g.away_score)
            rows["total"].append(g.home_score + g.away_score)
            rows["home_ml"].append(g.home_moneyline)
            rows["away_ml"].append(g.away_moneyline)
        history[g.home_team].append({"for": g.home_score, "against": g.away_score})
        history[g.away_team].append({"for": g.away_score, "against": g.home_score})
    return {k: np.array(v) for k, v in rows.items()}


def subset(ds, seasons):
    """Rows from the given seasons (an iterable of years)."""
    mask = np.isin(ds["season"], list(seasons))
    return {k: v[mask] for k, v in ds.items()}


def _logloss(p, won):
    p = np.clip(p, EPS, 1 - EPS)
    return float(-(won * np.log(p) + (1 - won) * np.log(1 - p)).mean())


def _pick_stats(p, won, price_win=100 / 110):
    """How picking the side with p > 0.5 would have done at -110, overall and on the top third."""
    side_prob = np.where(p >= 0.5, p, 1 - p)
    hit = np.where(p >= 0.5, won, 1 - won).astype(float)
    top = side_prob >= np.quantile(side_prob, 2 / 3)
    def roi(h):
        return float((h * price_win - (1 - h)).mean()) if len(h) else float("nan")
    return {"accuracy": float(hit.mean()), "roi": roi(hit),
            "top_third_accuracy": float(hit[top].mean()), "top_third_roi": roi(hit[top])}


def evaluate(ds, params):
    """Score the model on a dataset. Returns per-market log-loss, pick accuracy and -110 ROI.

    Log-loss is how well the probabilities are calibrated (0.693 = no better than a coin flip).
    Pushes (landing exactly on the line) are left out of the spread and total scores.
    """
    em = ratings.expected_margin(ds["mh"], ds["ma"], params)
    et = ratings.expected_total(ds["th"], ds["ta"], params)

    p_cover = ratings.p_home_cover(em, ds["spread_home"], params)
    cover = (ds["result"] + ds["spread_home"]) > 0
    keep = (ds["result"] + ds["spread_home"]) != 0
    p_ov = ratings.p_over(et, ds["total_line"], params)
    over = ds["total"] > ds["total_line"]
    keep_t = ds["total"] != ds["total_line"]
    market_p = ratings.market_home_prob(ds["home_ml"], ds["away_ml"], ds["spread_home"])
    p_win = ratings.p_home_win(em, ds["spread_home"], market_p, params)
    home_won = ds["result"] > 0
    keep_m = ds["result"] != 0

    return {
        "games": int(len(ds["result"])),
        "spread": {"logloss": _logloss(p_cover[keep], cover[keep]), **_pick_stats(p_cover[keep], cover[keep])},
        "total": {"logloss": _logloss(p_ov[keep_t], over[keep_t]), **_pick_stats(p_ov[keep_t], over[keep_t])},
        "moneyline": {"logloss": _logloss(p_win[keep_m], home_won[keep_m]),
                      "accuracy": float(np.where(p_win[keep_m] >= 0.5, home_won[keep_m], ~home_won[keep_m]).mean()),
                      # the book's own probabilities: the bar the model has to beat
                      "market_logloss": _logloss(market_p[keep_m], home_won[keep_m])},
    }


def objective(ds):
    """The score the optimizer maximizes: minus the average log-loss across the three markets."""
    def score(params):
        m = evaluate(ds, params)
        return -(m["spread"]["logloss"] + m["total"]["logloss"] + m["moneyline"]["logloss"]) / 3
    return score
