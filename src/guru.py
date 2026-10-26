"""BetGuru's brain: turn today's games into legs, a no-bet list and parlays.

Pipeline: game lines + each team's recent form -> the model (src/ratings.py) gives every leg a
probability -> injury and data checks flag legs we don't trust -> the builder assembles parlays
for a chosen risk level.

Be aware of what this can and can't do. Backtests (scripts/train_weights.py) show recent form adds
almost nothing beyond the market's own prices, so the model's chances stay close to the book's.
BetGuru's value is discipline: skip legs with a key player out, avoid correlated legs, size the
risk, and show the real expected value (usually negative, because of the sportsbook's cut).
"""
import numpy as np
import pandas as pd

from src import nobet, ratings

MIN_GAMES = 5  # a team needs this many recent games before we model it
BLOWOUT = {"nfl": 14.0, "nba": 15.0}  # spreads this big are volatile, so we skip spread legs

# What each risk level will accept. "allow" is which flag severities are tolerated; "block"
# flags (QB out, thin data, blowout spread, your own list) are never allowed at any level.
PROFILES = {
    "Safe": {"min_p": 0.60, "allow": (), "rank": "p", "prop_support": 80,
             "blurb": "Only legs the model gives 60%+ and no injury flags. Short odds, fewer surprises."},
    "Balanced": {"min_p": 0.52, "allow": ("warn",), "rank": "balanced", "prop_support": 70,
                 "blurb": "Legs above 52%, ranked by how much the model likes them versus the price."},
    "Aggressive": {"min_p": 0.40, "allow": ("warn",), "rank": "edge", "prop_support": 60,
                   "blurb": "Underdogs allowed. Ranked by value versus the price, so bigger payouts and bigger misses."},
}
LEG_COLUMNS = ["GAME", "START", "MARKET", "PICK", "TEAM", "LINE", "PRICE", "P", "P_MARKET", "IMPLIED",
               "EDGE", "WHY", "FLAGS", "SEVERITY", "PLAYER", "SUPPORT"]
PROP_MIN_GAMES = 5  # a player needs this many recent games before a prop leg is considered
PROP_PREFIX = "Prop:"  # prop legs have MARKET like "Prop:player_points"
NO_BET_COLUMNS = ["WHO", "TEAM", "STATUS", "WHY", "SEVERITY", "SOURCE"]


def _isnum(x):
    return x is not None and not pd.isna(x)


def worst(flags):
    """The most serious severity in a list of flag dicts: 'block', 'warn' or None."""
    severities = {f["severity"] for f in flags}
    return "block" if "block" in severities else "warn" if "warn" in severities else None


# --- Flags from injuries ---

def flag_for_injury(injury):
    """A flag dict for one injured key player, or None if it isn't worth flagging.

    A quarterback who is Out or Doubtful blocks his team's legs. A Questionable QB, or any other
    skill player who is Out or Doubtful, is a caution. Everything else is ignored as too noisy.
    """
    who = f"{injury['name']} ({injury['position']}) {injury['status']}"
    status, position = injury["status"], injury["position"]
    if position == "QB" and status in ("Out", "Doubtful"):
        return {"reason": who, "severity": "block"}
    if position == "QB" or status in ("Out", "Doubtful"):
        return {"reason": who, "severity": "warn"}
    return None


def team_flags(teams, get_injuries):
    """Map team name -> list of flags. get_injuries(team) returns that team's injured key players."""
    flags = {}
    for team in teams:
        try:
            injuries = get_injuries(team) or []
        except Exception:
            injuries = []  # no report is "unknown", not "healthy", but we can't flag what we can't see
        found = [flag_for_injury(i) for i in injuries]
        flags[team] = [f for f in found if f]
    return flags


# --- Legs ---

def _leg(game, market, pick, team, line, price, p, p_market, why, flags, player=None, support=None):
    """One candidate leg. P is the model's chance; P_MARKET is the book's own chance with the vig removed.

    player and support are only for prop legs: the player, and the % of his last 10 games that cleared
    the line on this side (context for the filters, never used as a probability).
    """
    return {"GAME": game.GAME, "START": game.START, "MARKET": market, "PICK": pick, "TEAM": team,
            "LINE": line, "PRICE": price, "P": float(p), "P_MARKET": float(p_market),
            "IMPLIED": ratings.american_to_prob(price),
            "EDGE": float(p) - ratings.american_to_prob(price), "WHY": why, "FLAGS": flags,
            "SEVERITY": worst(flags), "PLAYER": player, "SUPPORT": support}


