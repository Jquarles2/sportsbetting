# Sports Props App — Claude context

## What this is
A personal player-prop research web app (NBA + NFL), similar in spirit to Rotobot / PropsBot.
Shown to the owner plus 1–2 friends. It's also a learning project: the owner is a beginner,
so explain non-obvious code briefly and keep the code simple.

## Stack
- Python 3.11+
- Streamlit (UI and hosting on Streamlit Community Cloud)
- Data: The Odds API (prop lines), balldontlie (NBA stats), nflverse weekly player stats, read directly as CSV (NFL stats; nfl_data_py is unmaintained and pins pandas<2)
- AI: Anthropic API (claude-haiku-5-5) for pick write-ups
- Storage: SQLite cache (data/cache.db); don't refetch data we already have today
- Secrets: `.streamlit/secrets.toml` (git-ignored). Never commit API keys.

## Rules
- Use only legitimate, public data sources. Don't scrape or call private endpoints of
  Rotobot, PropsBot or other competitors. REA is for learning how features work, not for copying data.
- Keep API usage low: The Odds API's free tier is about 500 requests a month, so cache responses.
- Small, focused changes. One feature per session.
- Run `python -m pytest` before saying something works.

## Layout (planned)
- app.py: Streamlit entry point
- src/odds.py: fetch prop lines
- src/stats_nba.py, src/stats_nfl.py: player game logs
- src/analysis.py: hit rates, edges
- tests/
