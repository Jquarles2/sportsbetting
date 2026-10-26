import streamlit as st

from src import analysis, games, nobet, odds, picks, stats_nba, stats_nfl, store, writeups
from src.ui_betguru import render_betguru
from src.ui_common import load_cost, quota_left, show_cost

st.set_page_config(page_title="BetGuru", page_icon="🎯")

st.title("🎯 BetGuru")
st.caption("Team-vs-team game talks, parlays and a no-bet list, plus the player-props research tools.")


def facts_list(*facts):
    """Keep only the facts we actually have (the describe_* helpers return None for nothing to say)."""
    return [f for f in facts if f]


left = quota_left()
if left is not None:
    if left < 100:
        st.warning(f"Only {left} Odds API requests left this month. Load sparingly.")
    else:
        st.caption(f"Odds API requests left this month: {left}")


def props_dashboard(key, load_props, get_values, stat_label, load_label, cost, get_facts=None):
    """Load FanDuel props, scan players' recent games, then filter and sort the results.

    NBA and NFL share this. They differ only in the function that loads props, the function
    that returns a player's recent stat values, and the label for the stat. `key` keeps each
    tab's results separate in session_state: Streamlit reruns the whole script on every click,
    so anything we want to keep between clicks has to live there.
    cost() says how many Odds API requests loading would use, or None if unknown.
    get_facts(player, game), if given, returns extra fact lines (injury, matchup) for the write-ups.
    Returns the loaded props table, or None if nothing is loaded yet.
    """
    too_expensive = show_cost(cost())
    if st.button(load_label, key=f"{key}_load", disabled=too_expensive):
        try:
            st.session_state[f"{key}_props"] = load_props()
            quota_left.clear()  # the balance just changed
        except Exception as e:
            st.error(f"Couldn't load props right now: {e}")

    if f"{key}_props" not in st.session_state:
        return None
    props, remaining = st.session_state[f"{key}_props"]
    if props.empty:
        st.info("No FanDuel props posted yet for these games.")
        return props

    with st.expander(f"FanDuel {stat_label} lines"):
        st.dataframe(props, hide_index=True)

    st.subheader(f"Props dashboard: {stat_label}")
    st.caption(f"Scans every player's recent games against FanDuel's {stat_label} line. Stats are "
               "cached for the day, and the filters below cost nothing.")
    if st.button("Scan players", key=f"{key}_scan_btn"):
        bar = st.progress(0.0, text="Scanning players...")
        st.session_state[f"{key}_scan"] = picks.scan_players(
            props, get_values,
            progress=lambda done, total: bar.progress(done / total, text=f"{done}/{total} players"),
        )
        bar.empty()

    if f"{key}_scan" in st.session_state:
        scan, errors = st.session_state[f"{key}_scan"]
        if errors:
            st.warning(f"{len(errors)} players couldn't be loaded, e.g. {errors[0]}")

        left, right = st.columns(2)
        side = left.radio("Side", ["Over", "Under"], horizontal=True, key=f"{key}_side")
        window = right.selectbox("Sort and filter by", ["L5", "L10", "L20"], index=1, key=f"{key}_win")
        min_rate = st.slider(f"Minimum {side.lower()} hit rate (%)", 0, 100, 60, step=5, key=f"{key}_min")
        games = st.multiselect("Games", sorted(scan["GAME"].unique()), key=f"{key}_games")
        search = st.text_input("Player contains", key=f"{key}_search")

        table = analysis.props_table(scan, side)
        table = table[table[window].fillna(0) >= min_rate]
        if games:
            table = table[table["GAME"].isin(games)]
        if search:
            table = table[table["PLAYER"].str.contains(search, case=False)]
        table = table.sort_values(window, ascending=False).reset_index(drop=True)
        st.caption(f"{len(table)} {stat_label} props. L5/L10/L20 = % of the last 5/10/20 games where "
                   f"{stat_label} went {side.lower()} the line. Click a column header to re-sort.")
        st.dataframe(table, hide_index=True)

        st.subheader(f"Best 5/5 parlay: {stat_label}")
        found = picks.find_picks(scan)
        try:
            blocked = nobet.names("player")  # players on your no-bet list never make a parlay
        except store.StoreError as e:
            blocked = set()
            st.warning(f"Couldn't load your no-bet list, so it isn't applied to this parlay: {e}")
        if blocked:
            found = found[~found["PLAYER"].str.lower().isin(blocked)]
        if found.empty:
            st.info("No player went 5/5 against these lines.")
        else:
            st.dataframe(found, hide_index=True)
            for _, leg in found.head(5).iterrows():
                st.write(f"**{leg['PLAYER']}** {leg['SIDE']} {leg['LINE']} {stat_label} ({leg['GAME']})")
            st.caption("Top 5 by cushion over/under the line. Past games don't guarantee anything, "
                       "and every extra leg makes a parlay harder to hit.")

            if st.button("Write up these picks (Claude Haiku)", key=f"{key}_writeups_btn"):
                recent = dict(zip(scan["PLAYER"], scan["VALUES"]))
                facts_missing = False
                for _, leg in found.head(5).iterrows():
                    st.markdown(f"**{leg['PLAYER']}** - {leg['SIDE']} {leg['LINE']} {stat_label}")
                    facts = []
                    if get_facts:
                        try:  # a missing injury report shouldn't stop the write-up
                            facts = get_facts(leg["PLAYER"], leg["GAME"])
                        except Exception:
                            facts_missing = True
                    try:
                        st.write(writeups.get_writeup(leg.to_dict(), stat_label, recent[leg["PLAYER"]], facts))
                    except Exception as e:
                        st.error(f"Couldn't write this one up: {e}")
                        break  # same key or network problem would hit the rest too
                if facts_missing:
                    st.caption("Injury or matchup info wasn't available for some picks, so those notes leave it out.")

    st.caption(f"Odds API requests remaining this month: {remaining}")
    return props