def build_legs(lines, form, params, flags, sport):
    """Every candidate leg (both sides of the moneyline, spread and total) for each modelled game.

    lines is odds.get_game_lines output, form maps team -> recent games, params are the model
    settings, flags maps team -> injury flags. Games where either team has fewer than MIN_GAMES
    recent games are skipped (they show up in the no-bet list instead).
    """
    rows = []
    for g in lines.itertuples():
        home, away = form.get(g.HOME) or [], form.get(g.AWAY) or []
        if len(home) < MIN_GAMES or len(away) < MIN_GAMES:
            continue
        pred = ratings.predict_game(home, away, params)
        em, et = pred["exp_margin"], pred["exp_total"]
        has_spread = _isnum(g.SPREAD_HOME)
        spread_home = float(g.SPREAD_HOME) if has_spread else -em  # no spread: no tilt
        market_p = float(ratings.market_home_prob(
            np.array([g.ML_HOME if _isnum(g.ML_HOME) else np.nan], dtype=float),
            np.array([g.ML_AWAY if _isnum(g.ML_AWAY) else np.nan], dtype=float),
            np.array([spread_home]))[0])
        p_home = float(ratings.p_home_win(em, spread_home, market_p, params))
        flags_home, flags_away = flags.get(g.HOME, []), flags.get(g.AWAY, [])
        both = flags_home + flags_away
        margin_txt = f"Model margin: {g.HOME} by {em:+.1f}" if em >= 0 else f"Model margin: {g.AWAY} by {-em:.1f}"

        if _isnum(g.ML_HOME) and _isnum(g.ML_AWAY):
            rows.append(_leg(g, "Moneyline", f"{g.HOME} to win", g.HOME, None, g.ML_HOME, p_home, market_p,
                             f"{margin_txt}. Win chance {p_home:.0%} (market {market_p:.0%}).", flags_home))
            rows.append(_leg(g, "Moneyline", f"{g.AWAY} to win", g.AWAY, None, g.ML_AWAY, 1 - p_home, 1 - market_p,
                             f"{margin_txt}. Win chance {1 - p_home:.0%} (market {1 - market_p:.0%}).", flags_away))

        if has_spread and _isnum(g.SPREAD_HOME_PRICE) and _isnum(g.SPREAD_AWAY_PRICE):
            base_home, base_away = ratings.devig(g.SPREAD_HOME_PRICE, g.SPREAD_AWAY_PRICE)
            p_cover = float(ratings.p_home_cover(em, spread_home, params, base=base_home))
            blowout = ([{"reason": f"Spread of {abs(spread_home):g} is a blowout line", "severity": "block"}]
                       if abs(spread_home) >= BLOWOUT[sport] else [])
            why = f"{margin_txt} against a line of {g.HOME} {spread_home:+g}."
            rows.append(_leg(g, "Spread", f"{g.HOME} {spread_home:+g}", g.HOME, spread_home,
                             g.SPREAD_HOME_PRICE, p_cover, base_home, why, flags_home + blowout))
            rows.append(_leg(g, "Spread", f"{g.AWAY} {-spread_home:+g}", g.AWAY, -spread_home,
                             g.SPREAD_AWAY_PRICE, 1 - p_cover, base_away, why, flags_away + blowout))

        if _isnum(g.TOTAL) and _isnum(g.OVER) and _isnum(g.UNDER):
            base_over, base_under = ratings.devig(g.OVER, g.UNDER)
            p_o = float(ratings.p_over(et, g.TOTAL, params, base=base_over))
            why = f"Model total: {et:.1f} points against a line of {g.TOTAL:g}."
            rows.append(_leg(g, "Total", f"Over {g.TOTAL:g}", None, g.TOTAL, g.OVER, p_o, base_over, why, both))
            rows.append(_leg(g, "Total", f"Under {g.TOTAL:g}", None, g.TOTAL, g.UNDER, 1 - p_o, base_under, why, both))
    return pd.DataFrame(rows, columns=LEG_COLUMNS)


