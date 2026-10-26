import pandas as pd
import pytest

from src import guru, nobet, odds, ratings, stats_nfl, store

P = {**ratings.DEFAULTS["nfl"], "k_spread": 0.1, "k_total": 0.05, "k_ml": 0.1}


def games(margin, total=44, n=10):
    """n identical past games for a team that wins by `margin` with `total` combined points."""
    f = (total + margin) / 2
    return [{"for": f, "against": total - f}] * n


def lines_df(*rows):
    base = dict(START="2099-01-01T00:00:00Z", ML_HOME=-200, ML_AWAY=170, SPREAD_HOME=-4.5,
                SPREAD_HOME_PRICE=-110, SPREAD_AWAY_PRICE=-110, TOTAL=44.5, OVER=-110, UNDER=-110)
    out = []
    for home, away, extra in rows:
        out.append({**base, "GAME": f"{away} @ {home}", "HOME": home, "AWAY": away, **extra})
    return pd.DataFrame(out, columns=odds.LINE_COLUMNS)


FORM = {"Hawks": games(+10), "Owls": games(-10), "Bears": games(+3), "Lions": games(0)}


def test_six_legs_per_game_with_matching_picks():
    legs = guru.build_legs(lines_df(("Hawks", "Owls", {})), FORM, P, {}, "nfl")
    assert len(legs) == 6 and set(legs["MARKET"]) == {"Moneyline", "Spread", "Total"}
    picks = set(legs["PICK"])
    assert {"Hawks to win", "Owls to win", "Hawks -4.5", "Owls +4.5", "Over 44.5", "Under 44.5"} == picks
    spread = legs[legs["MARKET"] == "Spread"].set_index("TEAM")
    assert spread.loc["Hawks", "P"] + spread.loc["Owls", "P"] == pytest.approx(1.0)
    assert spread.loc["Hawks", "P"] > 0.5  # strong home team vs a -4.5 line
    ml = legs[legs["MARKET"] == "Moneyline"].set_index("TEAM")
    assert ml.loc["Hawks", "P"] > ml.loc["Owls", "P"]
    assert (legs["EDGE"] == legs["P"] - legs["IMPLIED"]).all()


def test_teams_with_too_little_data_are_skipped_and_listed():
    form = {**FORM, "Owls": games(-10, n=3)}
    lines = lines_df(("Hawks", "Owls", {}), ("Bears", "Lions", {}))
    legs = guru.build_legs(lines, form, P, {}, "nfl")
    assert set(legs["GAME"]) == {"Lions @ Bears"}
    nb = guru.auto_no_bets(lines, form, {}, "nfl")
    row = nb[nb["STATUS"] == "Thin data"].iloc[0]
    assert row["WHO"] == "Owls @ Hawks" and row["SEVERITY"] == "block"


def test_blowout_spread_blocks_spread_legs_only():
    lines = lines_df(("Hawks", "Owls", {"SPREAD_HOME": -17.0}))
    legs = guru.build_legs(lines, FORM, P, {}, "nfl")
    assert (legs[legs["MARKET"] == "Spread"]["SEVERITY"] == "block").all()
    assert legs[legs["MARKET"] != "Spread"]["SEVERITY"].isna().all()
    assert (guru.auto_no_bets(lines, FORM, {}, "nfl")["STATUS"] == "Blowout spread").any()


def test_injury_flags_and_how_they_reach_legs():
    qb_out = {"name": "Sam Qb", "position": "QB", "status": "Out", "injury": "Knee"}
    wr_q = {"name": "Wide Rec", "position": "WR", "status": "Questionable", "injury": None}
    wr_out = {"name": "Wide Out", "position": "WR", "status": "Out", "injury": None}
    qb_q = {"name": "Sam Qb", "position": "QB", "status": "Questionable", "injury": None}
    assert guru.flag_for_injury(qb_out)["severity"] == "block"
    assert guru.flag_for_injury(qb_q)["severity"] == "warn"
    assert guru.flag_for_injury(wr_out)["severity"] == "warn"
    assert guru.flag_for_injury(wr_q) is None  # a Questionable receiver is too noisy to flag

    flags = guru.team_flags(["Hawks", "Owls"], lambda t: [qb_out] if t == "Owls" else [])
    assert flags["Hawks"] == [] and flags["Owls"][0]["severity"] == "block"
    legs = guru.build_legs(lines_df(("Hawks", "Owls", {})), FORM, P, flags, "nfl")
    by_pick = legs.set_index("PICK")["SEVERITY"]
    assert by_pick["Owls to win"] == "block" and by_pick["Owls +4.5"] == "block"
    assert pd.isna(by_pick["Hawks to win"])           # his own team's legs stay clean
    assert by_pick["Over 44.5"] == "block"            # totals are flagged from either team
    nb = guru.auto_no_bets(lines_df(("Hawks", "Owls", {})), FORM, flags, "nfl")
    assert nb.iloc[0]["WHO"] == "Sam Qb (QB)" and nb.iloc[0]["STATUS"] == "Out"


