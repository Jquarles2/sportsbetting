"""Streamlit helpers shared by the BetGuru tab and the NBA/NFL props tabs: the Odds API quota
and the "this load will cost N requests" notes."""
from datetime import datetime, timezone

import streamlit as st

from src import cache, odds


REFRESH_COST = 3  # refreshing the game lines: moneyline, spread and total, one request each


@st.cache_data(ttl=300, show_spinner=False)
def quota_left():
    """Odds API requests left this month, or None if we can't tell. Free to ask; cached 5 minutes."""
    try:
        return odds.requests_remaining()
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def games_in_window(sport, hours):
    """Ids of the games in the window (a free Odds API call), remembered for 5 minutes."""
    return odds.event_ids(sport, hours)


def load_cost(sport, hours, market=None):
    """What loading would cost in Odds API requests, or None if we can't tell."""
    try:
        return odds.estimate_cost(sport, hours, market, ids=games_in_window)
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


def lines_age_text(pulled_at, now=None):
    """'FanDuel lines pulled at 9:05 AM Eastern (2 h 10 min ago).' for a UTC datetime, or a vaguer note if unknown."""
    if pulled_at is None:
        return "FanDuel lines were pulled earlier today (the exact time wasn't saved)."
    now = now or datetime.now(timezone.utc)
    minutes = max(0, int((now - pulled_at).total_seconds() // 60))
    ago = f"{minutes} min ago" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min ago"
    clock = f"{pulled_at.astimezone(cache.EASTERN):%I:%M %p}".lstrip("0")
    return f"FanDuel lines pulled at {clock} Eastern ({ago})."
