# BetGuru — Claude context

## What this is
**BetGuru**: a personal sports-betting research web app (NBA + NFL), shown to the owner, 1–2 friends and some
investors. It is also a learning project: the owner is a beginner, so explain non-obvious code briefly, keep the
code simple, and keep comments plain-English.

Two halves:
1. **BetGuru tab** (team vs team): FanDuel moneylines/spreads/totals → a model → a parlay for a chosen risk level,
   a lotto ticket, AI "game talks", an automatic + personal **no-bet list**, and a graded results record.
2. **Props tabs** (NBA props, NFL props): player-prop research — hit rates over the last 5/10/20 games, a sortable
   dashboard, a best 5/5 parlay, and AI write-ups for picks. Loaded props can also feed BetGuru parlays.

## Where things stand (as of 2026-10-28)
- Deployed on Streamlit Community Cloud from `main` (app URL looks like `bettingbotbot.streamlit.app`; confirm in the
  owner's dashboard at share.streamlit.io). PRs #1–#18 are merged, so `main` has everything
  described here (including line movement and the props-tab Refresh button).
- Supabase is connected to a real project and working (the owner created the tables with
  `docs/supabase_setup.sql`; the NFL slate only builds when the no-bet list loads, and it does).
- The owner has the Odds API free plan (~500 requests/month), a paid $10 balldontlie plan, an Anthropic key
  with a small prepaid balance, and Supabase on its free tier.
- Verified live: NFL slate, NBA slate, NBA team games, Supabase storage, pick write-ups (Claude), the Odds API
  quota banner and cost guard.
- **Not verified live** (tested only against fakes or never run): game talks, prop-leg grading, NBA
  `/player_injuries`, NBA finals (`stats_nba.get_final`), the lotto and saved-ticket grading, how FanDuel prices a
  same-game parlay, the Refresh lines button and line movement against the real Odds API, the NFL scores re-download,
  and how balldontlie reports a did-not-play stat line (the zero-minute check is a guess at the format).

## Honest status of the model (read before changing the pitch or any UI copy)
Backtests on 14 seasons of real NFL historical lines (`scripts/train_weights.py`) found that recent team form adds
**no reliable edge** over the market: spread ~50%, totals ~50–53% (break-even at -110 is 52.4%; ±4% is noise on the
validation set). Bayesian optimization shrank the model's tilts to ~0, so its probabilities track the book's. The
NBA has no free historical lines, so it is **untrained** with zero tilt (its chances are exactly the book's).
Props have no model at all: they use the book's no-vig odds, filtered by recent hit rate.

BetGuru's value is discipline (skip untrusted legs, no near-duplicate legs, real EV math, a graded record), not a
secret edge. Never write copy that promises winners or profit; parlay EV is always negative because of the vig.

**Winner's curse (learned the hard way):** an early NBA version with small non-zero tilts showed a "+16 EV"
Aggressive parlay in the live app, because ranking legs by model-vs-book disagreement selects the model's biggest
errors. So the headline EV (`ev_per_100`) is computed from the book's own no-vig chances (`P_MARKET`) and can never
be positive; the model-based EV (`ev_model_per_100`) is shown only as a labelled "don't trust this" number. Never
switch the headline back to model chances, and never give props or the NBA a tilt without live-result evidence.

## Stack
- Python 3.11+ (dev box runs 3.13), Streamlit (UI + hosting), numpy/pandas/requests. scikit-learn is NOT installed.
- Data: The Odds API (FanDuel only), balldontlie (NBA stats, ~60 req/min), nflverse public CSVs read directly
  with pandas (NFL stats, schedule/scores/historical lines, injuries). `nfl_data_py` is NOT used (unmaintained,
  pins pandas<2 and would break the app).
- AI: Anthropic API, `claude-haiku-5-5`, only through `src/claude.py` (write-ups, game talks).
- Math: our own small Gaussian-process Bayesian optimizer in `src/bayes.py` (numpy only).
- Storage (`src/store.py`): Supabase when `SUPABASE_URL` + `SUPABASE_KEY` are in secrets (plain REST over `requests`,
  RLS on, used with the secret/service_role key), else a local SQLite file `data/state.db` (wiped on Streamlit Cloud
  restarts). Holds the no-bet list (`src/nobet.py`), the results log (`src/results.py`) and a durable copy of Odds
  API answers (`odds_*` cache keys). `data/cache.db` (`src/cache.py`) is the always-local daily cache.
- Secrets: `.streamlit/secrets.toml` locally, the Secrets box on Streamlit Cloud. Never commit or echo keys. Names:
  `ODDS_API_KEY`, `BALLDONTLIE_API_KEY`, `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`.

## Rules
- Use only legitimate, public data sources. Don't scrape or call private endpoints of Rotobot, PropsBot or other
  competitors. REA (`npx rea-agents setup`, runs on the owner's own machine) is for learning how features work,
  not for copying data; do it in its own session.
- **Odds API budget is the main constraint (~500/month).** Free calls: `/sports` (also returns the remaining
  balance) and `/sports/{sport}/events`. Paid: props = 1 request per game per prop type; game lines = 3 per sport
  (h2h, spreads, totals) however many games. Cache "days" are the betting day (`cache.today()`: rolls at 5 a.m.
  Eastern, NOT UTC midnight). Props are cached per game and the time window is applied when reading, so a game is
  bought at most once a day; started games are never bought. Anything new that calls the Odds API must go through
  `src/odds.py`, show its cost beforehand (`src/ui_common.py`), and respect these rules. README has a monthly
  budget table.
- balldontlie: every call goes through `stats_nba._get` (spaces calls 1.1 s, retries 429s). Never call it elsewhere.
- Small, focused changes. One feature per session unless the owner asks for more (they often ask for several).
- Run `python -m pytest` before saying something works. Real data checks beat guesses: when a number looks
  surprising, test it against the real nflverse data.
- Report outcomes faithfully: say when something is unverified live, own mistakes plainly, and never tune a model
  or word a result to look good.

## Layout
- `app.py`: entry point. Title, Odds API quota banner, three tabs (BetGuru, NBA props, NFL props), and the shared
  `props_dashboard` / `game_lines_section` used by the props tabs. NFL props tab has a Games window (Today default).
- `src/ui_betguru.py`: the whole BetGuru tab (slate, parlay, lotto, game talks, no-bet list, model and record).
- `src/ui_common.py`: Odds API quota, `REFRESH_COST`, "this will cost N requests" and `lines_age_text` helpers.
- `src/odds.py`: Odds API (props + game lines, cache keys, free-call cost estimates). `refresh_game_lines` always
  re-buys (3 requests) and keeps the day's first pull as `opening`; `lines_pulled_at` and `line_moves` read the cache only.
- `src/stats_nba.py`: balldontlie (game logs, team games, finals, injuries, player stat lines). `MARKETS` maps
  points/rebounds/assists/threes/PRA. `src/stats_nfl.py`: nflverse (weekly stats, team results, finals, injuries,
  matchups, player stat lines). `MARKETS` maps passing/rushing/receiving yards and receptions.
- `src/analysis.py`: prop hit rates, win/cover/over rates, sides and totals tables.
- `src/picks.py`, `src/games.py`: scans (players' recent values, teams' recent games) and 5/5 picks.
- `src/ratings.py`: the team-vs-team model. `src/backtest.py`, `src/bayes.py`, `scripts/train_weights.py`: NFL
  backtest and optimizer; writes `data/model_nfl.json` (committed).
- `src/guru.py`: legs (game legs + `build_prop_legs`), flags, no-bet list, `legs_conflict`, `build_parlay`
  (Safe / Balanced / Aggressive). `src/lotto.py`: the lotto ticket.
- `src/talks.py`, `src/writeups.py`, `src/claude.py`: Claude-written game talks and pick write-ups.
- `src/store.py`, `src/nobet.py`, `src/results.py`, `src/cache.py`: persistence, your no-bet list, the results log
  with grading and calibration, and the daily cache.
- `tests/`: pytest. `tests/test_app.py` runs the real app headlessly (Streamlit `AppTest`) with fakes;
  `tests/fake_supabase.py` imitates Supabase's REST API and `tests/test_store.py` runs the same contract tests
  against both storage backends.
- `docs/PLAN.md` (build history + next), `docs/supabase_setup.sql`, `README.md` (user-facing, incl. API budget).

## How the main pieces behave
- **Slate**: "Build today's {NFL|NBA} slate" loads FanDuel game lines (3 requests, or free if cached), scans each
  team's recent games, and checks injuries (NFL only). Window = next 24 hours, not yet started, both sports.
- **Legs**: both sides of moneyline, spread and total per game. Chances start from the book's no-vig probability;
  `P` = model, `P_MARKET` = book, `EDGE = P - implied price`. Flags: `block` (QB Out/Doubtful, blowout spread, thin
  data, your list) removes a leg at every risk level; `warn` (other injured skill players, Questionable QB) only
  removes it from Safe.
- **Parlay**: `build_parlay(legs, risk, n_legs, per_game)`. UI defaults: 3 legs, 2 legs per game. `legs_conflict`
  forbids near-duplicate pairs (moneyline with spread, two totals, one player twice). Same-game legs are
  correlated, so the chance and payout assume independence and the page says FanDuel's same-game price differs.
  By default it combines every built slate ("Combine with my other built slates"); legs carry a `SPORT` column and a
  cross-sport parlay is logged with risk `"<risk> (mixed)"` so the record counts it as one ticket (same for `Lotto`).
- **Prop legs**: from props already loaded + scanned in the props tabs (session keys `{nba|nfl}_{market}_props` /
  `_scan`), only for games on the slate, MARKET `Prop:<odds market>`, priced at no-vig odds, filtered by the last-10
  hit rate (`SUPPORT`: Safe 80, Balanced 70, Aggressive 60). The player's name is stored in the log's `team` column.
  Grading uses the real stat line; a final game with no stat line for the player is voided as a push; NFL waits
  until nflverse publishes the game's weekly stats.
- **Lotto**: stake and dream payout (default $0.50 → $1,000), best price per risk, trims unneeded legs, mixes sports
  and props; never uses flagged, excluded or inconsistent legs; says plainly when today's games can't reach it.
- **No-bet list**: automatic (`guru.auto_no_bets`) plus the owner's own (teams, players, games) in `nobet`. If storage
  is down BetGuru refuses to build a parlay (it can't tell what the list excludes).
- **Results**: saved legs are graded against final scores/stat lines; `Grade finished games` on the Model and record
  tab; calibration table shows whether "60%" legs hit 60%.

## Commands
- Run: `streamlit run app.py`
- Tests: `python -m pytest` (≈185 tests, no network needed, ~15 s)
- Retrain the NFL model: `python scripts/train_weights.py` (needs network, ~1 min), then commit the JSON.

## Workflow notes
- Work on branch `claude/odds-props`. The owner merges PRs into `main`, which Streamlit deploys. PRs are merged, so
  after each merge reset the branch before new work: `git fetch origin main && git checkout -B claude/odds-props
  origin/main` (skipping this causes phantom conflicts; a PR with no merge button has `mergeable_state: dirty`).
- Open a PR only when the owner asks ("open pull request" / "merge"). They merge it themselves unless they clearly say
  "merge" to you (once they did, and the merge was done via `merge_pull_request` with the real head SHA from
  `git rev-parse HEAD`; never type a SHA by hand). Commit messages end with the Co-Authored-By and Claude-Session
  lines from the session reminder; PR bodies end with the generated-with line.
- Streamlit reruns the whole script on every click and renders ALL tabs every time: keep anything slow or chosen
  in `st.session_state`, give every widget a unique `key`, and never put a network call in code that runs per rerun
  without caching it. A stale error stays on screen until something re-runs (tell the owner to reload).

## Working with this owner
- A beginner who works mostly from a phone and sends screenshots; plain steps, exact button names, links when asked.
- Wants things built end to end and honest numbers over flattering ones. Appreciates being told what is untested.
- Never ask them to paste a secret; tell them where to put it. Offer the next step but don't stack unrequested work.

## Gotchas learned
- Tests: `AppTest` runs in-process, so monkeypatch module functions (e.g. `odds.get_game_lines`); patch
  `store.DB_PATH` and `cache.DB_PATH` to temp files; `at.metric` also matches Lotto's metrics (use the parlay's own
  label); `pandas.itertuples()` renames columns that start with `_`; `approx` doesn't work on a whole Series.
- Supabase: a 404 only means "tables missing" if it carries PostgREST's own error (PGRST205); any other 404 means a
  wrong `SUPABASE_URL` (an early version conflated them and misled the owner). Free projects pause after ~a week idle.
- GitHub release CDN occasionally returns a transient 502: retry. `pip install nfl_data_py` hangs/breaks: don't.
- nflverse: the Rams are `LA` in the schedule; names are mapped to full team names via the teams file.

## Known gaps
- NBA team-level injury flags and NBA matchups (opponent defense per stat) are not built; NBA injuries are
  per-player only and unverified.
- No per-user accounts: the no-bet list and record are shared by everyone who opens the app.
- Lines are cached all day (to save requests). The BetGuru tab and the props tabs show when they were pulled and
  have a "Refresh lines" button (3 requests, `odds.refresh_game_lines`, off when fewer than 3 are left). A refresh only
  re-buys that sport, and the BetGuru slate in session state is NOT rebuilt by a props-tab refresh (it warns "Newer
  lines were pulled" and the owner presses the free build button). Line movement compares only the first and latest
  pull of the day; there is no multi-day snapshot history.
- Results: the record keeps one ticket per betting day, sport and risk (`results.TicketExists` if you try a second,
  different one). Lotto and "(mixed)" tickets are one per day across sports.
- Phone layout is whatever Streamlit gives by default (owner marked it low priority).

## Next steps (suggested order)
1. Morning pre-warm + a real snapshot history (Supabase; needs a scheduled job: GitHub Actions or the owner's
   machine, since Streamlit Cloud can't run one). Spending Odds API requests on a schedule needs the owner's OK.
2. Verify live and fix: prop-leg grading, NBA injuries/finals, lotto saving, same-game parlay pricing. Then NBA team
   injuries and opponent-defense matchups.
3. (Done: lines pulled-at time, Refresh button and same-day line movement.)
4. Once there are ≥100 graded legs per sport, retrain/recalibrate on the live record (extend `train_weights.py` to
   read `picks_log`) and show calibration over time.
5. Phone layout polish. REA research is a separate session on the owner's machine.
