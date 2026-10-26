"""Short AI write-ups for each pick, written by Claude Haiku from the numbers we already have.

Each write-up costs a fraction of a cent, and is cached for the day so reloading is free.
Needs ANTHROPIC_API_KEY in secrets (see .streamlit/secrets.toml.example).
"""
from src import analysis, cache, claude
SYSTEM = (
    "You write brief, plain-English notes on sports player props for a personal research app. "
    "Use ONLY the numbers and facts you are given. If an injury or matchup fact is given, work it "
    "in; if none is given, do not mention injuries, matchups or news, and do not predict the "
    "result. In 3 short sentences: say what the recent games show against the line, point out any "
    "streak, inconsistency or given injury/matchup fact, and end with one risk to watch. "
    "No emojis, no headings."
)


def describe_injury(info):
    """One fact line from an injury dict ({'status', 'injury'}), or None if there's nothing to say."""
    if not info or not info.get("status"):
        return None
    detail = f" ({info['injury']})" if info.get("injury") else ""
    return f"Injury report: {info['status']}{detail}."


def describe_matchup(matchup, stat_label):
    """One fact line from a stats_nfl.get_matchup dict, or None."""
    if not matchup:
        return None
    return (f"Opponent {matchup['opponent']} allows {matchup['per_game']} {stat_label} per game this "
            f"season, {matchup['rank']} of {matchup['teams']} (1 = allows the most).")


def build_prompt(pick, stat_label, values, facts=()):
    """The facts the model gets: the line, the last 10 games, the L5/L10/L20 hit rates, and any
    extra fact lines (injury, matchup)."""
    side, line = pick["SIDE"], pick["LINE"]
    rates = ", ".join(
        f"last {n}: {analysis.rate(values, line, n, side)}%" for n in analysis.WINDOWS
    )
    prompt = (
        f"{pick['PLAYER']} - {side} {line} {stat_label} ({pick['GAME']}).\n"
        f"Last 10 games of {stat_label}, newest first: {values[:10]}.\n"
        f"Share of games that went {side.lower()} the line - {rates}."
    )
    return prompt + "".join(f"\n{fact}" for fact in facts)


def get_writeup(pick, stat_label, values, facts=(), client=None):
    """Return a short write-up for one pick (a row from picks.find_picks) as a string.

    values is the player's recent games, newest first. facts are extra lines like an injury
    status or opponent ranking; they're part of the cache key, so a status change gets a new note.
    Raises RuntimeError if there's no key
    or no reply, or anthropic.APIError if the API call fails.
    """
    key = f"writeup_{pick['PLAYER']}_{pick['SIDE']}_{pick['LINE']}_{stat_label}_{'|'.join(facts)}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    text = claude.ask(SYSTEM, build_prompt(pick, stat_label, values, facts), client=client)
    cache.put(key, text)
    return text
