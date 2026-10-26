"""The BetGuru tab: today's slate, the parlay for your risk level, game talks, no-bet list, record.

Streamlit reruns the whole script on every click, so anything slow (loading lines, scanning teams)
is saved in st.session_state and everything else is recomputed instantly from it.
"""
import pandas as pd
import streamlit as st

from src import games, guru, nobet, odds, ratings, results, stats_nba, stats_nfl, store, talks
from src.ui_common import load_cost, quota_left, show_cost

# What differs between sports: where the lines come from, how far ahead to look, and where each
# team's recent games, injuries and final scores come from. NBA injuries aren't wired up yet.
SPORTS = {
    "NFL": {"code": "nfl", "odds": odds.NFL, "hours": 24, "team_games": stats_nfl.get_team_games,
            "injuries": stats_nfl.get_team_injuries, "player_team": stats_nfl.get_player_team,
            "get_final": stats_nfl.get_final, "pause": 0, "markets": stats_nfl.MARKETS,
            "player_injury": stats_nfl.get_injury, "get_stat": stats_nfl.get_player_stat},
    "NBA": {"code": "nba", "odds": odds.NBA, "hours": 24, "team_games": stats_nba.get_team_games,
            "injuries": None, "player_team": None, "get_final": stats_nba.get_final, "pause": 0,
            "markets": stats_nba.MARKETS, "player_injury": stats_nba.get_injury,
            "get_stat": stats_nba.get_player_stat},
}
FINALS = {cfg["code"]: cfg["get_final"] for cfg in SPORTS.values()}
STATS = {cfg["code"]: cfg["get_stat"] for cfg in SPORTS.values()}


def loaded_prop_legs(cfg, state):
    """Prop legs from the props you've already loaded and scanned in the NBA/NFL props tabs.

    Only games on today's slate count, and it costs no Odds API requests: the props are already here.
    Returns (legs DataFrame, list of prop labels that contributed).
    """
    code = cfg["code"]
    slate_games = set(state["lines"]["GAME"])
    frames, labels = [], []
    for market, (_, label) in cfg["markets"].items():
        loaded = st.session_state.get(f"{code}_{market}_props")
        scanned = st.session_state.get(f"{code}_{market}_scan")
        if not loaded or not scanned:
            continue
        props, scan = loaded[0], scanned[0]
        props = props[props["GAME"].isin(slate_games)]
        if props.empty or scan.empty:
            continue
        legs = guru.build_prop_legs(props, scan, market, label, state["flags"], cfg["player_injury"])
        if not legs.empty:
            frames.append(legs)
            labels.append(label)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=guru.LEG_COLUMNS)), labels


def show_storage(where):
    """Say where your no-bet list and record are saved, with a button to test the connection."""
    db = store.get_store()
    if db.durable:
        st.success(f"Your no-bet list and record are saved in {db.name}.")
    else:
        st.warning(f"Your no-bet list and record are saved in {db.name}. Connect Supabase (see the README) "
                   "to keep them for good.")
    if st.button("Check storage connection", key=f"bg_check_{where}"):
        try:
            db.check()
            st.success("Storage works.")
        except store.StoreError as e:
            st.error(str(e))


def build_slate(cfg):
    """Load the lines, scan every team's recent games and check injuries. Saved by the caller."""
    lines, remaining = odds.get_game_lines(cfg["odds"], hours=cfg["hours"])
    quota_left.clear()  # the balance just changed
    bar = st.progress(0.0, text="Scanning teams...")
    form, errors = games.scan_teams(
        lines, cfg["team_games"], pause=cfg["pause"],
        progress=lambda done, total: bar.progress(done / total, text=f"{done}/{total} teams"),
    )
    bar.empty()
    teams = sorted(set(lines["HOME"]) | set(lines["AWAY"]))
    flags = guru.team_flags(teams, cfg["injuries"]) if cfg["injuries"] else {t: [] for t in teams}
    return {"lines": lines, "form": form, "errors": errors, "flags": flags, "remaining": remaining}


