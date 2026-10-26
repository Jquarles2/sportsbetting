"""BetGuru's game talks: a short team-vs-team preview of each game, written by Claude from facts.

The facts come from the lines, each team's recent form, the model's numbers and the injury
flags. Claude is told to use only those, so it can't invent injuries or stats.
"""
import hashlib

from src import cache, claude, ratings

SYSTEM = (
    "You write short, plain-English previews of a sports game for a research app. Use ONLY the "
    "facts you are given: never add injuries, stats, history or news that isn't listed, and never "
    "promise a result. In 4 short sentences: compare how the two teams have been playing, say "
    "what the betting line implies, mention any listed injury, and end with the main risk. The "
    "model numbers are one input, not proof of an edge: recent form is already largely reflected "
    "in the lines, so don't oversell them. No emojis, no headings."
)


def record(games, n):
    """'3-2' style win-loss record over a team's last n games (newest first)."""
    last = games[:n]
    wins = sum(g["for"] > g["against"] for g in last)
    return f"{wins}-{len(last) - wins}"


def team_line(team, games):
    last10 = games[:10]
    if not last10:
        return f"{team}: no recent games available."
    scored = sum(g["for"] for g in last10) / len(last10)
    allowed = sum(g["against"] for g in last10) / len(last10)
    return (f"{team}: {record(games, 5)} in the last 5, {record(games, 10)} in the last 10, "
            f"averaging {scored:.1f} points scored and {allowed:.1f} allowed ({scored - allowed:+.1f} margin).")


def game_facts(game, form, params, flags):
    """Fact lines for one game. `game` is a row from odds.get_game_lines (an itertuples row)."""
    home, away = form.get(game.HOME) or [], form.get(game.AWAY) or []
    facts = []
    line = []
    if game.SPREAD_HOME == game.SPREAD_HOME:  # not NaN
        line.append(f"spread {game.HOME} {game.SPREAD_HOME:+g}")
    if game.TOTAL == game.TOTAL:
        line.append(f"total {game.TOTAL:g}")
    if game.ML_HOME == game.ML_HOME and game.ML_AWAY == game.ML_AWAY:
        line.append(f"moneyline {game.HOME} {game.ML_HOME:+g} / {game.AWAY} {game.ML_AWAY:+g}")
    facts.append(f"{game.GAME} (home team: {game.HOME}). FanDuel line: " + ", ".join(line) + ".")
    facts += [team_line(game.HOME, home), team_line(game.AWAY, away)]
    if home and away:
        pred = ratings.predict_game(home, away, params)
        facts.append(f"Model: {game.HOME} by {pred['exp_margin']:+.1f}, total {pred['exp_total']:.1f}.")
    for team in (game.HOME, game.AWAY):
        for flag in flags.get(team, []):
            facts.append(f"Injury report, {team}: {flag['reason']}.")
    return facts


def get_talk(game_name, facts, client=None):
    """Claude's preview of one game. Cached for the day, and a changed fact gets a fresh one."""
    digest = hashlib.sha1("|".join(facts).encode()).hexdigest()[:12]
    key = f"talk_{game_name}_{digest}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    text = claude.ask(SYSTEM, "\n".join(facts), client=client, max_tokens=600)
    cache.put(key, text)
    return text
