"""Tune the BetGuru model on past NFL games with Bayesian optimization.

Run from the project folder:   python scripts/train_weights.py

It tunes on older seasons, then checks the result on newer seasons the optimizer never saw
(that check is the honest number: tuning always looks good on the data it was tuned on).
Writes data/model_nfl.json, which the app loads automatically.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import backtest, bayes, ratings  # noqa: E402


def show(label, m):
    s, t = m["spread"], m["total"]
    print(f"  {label:<22} {m['games']:>5} games | spread: {s['accuracy']:.1%} right, "
          f"ROI {s['roi']:+.1%}, logloss {s['logloss']:.4f} | total: {t['accuracy']:.1%} right, "
          f"ROI {t['roi']:+.1%}, logloss {t['logloss']:.4f} | moneyline logloss "
          f"{m['moneyline']['logloss']:.4f} (market alone: {m['moneyline']['market_logloss']:.4f})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-start", type=int, default=2012)
    parser.add_argument("--train-end", type=int, default=2023)
    parser.add_argument("--val-end", type=int, default=2025)
    parser.add_argument("--init", type=int, default=12, help="random settings tried first")
    parser.add_argument("--iters", type=int, default=60, help="Bayesian optimization steps")
    parser.add_argument("--out", default=str(ratings.DATA_DIR / "model_nfl.json"))
    args = parser.parse_args()

    print("Downloading games...")
    ds = backtest.build_dataset(backtest.download_games())
    train = backtest.subset(ds, range(args.train_start, args.train_end + 1))
    val = backtest.subset(ds, range(args.train_end + 1, args.val_end + 1))
    live = backtest.subset(ds, [args.val_end + 1])
    print(f"{len(train['result'])} training games, {len(val['result'])} validation, {len(live['result'])} this season so far")

    defaults = ratings.DEFAULTS["nfl"]
    print("Starting settings (not tuned):")
    show("training", backtest.evaluate(train, defaults))
    show("validation", backtest.evaluate(val, defaults))

    print(f"Tuning ({args.init} random tries + {args.iters} guided tries)...")
    best, score, history = bayes.optimize(backtest.objective(train), ratings.BOUNDS,
                                          n_init=args.init, n_iter=args.iters)
    print("Tuned settings:", {k: round(v, 3) for k, v in best.items()})
    metrics = {"train": backtest.evaluate(train, best), "validation": backtest.evaluate(val, best)}
    if len(live["result"]):
        metrics["current_season"] = backtest.evaluate(live, best)
    metrics["untuned_validation"] = backtest.evaluate(val, defaults)
    show("training", metrics["train"])
    show("validation", metrics["validation"])
    if "current_season" in metrics:
        show("this season so far", metrics["current_season"])

    report = {
        "sport": "nfl", "params": best, "metrics": metrics, "trained_at": date.today().isoformat(),
        "trained_on": f"{args.train_start}-{args.train_end}", "validated_on": f"{args.train_end + 1}-{args.val_end}",
        "tries": len(history), "breakeven_at_minus_110": 0.5238,
        # With n games, a 50/50 process still wanders this far from 50% about 1 time in 20.
        "accuracy_noise_pm": {k: round(1.96 * (0.25 / v["games"]) ** 0.5, 4)
                              for k, v in metrics.items() if k != "untuned_validation"},
    }
    Path(args.out).write_text(json.dumps(report, indent=2))
    print("Saved", args.out)


if __name__ == "__main__":
    main()
