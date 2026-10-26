import pandas as pd
import pytest

from src import guru, lotto, ratings


def leg(game, pick, price, p_market, **extra):
    row = {"GAME": game, "START": "2099-01-01T00:00:00Z", "MARKET": "Moneyline", "PICK": pick, "TEAM": pick,
           "LINE": None, "PRICE": price, "P": p_market, "P_MARKET": p_market, "IMPLIED": ratings.american_to_prob(price),
           "EDGE": 0.0, "WHY": "", "FLAGS": [], "SEVERITY": None, "PLAYER": None, "SUPPORT": None}
    return {**row, **extra}


def slate(n_games, price=-110, p=0.5):
    return pd.DataFrame([leg(f"G{i}", f"pick{i}", price, p) for i in range(n_games)], columns=guru.LEG_COLUMNS)


def test_a_dozen_even_money_legs_reach_a_thousand_dollars_on_fifty_cents():
    ticket = lotto.build_lotto(slate(14), stake=0.50, target_profit=1000)
    assert ticket["message"] == ""
    # The target is 2,001x. Eleven -110 legs reach about 1,226x and twelve reach about 2,340x, so it takes 12.
    assert ticket["profit"] >= 1000 and len(ticket["legs"]) == 12
    assert ticket["decimal"] == pytest.approx(1.9091 ** 12, rel=1e-3)
    assert ticket["one_in"] == pytest.approx(2 ** 12)
    assert ticket["ev"] < 0 and ticket["american"] > 100000


def test_it_uses_only_as_many_legs_as_needed():
    ticket = lotto.build_lotto(slate(20), stake=0.50, target_profit=100)  # 201x: 8 legs reach 176x, 9 reach 336x
    assert len(ticket["legs"]) == 9 and ticket["profit"] >= 100
    assert ticket["profit"] < 100 * 1.9091  # never one more leg than needed


def test_drops_the_least_likely_leg_it_does_not_need():
    legs = pd.DataFrame([leg("G1", "a", 100, 0.50), leg("G2", "b", 100, 0.50), leg("G3", "c", 100, 0.50),
                         leg("G4", "d", 100, 0.50), leg("G5", "long shot", 900, 0.09)], columns=guru.LEG_COLUMNS)
    ticket = lotto.build_lotto(legs, stake=1.0, target_profit=7)  # needs 8x: three even legs, or the long shot alone
    picks = set(ticket["legs"]["PICK"])
    assert ticket["profit"] >= 7 and picks == {"a", "b", "c"}  # likelier than risking the 9% long shot


def test_one_leg_per_game_with_the_best_priced_side():
    legs = pd.DataFrame([leg("G1", "good price", -105, 0.5), leg("G1", "bad price", -130, 0.5),
                         leg("G2", "x", -110, 0.5), leg("G3", "y", -110, 0.5)], columns=guru.LEG_COLUMNS)
    ticket = lotto.build_lotto(legs, stake=1.0, target_profit=2)
    assert ticket["legs"]["GAME"].is_unique and "good price" in set(ticket["legs"]["PICK"])
    assert "bad price" not in set(ticket["legs"]["PICK"])


def test_not_enough_games_says_so_and_still_returns_the_best_ticket():
    ticket = lotto.build_lotto(slate(3), stake=0.50, target_profit=1000)
    assert "can't reach $1,000" in ticket["message"] and len(ticket["legs"]) == 3
    assert ticket["profit"] == pytest.approx(0.5 * (1.9091 ** 3 - 1), rel=1e-3)


def test_flagged_excluded_and_inconsistent_legs_are_never_used():
    legs = slate(18)  # 14 are usable once four are excluded below, and 12 are needed
    legs.loc[0, "SEVERITY"] = "warn"       # even a caution keeps a leg off the lotto
    legs.loc[1, "SEVERITY"] = "block"
    legs["USER_REASON"] = None
    legs.loc[2, "USER_REASON"] = "Your list: Chiefs"
    legs.loc[3, ["MARKET", "SUPPORT", "PLAYER"]] = ["Prop:player_points", 50, "Streaky"]  # under Aggressive's 60%
    ticket = lotto.build_lotto(legs, stake=0.50, target_profit=1000)
    assert not {"pick0", "pick1", "pick2", "pick3"} & set(ticket["legs"]["PICK"])
    assert ticket["message"] == "" and len(ticket["legs"]) == 12


def test_one_game_cannot_make_a_ticket():
    ticket = lotto.build_lotto(slate(1), stake=0.50, target_profit=1000)
    assert ticket["p_all"] is None and "needs at least two legs" in ticket["message"]


def test_no_legs_at_all():
    ticket = lotto.build_lotto(slate(0), stake=0.50, target_profit=1000)
    assert ticket["p_all"] is None and "No legs" in ticket["message"]


def test_more_legs_per_game_lets_a_small_slate_reach_the_payout():
    games = []
    for i in range(6):  # six games, each with a side and a total at -110
        games.append(leg(f"G{i}", f"side{i}", -110, 0.5))
        games.append(leg(f"G{i}", f"total{i}", -110, 0.5, MARKET="Total"))
    legs = pd.DataFrame(games, columns=guru.LEG_COLUMNS)
    one = lotto.build_lotto(legs, stake=0.50, target_profit=1000, per_game=1)
    two = lotto.build_lotto(legs, stake=0.50, target_profit=1000, per_game=2)
    assert "can't reach" in one["message"] and len(one["legs"]) == 6                  # six games, one leg each
    assert two["message"] == "" and len(two["legs"]) == 12 and two["profit"] >= 1000  # a side and a total in each
    assert two["legs"]["GAME"].value_counts().max() == 2
