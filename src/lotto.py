"""The BetGuru lotto: a long-shot parlay priced to pay a big amount on a small stake.

Say $0.50 to win $1,000. That is odds of 2,000 to 1, so it takes about a dozen legs, and the chance of
hitting them all is tiny. It's meant as a bit of fun, like a lottery ticket, so the numbers are shown plainly.

How the ticket is chosen: from each game keep the leg with the best price for its risk, line them up best
price first until the payout is big enough, then drop any leg that isn't needed (starting with the least
likely one) so the ticket is as likely to hit as it can be while still paying what you asked for.
"""
import math

import pandas as pd

from src import guru, ratings

LOTTO_RISK = "Lotto"  # the risk label saved to the results record


def _efficiency(leg):
    """How much payout a leg buys per unit of risk: ln(decimal odds) / -ln(fair chance). 1.0 would be fair."""
    decimal = ratings.american_to_decimal(leg.PRICE)
    return math.log(decimal) / -math.log(leg.P_MARKET)


def build_lotto(legs, stake=0.50, target_profit=1000.0, per_game=1):
    """Build the ticket from candidate legs (guru.build_legs / build_prop_legs output).

    per_game is how many legs one game may contribute (see guru.legs_conflict for the pairs that are never
    allowed together). Legs from one game are linked, so the chance shown is only an estimate.

    Returns a dict with 'legs', 'decimal', 'american', 'profit' (what a win pays on top of the stake),
    'p_all' (the book's fair chance every leg hits), 'one_in', 'ev' (expected profit per ticket, always
    negative), and 'message' (set when today's games can't reach the target). Legs with any injury flag,
    on your no-bet list, or props that aren't consistent are never used.
    """
    target_decimal = target_profit / stake + 1
    eligible = legs[legs["SEVERITY"].isna()]
    if "USER_REASON" in eligible:
        eligible = eligible[eligible["USER_REASON"].isna()]
    is_prop = eligible["MARKET"].str.startswith(guru.PROP_PREFIX)
    eligible = eligible[~is_prop | (eligible["SUPPORT"] >= guru.PROFILES["Aggressive"]["prop_support"])]
    eligible = eligible[(eligible["P_MARKET"] > 0) & (eligible["P_MARKET"] < 1)]
    if eligible.empty:
        return {"legs": eligible, "decimal": None, "american": None, "profit": None, "p_all": None,
                "one_in": None, "ev": None, "message": "No legs are available for a ticket right now."}

    # Best price for the risk first, taking at most per_game compatible legs from each game.
    usable, by_game = [], {}
    for leg in sorted(eligible.itertuples(), key=_efficiency, reverse=True):
        in_game = by_game.setdefault(leg.GAME, [])
        if len(in_game) < per_game and not any(guru.legs_conflict(leg, other) for other in in_game):
            in_game.append(leg)
            usable.append(leg)
    if len(usable) < 2:
        return {"legs": eligible.iloc[0:0], "decimal": None, "american": None, "profit": None, "p_all": None,
                "one_in": None, "ev": None,
                "message": "A lotto ticket needs at least two legs. Build the other sport's slate, or allow more legs per game."}

    chosen, decimal = [], 1.0
    for leg in usable:
        chosen.append(leg)
        decimal *= ratings.american_to_decimal(leg.PRICE)
        if decimal >= target_decimal:
            break
    reached = decimal >= target_decimal

    if reached:  # drop legs we don't need, least likely first, so the ticket hits as often as possible
        trimmed = True
        while trimmed and len(chosen) > 2:
            trimmed = False
            for leg in sorted(chosen, key=lambda l: l.P_MARKET):
                rest = decimal / ratings.american_to_decimal(leg.PRICE)
                if rest >= target_decimal:
                    chosen.remove(leg)
                    decimal = rest
                    trimmed = True
                    break

    ticket = pd.DataFrame([leg._asdict() for leg in chosen]).drop(columns=["Index", "SCORE"], errors="ignore")
    p_all = float(ticket["P_MARKET"].prod())
    profit = stake * (decimal - 1)
    message = ""
    if not reached:
        message = (f"Today's games can't reach ${target_profit:,.0f} on ${stake:.2f}: the best ticket pays "
                   f"${profit:,.2f}. Build the other sport's slate or load props to add more legs.")
    return {"legs": ticket, "decimal": decimal, "american": ratings.decimal_to_american(decimal), "profit": profit,
            "p_all": p_all, "one_in": 1 / p_all, "ev": p_all * profit - (1 - p_all) * stake, "message": message}