def flag_for_player(player, info):
    """A flag for one prop player from an injury dict ({'status', 'injury'}), or None if he's fine/unknown.

    Out or Doubtful blocks the leg; any other status (Questionable, limited practice) is a caution.
    """
    status = (info or {}).get("status")
    if not status:
        return None
    return {"reason": f"{player} {status}", "severity": "block" if status in ("Out", "Doubtful") else "warn"}


def build_prop_legs(props, scan, odds_market, stat_label, team_flag_map, player_injury=None):
    """Over and under legs for player props, priced with the book's own fair odds.

    props is a FanDuel props table (PLAYER, GAME, LINE, OVER, UNDER, START), scan is the matching
    picks.scan_players result (each player's recent values). The chance of each side is the book's
    no-vig chance, the same as every other leg: we have no tested model for props, so we don't invent
    one. The recent hit rate goes in SUPPORT and only filters (see PROFILES). Flags come from the
    player's own injury status plus either team's flags (a quarterback out hurts his receivers too).
    player_injury(name) returns an injury dict or None; errors are treated as "unknown".
    """
    recent = dict(zip(scan["PLAYER"], scan["VALUES"]))
    rows = []
    for p in props.itertuples():
        values = recent.get(p.PLAYER)
        if not values or len(values) < PROP_MIN_GAMES or not (_isnum(p.LINE) and _isnum(p.OVER) and _isnum(p.UNDER)):
            continue
        try:
            info = player_injury(p.PLAYER) if player_injury else None
        except Exception:
            info = None
        own = flag_for_player(p.PLAYER, info)
        flags = ([own] if own else []) + [f for t in p.GAME.split(" @ ") for f in team_flag_map.get(t, [])]
        over, under = ratings.devig(p.OVER, p.UNDER)
        last = values[:10]
        for side, price, prob in (("Over", p.OVER, over), ("Under", p.UNDER, under)):
            hits = sum(v > p.LINE if side == "Over" else v < p.LINE for v in last)
            why = (f"Went {side.lower()} {p.LINE:g} in {hits} of his last {len(last)} games. The book's fair chance "
                   f"is {prob:.0%}; the hit rate is context, not a prediction.")
            rows.append(_leg(p, f"{PROP_PREFIX}{odds_market}", f"{p.PLAYER} {side} {p.LINE:g} {stat_label}", None,
                             p.LINE, price, prob, prob, why, flags, player=p.PLAYER,
                             support=round(100 * hits / len(last))))
    return pd.DataFrame(rows, columns=LEG_COLUMNS)


# --- No-bet list ---

def auto_no_bets(lines, form, flags, sport):
    """Players and games BetGuru won't trust today, each with a reason."""
    rows = []
    for team, team_flag_list in flags.items():
        for f in team_flag_list:
            why = (f"Legs on {team} and totals in this game are off the table."
                   if f["severity"] == "block" else "Caution: excluded from Safe parlays.")
            rows.append({"WHO": f["reason"].rsplit(" ", 1)[0], "TEAM": team,
                         "STATUS": f["reason"].rsplit(" ", 1)[1], "WHY": why,
                         "SEVERITY": f["severity"], "SOURCE": "Injury report"})
    for g in lines.itertuples():
        thin = [t for t in (g.HOME, g.AWAY) if len(form.get(t) or []) < MIN_GAMES]
        if thin:
            rows.append({"WHO": g.GAME, "TEAM": ", ".join(thin), "STATUS": "Thin data",
                         "WHY": f"Fewer than {MIN_GAMES} recent games for {', '.join(thin)}, so no model.",
                         "SEVERITY": "block", "SOURCE": "Data check"})
        if _isnum(g.SPREAD_HOME) and abs(g.SPREAD_HOME) >= BLOWOUT[sport]:
            rows.append({"WHO": g.GAME, "TEAM": "", "STATUS": "Blowout spread",
                         "WHY": f"A {abs(g.SPREAD_HOME):g}-point spread is volatile, so spread legs are skipped.",
                         "SEVERITY": "block", "SOURCE": "Data check"})
    return pd.DataFrame(rows, columns=NO_BET_COLUMNS)


