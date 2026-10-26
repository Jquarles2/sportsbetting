# BetGuru — Claude context

## What this is
**BetGuru**: a personal sports-betting research web app (NBA + NFL), shown to the owner, 1–2 friends
and some investors. It is also a learning project: the owner is a beginner, so explain non-obvious
code briefly and keep the code simple.

Two halves:
1. **BetGuru tab** (team vs team): FanDuel moneylines/spreads/totals → a model → a parlay for a chosen
   risk level, AI "game talks", an automatic + personal **no-bet list**, and a graded results record.
2. **Props tabs** (NBA props, NFL props): player-prop research — hit rates over the last 5/10/20 games,
   a sortable dashboard, a best 5/5 parlay, and AI write-ups for picks.

## Honest status of the model (read this before changing the pitch or the UI copy)
Backtests on 14 seasons of real NFL historical lines (`scripts/train_weights.py`) found that recent team
form adds **no reliable edge** over the market: spread ~50%, totals ~50–53% (break-even at -110 is
52.4%; ±4% is noise on the validation set). Bayesian optimization shrank the model's tilts to ~0, so
its probabilities track the book's. The NBA has no free historical lines, so it is **untrained** and uses
zero tilt (its chances are exactly the book's). BetGuru's value is discipline (skip untrusted legs, one leg per game, real EV
math, a graded record), not a secret edge. Never write copy that promises winners or profit; parlay EV
is always negative because of the vig. Keep the "How the model is doing" panel honest.

**Winner's curse (learned the hard way):** an early NBA version with small non-zero tilts showed a
"+16 EV" Aggressive parlay in the live app, because ranking legs by model-vs-book disagreement selects
the model's biggest errors. So the headline EV (`ev_per_100`) is computed from the book's own no-vig
chances (`P_MARKET`) and can never be positive; the model-based EV (`ev_model_per_100`) is shown only as a
labelled "don't trust this" number. Never switch the headline back to model chances.

## Stack
- Python 3.11+ (dev box runs 3.13), Streamlit (UI + hosting on Streamlit Community Cloud, deploys `main`)
- Data: The Odds API (FanDuel only), balldontlie (NBA stats, paid $10 plan, ~60 req/min),
  nflverse public CSVs read directly with pandas (NFL stats, schedule/scores/lines, injuries).
  `nfl_data_py` is NOT used (unmaintained, pins pandas<2).
- AI: Anthropic API, `claude-haiku-5-5`, via `src/claude.py` (write-ups and game talks)
- Math: numpy only. Bayesian optimization is our own small GP + expected-improvement in `src/bayes.py`
  (scikit-learn is not installed).
- Storage (`src/store.py`): Supabase when `SUPABASE_URL` + `SUPABASE_KEY` are in secrets (plain REST over
  `requests`, tables from `docs/supabase_setup.sql`, RLS on, used with the secret/service_role key),
  otherwise a local SQLite file `data/state.db` (wiped on Streamlit Cloud restarts). It holds the no-bet list
  (`src/nobet.py`), the results log (`src/results.py`) and a durable copy of Odds API answers (`odds_*` keys).
  `data/cache.db` (`src/cache.py`) is the always-local daily cache; only `odds_*` keys are mirrored to
  Supabase, with a 60 s in-memory "miss" memo so page clicks stay fast.
- Secrets: `.streamlit/secrets.toml` (git-ignored; example file committed). Never commit keys.
  Names: `ODDS_API_KEY`, `BALLDONTLIE_API_KEY`, `ANTHROPIC_API_KEY`.

## Rules
- Use only legitimate, public data sources. Don't scrape or call private endpoints of Rotobot,
  PropsBot or other competitors. REA is for learning how features work, not for copying data.
- Keep API usage low. The Odds API free tier is ~500 requests/month: cache everything, and show the
  cost before every load (`src/ui_common.py`). Free Odds API calls: `/sports` (also returns the
  remaining balance) and `/sports/{sport}/events`. Costs: props = 1 request per game per prop type;
  game lines = 3 per sport (h2h, spreads, totals) however many games.
- balldontlie: every call goes through `stats_nba._get`, which spaces calls (1.1 s) and retries 429s.
  Never call the API from elsewhere.
- Small, focused changes. One feature per session unless the owner asks for more.
- Run `python -m pytest` before saying something works. Real data checks beat guesses: when a number
  looks surprising, test it against the real nflverse data.
- Report outcomes faithfully (say when something is unverified live). Don't tune a model to look good.

## Layout
- `app.py`: entry point. Title, Odds API quota banner, three tabs (BetGuru, NBA props, NFL props),
  and the shared `props_dashboard` / `game_lines_section` for the props tabs.
- `src/ui_betguru.py`: the BetGuru tab (slate, parlay, game talks, no-bet list, model and record).
- `src/ui_common.py`: Odds API quota and "this will cost N requests" helpers (Streamlit-cached).
- `src/odds.py`: Odds API (props + game lines, cache keys, free-call cost estimates)
- `src/stats_nba.py`: balldontlie (game logs, team games, final scores, injuries). Props markets map:
  points/rebounds/assists/threes/PRA.
- `src/stats_nfl.py`: nflverse (weekly stats, team results, finals, injuries, matchups).
- `src/analysis.py`: prop hit rates, win/cover/over rates, sides and totals tables.
- `src/picks.py`, `src/games.py`: scans (players' recent values, teams' recent games), 5/5 picks.
- `src/ratings.py`: the team-vs-team model (rating blend, expected margin/total, probabilities).
- `src/backtest.py`, `src/bayes.py`, `scripts/train_weights.py`: backtest on historical NFL lines and
  Bayesian optimization of the model settings. Writes `data/model_nfl.json` (committed).
- `src/guru.py`: legs, flags, no-bet list, parlay builder (Safe / Balanced / Aggressive).
- `src/talks.py`, `src/writeups.py`, `src/claude.py`: Claude-written game talks and pick write-ups.
- `src/store.py`: storage backends (SQLiteStore, SupabaseStore) and `get_store()`. All persistence goes
  through it. `src/results.py`, `src/nobet.py`: results log + grading + calibration; your no-bet list.
- `tests/`: pytest. `tests/test_app.py` runs the real app headlessly (Streamlit `AppTest`) with fakes.
  `tests/fake_supabase.py` imitates Supabase's REST API; `tests/test_store.py` runs the same contract
  tests against both backends.

## Commands
- Run: `streamlit run app.py`
- Tests: `python -m pytest` (≈125 tests, no network needed)
- Retrain the NFL model: `python scripts/train_weights.py` (needs network, ~1 min), commit the JSON.

## Workflow notes
- Work on branch `claude/odds-props`; the owner merges PRs into `main`, which Streamlit deploys.
  PRs are squash-merged, so after each merge reset the branch before new work:
  `git fetch origin main && git checkout -B claude/odds-props origin/main` (avoids phantom conflicts).
- Only open a PR when the owner asks. If the PR shows no merge button, it has conflicts (`mergeable_state: dirty`).
- Streamlit reruns the whole script on every click: keep anything slow or chosen in
  `st.session_state`, and give every widget a unique `key`.

## Known gaps and unverified-live items
- NBA team games (`stats_nba.get_team_games`, balldontlie `/games`) are verified live (the NBA slate built
  on the deployed app). NBA injuries (`/player_injuries`) and NBA finals (`stats_nba.get_final`, used for
  grading) were written from the docs and never run against a real key. Failures degrade quietly.
- NBA team-level injury flags and NBA matchups (opponent defense per stat) are not built.
- Supabase is tested only against our fake (`tests/fake_supabase.py`), never a real project, until the owner
  connects one. The in-app "Check storage connection" button reports real problems in plain words.
  If storage is down, BetGuru refuses to build a parlay (it can't tell what your no-bet list excludes).
- The no-bet list and record are shared by everyone who opens the app (no per-user accounts).
- Phone layout is only what Streamlit gives by default (owner marked it low priority).

## Next steps (suggested order)
1. Owner connects Supabase (README steps) and confirms "Check storage connection" works; fix anything real.
2. Morning pre-warm job + line-movement snapshots (history can now live in Supabase).
3. Verify NBA calls live; add NBA team injuries and opponent-defense matchups.
4. Once there are ≥100 graded legs per sport, retrain/recalibrate on the live record (extend
   `train_weights.py` to read `picks_log`), and show calibration over time.
5. Phone layout polish.