def show_parlay(code, risk, parlay):
    if parlay["message"]:
        st.info(parlay["message"])
    legs = parlay["legs"]
    if parlay["p_all"] is None:
        return
    a, b, c = st.columns(3)
    a.metric("Chance every leg hits", f"{parlay['p_all']:.0%}")
    b.metric("Pays (American odds)", f"{parlay['american']:+d}")
    c.metric("Expected value per $100 (fair odds)", f"{parlay['ev_per_100']:+.0f}")
    for leg in legs.itertuples():
        st.markdown(f"**{leg.PICK}** ({leg.PRICE:+.0f}, {leg.P:.0%}) - {leg.GAME}")
        st.caption(leg.WHY)
        for flag in leg.FLAGS:
            st.caption(f"⚠️ {flag['reason']}")
    st.caption("Expected value is what you should expect on average if BetGuru has no edge: the book's own "
               "fair chances against the real prices. It is always negative, because the sportsbook takes a "
               "cut on every leg and the cut multiplies with each added leg.")
    st.caption(f"If you trusted the model's chances instead, the number would be {parlay['ev_model_per_100']:+.0f}. "
               "Don't: that figure comes from where the model disagrees with the book, and backtests found those "
               "disagreements aren't real edge. BetGuru can't promise a winner; it avoids legs it doesn't "
               "trust and shows you the real math.")
    if st.button("Save this parlay to my record", key=f"bg_{code}_save"):
        try:
            results.log_parlay(code, risk, legs)
            st.success("Saved. Grade finished games on the Model and record tab to see how it did.")
        except store.StoreError as e:
            st.error(f"Couldn't save the parlay: {e}")


def show_talks(key, state, params):
    lines, form, flags = state["lines"], state["form"], state["flags"]
    talks_done = st.session_state.setdefault(f"{key}_talks", {})
    st.caption("A short team-vs-team preview of each game, written by Claude from the lines, each team's "
               "recent form and the injury report. It can only use those facts.")
    if st.button("Write the game talks (Claude Haiku)", key=f"{key}_talks_btn"):
        for g in lines.itertuples():
            if g.HOME not in form or g.AWAY not in form:
                continue
            try:
                talks_done[g.GAME] = talks.get_talk(g.GAME, talks.game_facts(g, form, params, flags))
            except Exception as e:
                st.error(f"Couldn't write the talks: {e}")
                break
    for g in lines.itertuples():
        with st.expander(g.GAME):
            if g.HOME not in form or g.AWAY not in form:
                st.write("Not enough recent games for one of these teams, so BetGuru skips this game.")
                continue
            st.write(talks_done.get(g.GAME) or "Press the button above to write this talk.")
            st.markdown("**What it's based on**")
            st.markdown("\n".join(f"- {fact}" for fact in talks.game_facts(g, form, params, flags)))


def show_no_bets(state, legs_teams):
    lines, form, flags = state["lines"], state["form"], state["flags"]
    st.subheader("BetGuru's no-bet list")
    st.caption("Players and games BetGuru won't build a parlay around, and why. A quarterback who is "
               "Out or Doubtful blocks his team's legs; other injured skill players add a caution; thin data "
               "and blowout spreads are skipped.")
    auto = guru.auto_no_bets(lines, form, flags, st.session_state["bg_code"])
    if auto.empty:
        st.success("Nothing flagged today.")
    else:
        st.dataframe(auto, hide_index=True)
    if st.session_state["bg_code"] == "nba":
        st.caption("NBA injury flags aren't wired up yet, so only data checks show for the NBA.")

    st.subheader("Your no-bet list")
    st.caption("Teams, players or games you never want in a parlay. A player blocks his team's game. "
               "Players on your list are also hidden from the player-props 5/5 parlays. The list is "
               "shared by everyone using this app and can reset when the app restarts.")
    show_storage("nobet")
    kind = st.radio("Add a", list(nobet.KINDS), horizontal=True, key="bg_nb_kind")
    if kind == "team":
        value = st.selectbox("Team", legs_teams, key="bg_nb_team")
    elif kind == "game":
        value = st.selectbox("Game", list(lines["GAME"]), key="bg_nb_game")
    else:
        value = st.text_input("Player name", placeholder="e.g. Patrick Mahomes", key="bg_nb_player")
    try:
        if st.button("Add to my list", key="bg_nb_add") and nobet.add(kind, value or ""):
            st.rerun()
        for item_kind, name in nobet.list_items():
            left, right = st.columns([4, 1])
            left.write(f"**{item_kind.title()}:** {name}")
            if right.button("Remove", key=f"bg_nb_rm_{item_kind}_{name}"):
                nobet.remove(item_kind, name)
                st.rerun()
    except store.StoreError as e:
        st.error(f"Couldn't update your no-bet list: {e}")


