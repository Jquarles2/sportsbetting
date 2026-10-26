"""Your own no-bet list: teams, players or games you never want in a BetGuru parlay.

Saved through src/store.py: in Supabase when it's configured (survives restarts), otherwise in a local
file. Everyone using the same app shares one list.
"""
from src import store

KINDS = ("team", "player", "game")


def list_items():
    """Every entry as a list of (kind, name) tuples, oldest first."""
    return store.get_store().nobet_list()


def add(kind, name):
    """Add an entry. Returns False if the name was blank or the kind is unknown."""
    name = " ".join(name.split())
    if kind not in KINDS or not name:
        return False
    store.get_store().nobet_add(kind, name)
    return True


def remove(kind, name):
    store.get_store().nobet_remove(kind, name)


def names(kind, items=None):
    """Lowercased names of one kind, for case-insensitive matching."""
    return {n.lower() for k, n in (items if items is not None else list_items()) if k == kind}
