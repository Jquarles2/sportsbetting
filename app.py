import streamlit as st

from src import stats_nba

st.set_page_config(page_title="Props Research", page_icon="🏀")

st.title("Props Research")

st.header("NBA game logs")
name = st.text_input("Player name", placeholder="e.g. Jayson Tatum")
if name:
    try:
        logs = stats_nba.get_game_logs(name, n=10)
    except Exception as e:  # nba_api raises many kinds of network errors
        st.error(f"Couldn't load stats right now: {e}")
    else:
        if logs is None:
            st.warning(f"No NBA player found matching '{name}'.")
        else:
            st.dataframe(logs, hide_index=True)
