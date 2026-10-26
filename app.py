import streamlit as st

from src import analysis, odds, picks, stats_nba, stats_nfl

st.set_page_config(page_title="Props Research", page_icon="🏀")

st.title("Props Research")


def props_dashboard(key, load_props, get_values, stat_label, load_label):
    """Load FanDuel props, scan players' recent games, then filter and sort the results.

    NBA and NFL share this. They differ only in the function that loads props, the function
    that returns a player's recent stat values, and the label for the stat. `key` keeps each
    tab's results separate in session_state: Streamlit reruns the whole script on every click,
    so anything we want to keep between clicks has to live there.
    Returns the loaded props table, or None if nothing is loaded yet.
    """
    if st.button(load_label, key=f"{key}_load"):
        try:
            st.session_state[f"{key}_props"] = load_props()
        except Exception as e:
            st.error(f"Couldn't load props right now: {e}")

    if f"{key}_props" not in st.session_state:
        return None
    props, remaining = st.session_state[f"{key}_props"]
    if props.empty:
        st.info("No FanDuel props posted yet for these games.")
        return props

    with st.expander("FanDuel lines"):
        st.dataframe(props, hide_index=True)

    st.subheader("Props dashboard")
    st.caption("Scans every player's recent games against FanDuel's line. Stats are cached for the "
               "day, and the filters below cost nothing.")
    if st.button("Scan players", key=f"{key}_scan_btn"):
        bar = st.progress(0.0, text="Scanning players...")
        st.session_state[f"{key}_scan"] = picks.scan_players(
            props, get_values,
            progress=lambda done, total: bar.progress(done / total, text=f"{done}/{total} players"),
            pause=1.0 if key == "nba" else 0,  # NBA stats come from a rate-limited API
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
        st.caption(f"{len(table)} props. L5/L10/L20 = % of last 5/10/20 games {side.lower()} the line. "
                   "Click a column header to re-sort.")
        st.dataframe(table, hide_index=True)

        st.subheader("Best 5/5 parlay")
        found = picks.find_picks(scan)
        if found.empty:
            st.info("No player went 5/5 against these lines.")
        else:
            st.dataframe(found, hide_index=True)
            for _, leg in found.head(5).iterrows():
                st.write(f"**{leg['PLAYER']}** {leg['SIDE']} {leg['LINE']} {stat_label} ({leg['GAME']})")
            st.caption("Top 5 by cushion over/under the line. Past games don't guarantee anything, "
                       "and every extra leg makes a parlay harder to hit.")

    st.caption(f"Odds API requests remaining this month: {remaining}")
    return props


nba_tab, nfl_tab = st.tabs(["🏀 NBA", "🏈 NFL"])

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

    st.header("Today's NBA points props")
    st.caption("Each load uses Odds API requests (free plan: ~500/month), so it's cached for the day.")
    props = props_dashboard(
        "nba",
        load_props=lambda: odds.get_todays_props(odds.NBA, "player_points", hours=24),
        get_values=stats_nba.get_recent_points,
        stat_label="points",
        load_label="Load today's props",
    )

    if props is not None and not props.empty:
        st.subheader("Hit rates for one player")
        st.caption("Uses 2 balldontlie requests per new player.")
        player = st.selectbox("Player", sorted(props["PLAYER"].unique()))
        player_lines = props[props["PLAYER"] == player]["LINE"].dropna()
        default_line = float(player_lines.median()) if len(player_lines) else 20.5
        line = st.number_input("Points line", value=default_line, step=0.5)
        if st.button("Show hit rates"):
            try:
                logs = stats_nba.get_game_logs(player, n=20)
            except Exception as e:
                st.error(f"Couldn't load stats right now: {e}")
            else:
                if logs is None or logs.empty:
                    st.warning(f"No game logs found for {player}.")
                else:
                    st.dataframe(analysis.hit_rates(logs, line), hide_index=True)

with nfl_tab:
    st.header("This week's NFL props")
    market = st.selectbox(
        "Prop type", list(stats_nfl.MARKETS), format_func=lambda m: stats_nfl.MARKETS[m][1].title()
    )
    st.caption("Loading uses about 1 Odds API request per game this week (roughly 14-16) for the "
               "chosen prop type, then it's cached for the day. Load one prop type at a time to "
               "stay inside the free plan's ~500/month.")
    stat_label = stats_nfl.MARKETS[market][1]
    props_dashboard(
        f"nfl_{market}",
        load_props=lambda: odds.get_todays_props(odds.NFL, market, hours=24 * 7),
        get_values=lambda player: stats_nfl.get_recent_values(player, market),
        stat_label=stat_label,
        load_label=f"Load this week's {stat_label} props",
    )
