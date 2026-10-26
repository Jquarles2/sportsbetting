import streamlit as st

from src import odds, stats_nba

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
        props, remaining = odds.get_todays_props()
    except Exception as e:
        st.error(f"Couldn't load props right now: {e}")
    else:
        if props.empty:
            st.info("No player-points props posted yet for games in the next 24 hours.")
        else:
            st.dataframe(props, hide_index=True)
        st.caption(f"Odds API requests remaining this month: {remaining}")