def test_failed_injury_lookup_just_means_no_flags():
    def boom(team):
        raise RuntimeError("no report")
    assert guru.team_flags(["Hawks"], boom) == {"Hawks": []}


def test_user_list_blocks_teams_games_and_players_teams():
    legs = guru.build_legs(lines_df(("Hawks", "Owls", {}), ("Bears", "Lions", {})), FORM, P, {}, "nfl")
    out = guru.apply_user_list(legs, [("team", "owls")])
    assert out[out["GAME"] == "Owls @ Hawks"]["USER_REASON"].notna().all()
    assert out[out["GAME"] == "Lions @ Bears"]["USER_REASON"].isna().all()
    out = guru.apply_user_list(legs, [("game", "Lions @ Bears")])
    assert out[out["GAME"] == "Lions @ Bears"]["USER_REASON"].notna().all()
    out = guru.apply_user_list(legs, [("player", "Star Qb")], player_team=lambda n: "Bears")
    assert out[out["GAME"] == "Lions @ Bears"]["USER_REASON"].iloc[0] == "Your list: Star Qb's team"
    out = guru.apply_user_list(legs, [("player", "Star Qb")], player_team=lambda n: None)
    assert out["USER_REASON"].isna().all()  # can't tell the team, so nothing is blocked


def slate():
    lines = lines_df(("Hawks", "Owls", {}), ("Bears", "Lions", {"ML_HOME": -130, "ML_AWAY": 110}))
    return guru.apply_user_list(guru.build_legs(lines, FORM, P, {}, "nfl"), [])


def test_parlay_takes_one_leg_per_game_and_multiplies_probabilities():
    out = guru.build_parlay(slate(), "Balanced", 2)
    legs = out["legs"]
    assert len(legs) == 2 and legs["GAME"].nunique() == 2
    assert out["p_all"] == pytest.approx(legs["P"].prod())
    decimal = 1.0
    for price in legs["PRICE"]:
        decimal *= ratings.american_to_decimal(price)
    assert out["decimal"] == pytest.approx(decimal)
    # The headline EV uses the book's own no-vig chances; the model-based one is kept separately.
    pm = legs["P_MARKET"].prod()
    assert out["ev_per_100"] == pytest.approx(pm * (decimal - 1) * 100 - (1 - pm) * 100)
    assert out["ev_model_per_100"] == pytest.approx(
        out["p_all"] * (decimal - 1) * 100 - (1 - out["p_all"]) * 100)
    assert out["message"] == ""


def test_safe_is_stricter_than_aggressive():
    safe = guru.build_parlay(slate(), "Safe", 3)
    assert (safe["legs"]["P"] >= 0.60).all()
    # Only one leg in this slate clears 60%, so Safe says so instead of padding the parlay.
    assert len(safe["legs"]) == 1 and "Not enough legs" in safe["message"] and safe["p_all"] is None
    aggressive = guru.build_parlay(slate(), "Aggressive", 2)
    assert len(aggressive["legs"]) == 2 and aggressive["message"] == ""


def test_blocked_and_user_excluded_legs_never_make_a_parlay():
    qb_out = [{"name": "Sam Qb", "position": "QB", "status": "Out", "injury": None}]
    flags = guru.team_flags(["Hawks", "Owls", "Bears", "Lions"], lambda t: qb_out if t == "Hawks" else [])
    legs = guru.build_legs(lines_df(("Hawks", "Owls", {}), ("Bears", "Lions", {})), FORM, P, flags, "nfl")
    legs = guru.apply_user_list(legs, [("team", "Lions")])
    # Hawks' game: legs on Hawks and the total are blocked; the Owls-side legs aren't flagged.
    # Lions' game: everything is excluded by your list.
    for risk in guru.PROFILES:
        out = guru.build_parlay(legs, risk, 3)
        assert "Lions" not in " ".join(out["legs"].get("GAME", []))
        assert (out["legs"].get("SEVERITY", pd.Series(dtype=object)) != "block").all()