def show_model(code):
    info = ratings.load_model_info(code)
    st.subheader("How the model is doing")
    if info:
        val = info["metrics"]["validation"]
        noise = info["accuracy_noise_pm"]["validation"]
        st.caption(f"Tuned with Bayesian optimization on NFL seasons {info['trained_on']} using real "
                   f"historical lines, then checked on {info['validated_on']} ({val['games']} games it never "
                   f"saw). Break-even at -110 odds is 52.4% right.")
        table = pd.DataFrame([
            {"MARKET": "Spread", "RIGHT": f"{val['spread']['accuracy']:.1%} ± {noise:.1%}",
             "ROI AT -110": f"{val['spread']['roi']:+.1%}", "LOG-LOSS": f"{val['spread']['logloss']:.4f}"},
            {"MARKET": "Total", "RIGHT": f"{val['total']['accuracy']:.1%} ± {noise:.1%}",
             "ROI AT -110": f"{val['total']['roi']:+.1%}", "LOG-LOSS": f"{val['total']['logloss']:.4f}"},
            {"MARKET": "Moneyline", "RIGHT": f"{val['moneyline']['accuracy']:.1%}", "ROI AT -110": "n/a",
             "LOG-LOSS": f"{val['moneyline']['logloss']:.4f} (market alone: {val['moneyline']['market_logloss']:.4f})"},
        ])
        st.dataframe(table, hide_index=True)
        st.info("The honest read: recent team form adds almost nothing beyond what the betting lines already "
                "price in. The optimizer shrank the model's tilts to near zero, so BetGuru's chances stay "
                "close to the book's. Differences from 50% inside the ± range are noise. BetGuru's value is "
                "discipline and transparency, not a secret edge.")
        with st.expander("Tuned settings"):
            st.json({k: round(v, 3) for k, v in info["params"].items()})
    else:
        st.warning("The NBA model hasn't been trained: there are no free historical NBA lines to test it on. "
                   "Until its own saved results (below) give it something to learn from, its chances are "
                   "exactly the book's, so the parlay is about avoiding flagged legs and finding the best "
                   "prices, not about beating the market.")

    st.subheader("Record")
    st.caption("Every parlay you save is graded against the final scores. The calibration table shows "
               "whether legs the model rated, say, 60-70% really won that often.")
    show_storage("record")
    if st.button("Grade finished games", key=f"bg_{code}_grade"):
        try:
            n = results.grade_pending(
                lambda sport, home, away, start: FINALS[sport](home, away, start),
                get_stat=lambda sport, player, market, home, away, start: STATS[sport](player, market, home, away, start))
            st.success(f"Graded {n} legs.")
        except Exception as e:  # network, storage or API trouble
            st.error(f"Couldn't grade right now: {e}")
    try:
        pr = results.parlay_record()
        rec = results.record()
        calibration = results.calibration()
    except store.StoreError as e:
        st.error(f"Couldn't load your record: {e}")
        return
    st.write(f"Parlays: {pr['won']} won, {pr['lost']} lost, {pr['pending']} waiting.")
    if rec.empty:
        st.caption("No graded legs yet. Save a parlay and grade it after the games finish.")
    else:
        st.dataframe(rec, hide_index=True)
        st.dataframe(calibration, hide_index=True)


