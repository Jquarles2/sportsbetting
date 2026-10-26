"""Streamlit helpers shared by the BetGuru tab and the NBA/NFL props tabs: the Odds API quota
and the "this load will cost N requests" notes."""
import streamlit as st

from src import odds


@st.cache_data(ttl=300, show_spinner=False)
def quota_left():
    """Odds API requests left this month, or None if we can't tell. Free to ask; cached 5 minutes."""
    try:
        return odds.requests_remaining()
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def games_in_window(sport, hours):
    return odds.count_games(sport, hours)


def load_cost(sport, hours, market=None):
    """What loading would cost in Odds API requests, or None if we can't tell."""
    try:
        return odds.estimate_cost(sport, hours, market, count=games_in_window)
    except Exception:
        return None


def show_cost(cost):
    """Say what a load will cost. Returns True if you don't have enough requests left for it."""
    if cost is None:
        return False
    left = quota_left()
    if cost == 0:
        st.caption("Already loaded today, so this is free.")
    else:
        extra = f" ({left} left this month)" if left is not None else ""
        st.caption(f"This load will use about {cost} Odds API requests{extra}.")
    return left is not None and cost > left
