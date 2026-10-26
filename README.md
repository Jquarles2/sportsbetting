# BetGuru

A personal NBA/NFL betting research app, built to be honest about what the numbers can and can't do.

## What it does

**BetGuru tab (team vs team)**
- Loads FanDuel moneylines, spreads and totals for today's games (NBA) or this week's (NFL).
- Scans each team's recent games and, for the NFL, the weekly injury report.
- **Parlay builder** with a **risk level** (Safe / Balanced / Aggressive) and a leg count. One leg per
  game, never a leg it doesn't trust, and the expected value at fair odds shown (always negative: the
  sportsbook takes a cut on every leg, and the cut multiplies with each leg).
- **Player props as legs**: props you've already loaded and scanned in the props tabs can join the parlay,
  for today's games only and at no extra Odds API cost. They are priced at the book's fair odds (no invented
  edge), must also have been consistent lately (80% / 70% / 60% of the last 10 games for Safe / Balanced /
  Aggressive), and a player who is Out or on your no-bet list never makes a parlay.
- **Lotto of the day**: a long-shot ticket, say $0.50 to win $1,000, built from every slate you've built
  (both sports plus loaded props) with one leg per game. It shows the real odds ("1 in 4,000") and the
  expected loss, because it is a lottery ticket, not a strategy.
- **Game talks**: a short Claude-written preview of each game, using only the facts it is given.
- **No-bet list**: BetGuru's own (a quarterback who is Out or Doubtful, thin data, blowout spreads)
  plus **your own** teams, players and games.
- **Results**: save a parlay, grade it against final scores later, and see the record and a
  calibration table (did "60%" legs really hit 60%?). This is how the app learns from results.

**Props tabs (NBA props, NFL props)**
- Player props from FanDuel (points, rebounds, assists, threes, PRA; NFL passing/rushing/receiving
  yards and receptions): hit rates over the last 5/10/20 games, a filterable dashboard, a best 5/5
  parlay, and AI write-ups with injury and matchup facts.

## Be realistic about the model

The team-vs-team model is tuned with Bayesian optimization on 14 NFL seasons of real historical lines
and checked on seasons it never saw. The result: recent form adds almost nothing beyond what the
betting lines already price in, so the model stays close to the book's own probabilities. The NBA has
no free historical lines, so it is untrained and conservative. See the "Model and record" tab for the
numbers. Nothing here guarantees a winning bet. Gamble responsibly.