def game_lines_section(key, load_lines, get_team_games, pause, cost):
    """Moneylines, spreads and totals for the loaded games, plus each team's recent form.

    Form means: how often the team's last games would have won, covered today's spread, or gone
    over today's total. It's the same idea as the prop hit rates, using final scores only.
    """
    too_expensive = show_cost(cost())
    if st.button("Load game lines", key=f"{key}_lines_load", disabled=too_expensive):
        try:
            st.session_state[f"{key}_lines"] = load_lines()
            quota_left.clear()  # the balance just changed
        except Exception as e:
            st.error(f"Couldn't load game lines right now: {e}")

    if f"{key}_lines" not in st.session_state:
        return
    lines, remaining = st.session_state[f"{key}_lines"]
    if lines.empty:
        st.info("No FanDuel game lines posted yet.")
        return
    st.dataframe(
        lines[["GAME", "ML_AWAY", "ML_HOME", "SPREAD_HOME", "SPREAD_HOME_PRICE", "TOTAL", "OVER", "UNDER"]],
        hide_index=True,
    )
    st.caption("SPREAD_HOME is the home team's number (-3.5 = home favored by 3.5). "
               f"Odds API requests remaining this month: {remaining}")

    if st.button("Scan teams", key=f"{key}_teams_btn"):
        bar = st.progress(0.0, text="Scanning teams...")
        st.session_state[f"{key}_form"] = games.scan_teams(
            lines, get_team_games, pause=pause,
            progress=lambda done, total: bar.progress(done / total, text=f"{done}/{total} teams"),
        )
        bar.empty()

    if f"{key}_form" in st.session_state:
        form, errors = st.session_state[f"{key}_form"]
        if errors:
            st.warning(f"{len(errors)} teams couldn't be loaded, e.g. {errors[0]}")
        st.caption("COVER = % of the team's recent games it would have covered today's spread. "
                   "OVER = % that went over today's total. Past results are context, not a prediction.")

        st.markdown("**Sides (moneyline and spread)**")
        window = st.selectbox("Window", ["L5", "L10"], index=1, key=f"{key}_side_win")
        min_cover = st.slider("Minimum cover rate (%)", 0, 100, 60, step=10, key=f"{key}_min_cover")
        sides = analysis.sides_table(lines, form)
        sides = sides[sides[f"COVER_{window}"].fillna(0) >= min_cover]
        sides = sides.sort_values(f"COVER_{window}", ascending=False).reset_index(drop=True)
        st.dataframe(sides, hide_index=True)

        st.markdown("**Totals**")
        totals = analysis.totals_table(lines, form)
        st.dataframe(totals, hide_index=True)


guru_tab, nba_tab, nfl_tab = st.tabs(["🎯 BetGuru", "🏀 NBA props", "🏈 NFL props"])

with guru_tab:
    render_betguru()