def apply_user_list(legs, items, player_team=None):
    """Add a USER_REASON column: why your own no-bet list excludes each leg (None if it doesn't).

    items is nobet.list_items() output. A player entry blocks his team's game (needs player_team,
    a function from player name to team name, to work out which team).
    """
    teams = nobet.names("team", items)
    games = nobet.names("game", items)
    players = nobet.names("player", items)
    player_teams = {}
    for kind, name in items:
        if kind == "player" and player_team:
            try:
                team = player_team(name)
            except Exception:
                team = None
            if team:
                player_teams[team.lower()] = name

    def reason(leg):
        if isinstance(leg.PLAYER, str) and leg.PLAYER.lower() in players:  # a prop on a player you excluded
            return f"Your list: {leg.PLAYER}"
        game_teams = [t.lower() for t in leg.GAME.split(" @ ")]
        for t in game_teams:
            if t in teams:
                return f"Your list: {t.title()}"
            if t in player_teams:
                return f"Your list: {player_teams[t]}'s team"
        for g in games:
            if g in leg.GAME.lower():
                return f"Your list: {leg.GAME}"
        return None

    legs = legs.copy()
    legs["USER_REASON"] = [reason(r) for r in legs.itertuples()]
    return legs


# --- Parlays ---

def _rank(legs, how):
    if how == "p":
        return legs.sort_values("P", ascending=False)
    if how == "balanced":
        return legs.assign(SCORE=legs["EDGE"] + 0.5 * (legs["P"] - 0.5)).sort_values("SCORE", ascending=False)
    return legs.sort_values(["EDGE", "P"], ascending=False)


def build_parlay(legs, risk, n_legs):
    """Pick the best parlay for a risk level: at most one leg per game, never a blocked leg.

    Returns a dict with 'legs' (DataFrame), 'p_all' (the model's chance every leg hits, assuming
    independent games), 'decimal' and 'american' (the payout odds), and 'message' (set when there
    weren't enough legs). Two expected values per $100 staked:
    - 'ev_per_100' uses the book's own no-vig chances. It answers "what should I expect if BetGuru
      has no edge?", and it is the honest headline: it is never positive, only the vig compounding.
    - 'ev_model_per_100' uses the model's chances. Treat it with suspicion: ranking by disagreement
      with the book picks the model's biggest errors (the winner's curse), and backtests found no edge.
    """
    profile = PROFILES[risk]
    eligible = legs.copy()
    if "USER_REASON" in eligible:
        eligible = eligible[eligible["USER_REASON"].isna()]
    eligible = eligible[eligible["SEVERITY"].isna() | eligible["SEVERITY"].isin(profile["allow"])]
    eligible = eligible[eligible["P"] >= profile["min_p"]]
    is_prop = eligible["MARKET"].str.startswith(PROP_PREFIX)
    eligible = eligible[~is_prop | (eligible["SUPPORT"] >= profile["prop_support"])]  # props must also be consistent

    chosen, used = [], set()
    for leg in _rank(eligible, profile["rank"]).itertuples():
        if leg.GAME in used:
            continue
        chosen.append(leg._asdict())
        used.add(leg.GAME)
        if len(chosen) == n_legs:
            break
    picked = pd.DataFrame(chosen).drop(columns=["Index", "SCORE"], errors="ignore")
    if len(picked) < 2:
        return {"legs": picked, "p_all": None, "decimal": None, "american": None, "ev_per_100": None,
                "ev_model_per_100": None,
                "message": f"Not enough legs meet the {risk} rules today (found {len(picked)})."}
    p_all = float(picked["P"].prod())
    p_market = float(picked["P_MARKET"].prod())
    decimal = float(np.prod([ratings.american_to_decimal(x) for x in picked["PRICE"]]))
    return {"legs": picked, "p_all": p_all, "decimal": decimal,
            "american": ratings.decimal_to_american(decimal),
            "ev_per_100": p_market * (decimal - 1) * 100 - (1 - p_market) * 100,
            "ev_model_per_100": p_all * (decimal - 1) * 100 - (1 - p_all) * 100,
            "message": (f"Only {len(picked)} legs qualified, fewer than the {n_legs} you asked for."
                        if len(picked) < n_legs else "")}
