"""Short AI write-ups for each pick, written by Claude Haiku from the numbers we already have.

Each write-up costs a fraction of a cent, and is cached for the day so reloading is free.
Needs ANTHROPIC_API_KEY in secrets (see .streamlit/secrets.toml.example).
"""
import anthropic

from src import analysis, cache
from src.config import get_secret

MODEL = "claude-haiku-5-5"
SYSTEM = (
    "You write brief, plain-English notes on sports player props for a personal research app. "
    "Use ONLY the numbers you are given. Do not mention injuries, matchups, news or anything else "
    "you were not told, and do not predict the result. In 3 short sentences: say what the recent "
    "games show against the line, point out any streak or inconsistency, and end with one risk to "
    "watch. No emojis, no headings."
)


def build_prompt(pick, stat_label, values):
    """The facts the model gets: the line, the last 10 games and the L5/L10/L20 hit rates."""
    side, line = pick["SIDE"], pick["LINE"]
    rates = ", ".join(
        f"last {n}: {analysis.rate(values, line, n, side)}%" for n in analysis.WINDOWS
    )
    return (
        f"{pick['PLAYER']} - {side} {line} {stat_label} ({pick['GAME']}).\n"
        f"Last 10 games of {stat_label}, newest first: {values[:10]}.\n"
        f"Share of games that went {side.lower()} the line - {rates}."
    )


def get_writeup(pick, stat_label, values, client=None):
    """Return a short write-up for one pick (a row from picks.find_picks) as a string.

    values is the player's recent games, newest first. Raises RuntimeError if there's no key,
    or anthropic.APIError if the API call fails.
    """
    key = f"writeup_{pick['PLAYER']}_{pick['SIDE']}_{pick['LINE']}_{stat_label}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    if client is None:
        api_key = get_secret("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("No ANTHROPIC_API_KEY found. Add it to your secrets.")
        client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=SYSTEM,
        output_config={"effort": "low"},  # a 3-sentence note doesn't need deep thinking
        messages=[{"role": "user", "content": build_prompt(pick, stat_label, values)}],
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:  # e.g. a refusal or cut-off, so don't cache an empty note
        raise RuntimeError(f"No write-up returned (stop reason: {response.stop_reason}).")
    cache.put(key, text)
    return text
