import streamlit as st

from src import analysis, odds, picks, stats_nba

st.set_page_config(page_title="Props Research", page_icon="🏀")

st.title("Props Research")

st.header("NBA game logs")
# A form gives phones a Search button, since the keyboard's Enter key doesn't always submit.
with st.form("player_search"):
    name = st.text_input("Player name", placeholder="e.g. Stephen Curry")
    submitted = st.form_submit_button("Search")

if submitted and name:
    try:
        logs = stats_nba.get_game_logs(name, n=10)
    except Exception as e:  # nba_api raises many kinds of network errors
        st.error(f"Couldn't load stats right now: {e}")
    else:
        if logs is None:
            st.warning(f"No NBA player found matching '{name}'.")
        else:
            st.dataframe(logs, hide_index=True)

st.header("Today's NBA points props")
st.caption("Each load uses Odds API requests (free plan: ~500/month), so it's cached for the day.")
if st.button("Load today's props"):
    try:
        # Keep results in session_state: Streamlit reruns the script on every click,
        # so a plain variable would vanish when you pick a player below.
        st.session_state["props"] = odds.get_todays_props()
    except Exception as e:
        st.error(f"Couldn't load props right now: {e}")

if "props" in st.session_state:
    props, remaining = st.session_state["props"]
    if props.empty:
        st.info("No player-points props posted yet for games in the next 24 hours.")
    else:
        with st.expander("All lines by sportsbook"):
            st.dataframe(props, hide_index=True)

        st.header("Props dashboard")
        st.caption("Scans every player's recent games against their median line. First run takes a few "
                   "minutes; game logs are then cached for the day, and filters below cost nothing.")
        if st.button("Scan players"):
            bar = st.progress(0.0, text="Scanning players...")
            st.session_state["scan"] = picks.scan_players(
                props, progress=lambda done, total: bar.progress(done / total, text=f"{done}/{total} players")
            )
            bar.empty()

        if "scan" in st.session_state:
            scan, errors = st.session_state["scan"]
            if errors:
                st.warning(f"{len(errors)} players couldn't be loaded, e.g. {errors[0]}")

            left, right = st.columns(2)
            side = left.radio("Side", ["Over", "Under"], horizontal=True)
            window = right.selectbox("Sort and filter by", ["L5", "L10", "L20"], index=1)
            min_rate = st.slider(f"Minimum {side.lower()} hit rate (%)", 0, 100, 60, step=5)
            games = st.multiselect("Games", sorted(scan["GAME"].unique()))
            search = st.text_input("Player contains")

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
                st.info("No player went 5/5 against today's lines.")
            else:
                st.dataframe(found, hide_index=True)
                for _, leg in found.head(5).iterrows():
                    st.write(f"**{leg['PLAYER']}** {leg['SIDE']} {leg['LINE']} points ({leg['GAME']})")
                st.caption("Top 5 by cushion over/under the line. Past games don't guarantee anything, "
                           "and every extra leg makes a parlay harder to hit.")

        st.header("Hit rates")
        st.caption("Uses 2 balldontlie requests per new player (free plan: 5/minute).")
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
    st.caption(f"Odds API requests remaining this month: {remaining}")
