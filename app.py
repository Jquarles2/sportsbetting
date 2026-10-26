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
        st.dataframe(props, hide_index=True)

        st.header("Best 5/5 picks")
        st.caption("Scans every player in the table for 'cleared the line in all of the last 5 games'. "
                   "First run takes a few minutes; game logs are then cached for the day.")
        if st.button("Find 5/5 picks"):
            bar = st.progress(0.0, text="Scanning players...")
            found, errors = picks.find_picks(
                props, progress=lambda done, total: bar.progress(done / total, text=f"{done}/{total} players")
            )
            bar.empty()
            st.session_state["picks"] = (found, errors)
        if "picks" in st.session_state:
            found, errors = st.session_state["picks"]
            if found.empty:
                st.info("No player went 5/5 against today's lines.")
            else:
                st.dataframe(found, hide_index=True)
                legs = found.head(5)
                st.subheader("Best 5/5 parlay")
                for _, leg in legs.iterrows():
                    st.write(f"**{leg['PLAYER']}** {leg['SIDE']} {leg['LINE']} points ({leg['GAME']})")
                st.caption("Picks with the biggest cushion over/under the line. Past games don't "
                           "guarantee anything, and every extra leg makes a parlay harder to hit.")
            if errors:
                st.warning(f"{len(errors)} players couldn't be loaded, e.g. {errors[0]}")

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