def test_not_enough_legs_gives_a_message_not_a_crash():
    out = guru.build_parlay(slate().iloc[0:0], "Safe", 3)
    assert out["p_all"] is None and "Not enough legs" in out["message"]


def test_user_nobet_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "state.db")
    assert nobet.list_items() == []
    assert nobet.add("team", "  Kansas   City Chiefs ") and nobet.add("player", "Sam Qb")
    assert not nobet.add("team", "   ") and not nobet.add("fish", "x")
    nobet.add("team", "Kansas City Chiefs")  # duplicates are ignored
    assert nobet.list_items() == [("team", "Kansas City Chiefs"), ("player", "Sam Qb")]
    assert nobet.names("team") == {"kansas city chiefs"}
    nobet.remove("team", "Kansas City Chiefs")
    assert nobet.list_items() == [("player", "Sam Qb")]


def test_nfl_team_injuries_and_player_team(monkeypatch):
    def row(name, team, pos, status, injury=None):
        return {"week": 7, "team": team, "position": pos, "full_name": name, "report_status": status,
                "report_primary_injury": injury, "practice_status": "Full Participation in Practice"}
    rows = [row("Sam Qb", "KC", "QB", "Questionable", "Hand"), row("Wide Out", "KC", "WR", "Out", "Knee"),
            row("Big Lineman", "KC", "OT", "Out"), row("Other Team", "DEN", "RB", "Out"),
            row("Fine Guy", "KC", "TE", None)]
    monkeypatch.setattr(stats_nfl, "_download_injuries", lambda season: rows)
    monkeypatch.setattr(stats_nfl, "_team_names", lambda: {"KC": "Kansas City Chiefs", "DEN": "Denver Broncos"})
    stats_nfl._load_injuries.cache_clear()
    got = stats_nfl.get_team_injuries("Kansas City Chiefs")
    assert [(p["name"], p["status"]) for p in got] == [("Wide Out", "Out"), ("Sam Qb", "Questionable")]
    assert stats_nfl.get_team_injuries("Nowhere") == []


def test_headline_ev_can_never_show_profit_even_when_the_model_disagrees_wildly():
    # A model that is certain about everything (huge tilts) still can't make the headline EV positive,
    # because that number is built from the book's own chances.
    wild = {**P, "k_spread": 5.0, "k_total": 5.0, "k_ml": 5.0}
    lines = lines_df(("Hawks", "Owls", {}), ("Bears", "Lions", {}), ("Hawks", "Lions", {}))
    legs = guru.apply_user_list(guru.build_legs(lines, FORM, wild, {}, "nfl"), [])
    for risk in guru.PROFILES:
        out = guru.build_parlay(legs, risk, 2)
        if out["p_all"] is not None:
            assert out["ev_per_100"] <= 0
    aggressive = guru.build_parlay(legs, "Aggressive", 2)
    assert aggressive["ev_model_per_100"] > 0  # the model "sees" profit; the headline refuses to


def test_untrained_nba_model_has_no_tilt_so_it_matches_the_market():
    nba = ratings.load_params("nba")
    assert nba["k_spread"] == nba["k_total"] == nba["k_ml"] == 0.0
    lines = lines_df(("Hawks", "Owls", {"ML_HOME": -140, "ML_AWAY": 120, "SPREAD_HOME_PRICE": -120,
                                         "SPREAD_AWAY_PRICE": 100}))
    legs = guru.build_legs(lines, FORM, nba, {}, "nba")
    assert (legs["P"] - legs["P_MARKET"]).abs().max() < 1e-9
    spread = legs[legs["MARKET"] == "Spread"].set_index("TEAM")
    assert spread.loc["Hawks", "P"] == pytest.approx(0.5217, abs=1e-3)  # -120 implies 54.5% and +100 implies 50%; without the vig it's 52.2%, not a flat 50%