def render_betguru():
    sport_label = st.radio("Sport", list(SPORTS), horizontal=True, key="bg_sport")
    cfg = SPORTS[sport_label]
    code = cfg["code"]
    st.session_state["bg_code"] = code
    key = f"bg_{code}"

    left, right = st.columns(2)
    risk = left.select_slider("Risk level", options=list(guru.PROFILES), value="Balanced", key="bg_risk")
    n_legs = right.slider("Legs", 2, 6, 3, key="bg_legs")
    st.caption(guru.PROFILES[risk]["blurb"])
    use_props = st.checkbox("Include player props I've loaded", value=True, key=f"{key}_useprops")
    st.caption("The slate is today's games: those starting in the next 24 hours that haven't kicked off yet.")

    too_expensive = show_cost(load_cost(cfg["odds"], cfg["hours"]))
    if st.button(f"Build today's {sport_label} slate", key=f"{key}_build", disabled=too_expensive):
        try:
            st.session_state[f"{key}_state"] = build_slate(cfg)
        except Exception as e:
            st.error(f"Couldn't build the slate right now: {e}")

    state = st.session_state.get(f"{key}_state")
    if state is None:
        st.info("Press the button to load FanDuel's moneylines, spreads and totals, scan each team's recent "
                "games and check injuries. Then BetGuru builds your parlay, writes game talks and shows "
                "who is on the no-bet list.")
        return
    if state["lines"].empty:
        st.info("No FanDuel game lines posted yet for this window.")
        return
    if state["errors"]:
        st.warning(f"{len(state['errors'])} teams couldn't be loaded, e.g. {state['errors'][0]}")

    params = ratings.load_params(code)
    teams = sorted(set(state["lines"]["HOME"]) | set(state["lines"]["AWAY"]))
    try:
        my_list = nobet.list_items()
    except store.StoreError as e:
        # Without your list we might include something you excluded, so don't build a parlay at all.
        st.error(f"Couldn't load your no-bet list, so BetGuru won't build a parlay right now: {e}")
        show_storage("error")
        return
    legs = guru.build_legs(state["lines"], state["form"], params, state["flags"], code)
    prop_labels = []
    if use_props:
        prop_legs, prop_labels = loaded_prop_legs(cfg, state)
        if not prop_legs.empty:
            legs = pd.concat([legs, prop_legs], ignore_index=True)
    if prop_labels:
        st.caption(f"Player props in the mix: {', '.join(prop_labels)}. They use the book's fair odds like every other "
                   "leg, and must also be consistent recently (Safe 80% of the last 10 games, Balanced 70%, "
                   "Aggressive 60%).")
    elif use_props:
        st.caption(f"No props loaded for today's games. Load and scan them in the {sport_label} props tab and "
                   "they'll appear here with no extra Odds API requests.")
    legs = guru.apply_user_list(legs, my_list, cfg["player_team"])
    parlay = guru.build_parlay(legs, risk, n_legs)

    parlay_tab, talks_tab, nobet_tab, model_tab = st.tabs(
        ["Parlay", "Game talks", "No-bet list", "Model and record"])
    with parlay_tab:
        show_parlay(code, risk, parlay)
        with st.expander("Every candidate leg"):
            shown = legs.assign(P=(legs["P"] * 100).round(1), EDGE=(legs["EDGE"] * 100).round(1))
            st.dataframe(shown[["PICK", "GAME", "PRICE", "P", "EDGE", "SEVERITY", "USER_REASON"]]
                         .sort_values("P", ascending=False), hide_index=True)
    with talks_tab:
        show_talks(key, state, params)
    with nobet_tab:
        show_no_bets(state, teams)
    with model_tab:
        show_model(code)