with nba_tab:
    st.header("NBA game logs")
    # A form gives phones a Search button, since the keyboard's Enter key doesn't always submit.
    with st.form("player_search"):
        name = st.text_input("Player name", placeholder="e.g. Stephen Curry")
        submitted = st.form_submit_button("Search")

    if submitted and name:
        try:
            logs = stats_nba.get_game_logs(name, n=10)
        except Exception as e:  # network errors come in many kinds
            st.error(f"Couldn't load stats right now: {e}")
        else:
            if logs is None:
                st.warning(f"No NBA player found matching '{name}'.")
            else:
                st.dataframe(logs, hide_index=True)

    st.header("Today's NBA props")
    nba_market = st.selectbox(
        "Prop type", list(stats_nba.MARKETS), format_func=lambda m: stats_nba.MARKETS[m][1].title(),
        key="nba_market",
    )
    nba_column, nba_label = stats_nba.MARKETS[nba_market]
    st.caption("Player stats are shared by all prop types, so switching type doesn't re-fetch them.")
    props = props_dashboard(
        f"nba_{nba_market}",
        load_props=lambda: odds.get_todays_props(odds.NBA, nba_market, hours=24),
        get_values=lambda player: stats_nba.get_recent_values(player, nba_market),
        stat_label=nba_label,
        load_label=f"Load today's {nba_label} props",
        cost=lambda: load_cost(odds.NBA, 24, nba_market),
        get_facts=lambda player, game: facts_list(writeups.describe_injury(stats_nba.get_injury(player))),
    )

    if props is not None and not props.empty:
        st.subheader("Hit rates for one player")
        st.caption("Uses up to 3 balldontlie requests per new player.")
        player = st.selectbox("Player", sorted(props["PLAYER"].unique()))
        player_lines = props[props["PLAYER"] == player]["LINE"].dropna()
        default_line = float(player_lines.median()) if len(player_lines) else 20.5
        line = st.number_input(f"{nba_label.capitalize()} line", value=default_line, step=0.5)
        if st.button("Show hit rates"):
            try:
                logs = stats_nba.get_game_logs(player, n=20)
            except Exception as e:
                st.error(f"Couldn't load stats right now: {e}")
            else:
                if logs is None or logs.empty:
                    st.warning(f"No game logs found for {player}.")
                else:
                    st.dataframe(analysis.hit_rates(logs, line, nba_column), hide_index=True)

    st.header("NBA moneylines, spreads and totals")
    game_lines_section(
        "nba",
        load_lines=lambda: odds.get_game_lines(odds.NBA, hours=24),
        get_team_games=stats_nba.get_team_games,
        pause=0,  # stats_nba already spaces its calls to respect the rate limit
        cost=lambda: load_cost(odds.NBA, 24),
    )

with nfl_tab:
    st.header("NFL props")
    windows = {"Today": 24, "Next 3 days": 72, "This week": 168}
    window_label = st.selectbox("Games", list(windows), key="nfl_window")
    window_hours = windows[window_label]
    market = st.selectbox(
        "Prop type", list(stats_nfl.MARKETS), format_func=lambda m: stats_nfl.MARKETS[m][1].title()
    )
    st.caption("Props cost 1 Odds API request per game, per prop type, and each game is only ever bought once "
               "a day. Today's games keep it cheap; widening the window pays only for the extra games.")
    stat_label = stats_nfl.MARKETS[market][1]
    props_dashboard(
        f"nfl_{market}",
        load_props=lambda: odds.get_todays_props(odds.NFL, market, hours=window_hours),
        get_values=lambda player: stats_nfl.get_recent_values(player, market),
        stat_label=stat_label,
        load_label=f"Load {stat_label} props ({window_label.lower()})",
        cost=lambda: load_cost(odds.NFL, window_hours, market),
        get_facts=lambda player, game: facts_list(
            writeups.describe_injury(stats_nfl.get_injury(player)),
            writeups.describe_matchup(stats_nfl.get_matchup(player, market, game), stat_label),
        ),
    )

    st.header("NFL moneylines, spreads and totals")
    game_lines_section(
        "nfl",
        load_lines=lambda: odds.get_game_lines(odds.NFL, hours=window_hours),
        get_team_games=stats_nfl.get_team_games,
        pause=0,  # results come from one downloaded file
        cost=lambda: load_cost(odds.NFL, window_hours),
    )