## Run locally

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then fill in your keys
streamlit run app.py
```

Keys (all in `.streamlit/secrets.toml`, which is git-ignored):

| Key | Where to get it | Needed for |
|---|---|---|
| `ODDS_API_KEY` | the-odds-api.com (free: ~500 requests/month) | all lines and props |
| `BALLDONTLIE_API_KEY` | balldontlie.io (paid plan for stats) | NBA stats |
| `ANTHROPIC_API_KEY` | console.anthropic.com (pay as you go) | AI write-ups and game talks (optional) |
| `SUPABASE_URL`, `SUPABASE_KEY` | supabase.com (free), see below | keeping your data across restarts (optional) |

## The Odds API budget (500 requests a month)

Everything is built around spending as little as possible. What costs requests, and what doesn't:

| Action | Cost |
|---|---|
| Game lines (moneyline, spread, total) for a sport | **3**, once per betting day per sport |
| Player props, one prop type | **1 per game** that you haven't already bought today |
| Quota balance, game counts, cost estimates | free |
| Scanning players or teams, parlays, the lotto, game talks, write-ups, grading, filters | free (they use stats sources or Claude, not the Odds API) |

How it saves requests:
- **Bought once, kept all day.** Answers are cached for the "betting day", which rolls over at 5 a.m. Eastern
  (not at midnight UTC, which is 8 p.m. Eastern), so checking in the evening never re-buys the morning's lines.
- **Saved in Supabase**, so an app restart doesn't lose them.
- **Props are bought per game.** Widening the window later pays only for the new games, and narrowing it back is free.
- **Today's games by default.** The NFL props tab starts on "Today" (one game on a Monday), not the whole week.
- **No started games.** Pre-game lines and props can't be bet once a game starts, so they aren't bought.
- **Props in BetGuru are free.** It reuses props you already loaded in the props tabs.

Rough monthly budget (estimates; games per night vary):

| Plan | About |
|---|---|
| Game lines: NBA every day + NFL on game days (Thu, Sun, Mon) | 130 |
| + NBA points props every day (around 7 games a night) | 340 |
| + one NFL prop type on game days (about 13 on a Sunday, 1 on Thursday and Monday) | 400 |
| + a second NBA prop type every day | over 550, so it blows the budget |

Good habits: load lines every day you plan to look, load props only for the one or two prop types you actually
use, and watch the "requests left" line under the title. If you outgrow the free plan, The Odds API sells paid
plans with far more requests (check their pricing page).

## Tests

```
python -m pytest
```

About 95 tests, none need the network. `tests/test_app.py` runs the whole app headlessly with fake data.

## Retrain the NFL model

```
python scripts/train_weights.py
```

Downloads nflverse games, tunes on 2012-2023, checks on 2024-2025 and writes `data/model_nfl.json`.

## Costs to keep an eye on

- **Odds API**: see the budget section below. The app shows the cost before every load and disables buttons
  you can't afford.
- **balldontlie**: calls are spaced to stay under the plan's rate limit, so a first scan of a whole slate
  takes a few minutes. Results are cached for the day.
- **Claude**: a fraction of a cent per write-up or talk (`claude-haiku-5-5`).

## Deploy to Streamlit Community Cloud (free)

1. **Merge to `main`.** Streamlit deploys one branch of your GitHub repo, and `main` is the usual choice.
2. Go to <https://share.streamlit.io>, sign in with GitHub, and click **Create app** (or **New app**).
3. Pick this repo, the `main` branch, and `app.py` as the main file.
4. Open **Advanced settings → Secrets** and paste your keys in TOML form (same names as above).
5. Click **Deploy**. The first build takes a couple of minutes while it installs `requirements.txt`.
6. **Protect your API quota.** Your keys are shared by everyone who opens the app. In the app's
   **Settings → Sharing**, choose *Only specific people can view this app* and add emails.

Notes:
- Without Supabase, the SQLite files in `data/` live on the server's disk, which is wiped whenever the app
  restarts or sleeps: you'd lose your no-bet list and results record and re-spend Odds API requests.
  Connect Supabase (next section) to prevent that.
- To update the app, merge to `main`. Streamlit redeploys automatically.

## Durable storage with Supabase (free)

Supabase gives you a small hosted database. BetGuru uses it for three things: your **no-bet list**, your
**results record**, and the **Odds API answers** (so a restart doesn't re-spend your monthly requests).
Without it, everything still works but is wiped on restart.

1. Create a free account at <https://supabase.com> and click **New project** (any name, any region, set
   a database password and keep it somewhere safe; BetGuru doesn't need it).
2. Open **SQL Editor → New query**, paste the whole of `docs/supabase_setup.sql`, and click **Run**. It
   creates three tables and locks them so only your secret key can read or write them.
3. Open **Project Settings → API** (the page may be called **API Keys**). Copy the **Project URL** and the
   **secret** key (older projects call it **service_role**). Do not use the "anon" or "publishable" key.
4. Put them in your secrets, either `.streamlit/secrets.toml` locally or **Manage app → Settings → Secrets**
   on Streamlit Cloud:
   ```toml
   SUPABASE_URL = "https://your-project-id.supabase.co"
   SUPABASE_KEY = "your-secret-key"
   ```
5. Reboot the app. On the **BetGuru** tab, open **No-bet list** (or **Model and record**) and press
   **Check storage connection**. You should see "Storage works", and a green box saying your data is saved
   in Supabase. Any problem shows up there in plain words (wrong key, tables not created, can't connect).

If the check button shows an error:

| It says | What it means | Fix |
|---|---|---|
| "has no 'nobet' table" (and names your project) | You're connected, but that project has no tables | Run `docs/supabase_setup.sql` in **that** project's SQL Editor, then `notify pgrst, 'reload schema';` |
| "SUPABASE_URL is probably wrong" | Supabase said "not found" for the address you gave | Copy **Project URL** from Project Settings, Data API. It's `https://<id>.supabase.co` with nothing after it |
| "the Supabase website, not your project" | You pasted a supabase.com dashboard link | Same: use the Project URL, not the browser address bar |
| "rejected the key" | Wrong kind of key | Use the **secret** key (`sb_secret_...`) or `service_role`, not publishable or anon |
| "Couldn't reach Supabase" | Network problem or the free project is paused | Open the Supabase dashboard; click **Restore project** if it's paused |

After fixing a secret, reload the page: Streamlit keeps showing the last error until something re-runs.

Good to know:
- The secret key can read and write everything in your project. Treat it like a password: keep it only in
  secrets, never in the code or in a chat.
- Supabase's free plan pauses a project after about a week with no use. If the app says it can't reach
  Supabase, open the Supabase dashboard and click **Restore project**.
- Everyone who can open your app shares the same no-bet list and record.

## Project layout

See `CLAUDE.md` for the full file-by-file map, workflow notes and next steps, and `docs/PLAN.md` for the
build history.

## Links

| What | Where |
|---|---|
| Your app, deploy, reboot, secrets, sharing | <https://share.streamlit.io> |
| Code and pull requests | <https://github.com/Jquarles2/sportsbetting> |
| Odds API (lines, props; usage and key under Account) | <https://the-odds-api.com> |
| balldontlie (NBA stats) | <https://www.balldontlie.io> |
| Anthropic console (Claude key, billing, spend limit) | <https://console.anthropic.com> |
| Supabase (storage) | <https://supabase.com/dashboard> |
| NFL data we read (nflverse) | <https://github.com/nflverse/nflverse-data/releases> |
| Streamlit docs | <https://docs.streamlit.io> |
