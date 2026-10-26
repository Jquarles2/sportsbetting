# BetGuru

A personal NBA/NFL betting research app, built to be honest about what the numbers can and can't do.

## What it does

**BetGuru tab (team vs team)**
- Loads FanDuel moneylines, spreads and totals for today's games (NBA) or this week's (NFL).
- Scans each team's recent games and, for the NFL, the weekly injury report.
- **Parlay builder** with a **risk level** (Safe / Balanced / Aggressive) and a leg count. One leg per
  game, never a leg it doesn't trust, and the expected value at fair odds shown (always negative: the
  sportsbook takes a cut on every leg, and the cut multiplies with each leg).
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

- **Odds API**: props cost 1 request per game per prop type; game lines cost 3 per sport. The app shows
  the cost before every load and disables buttons you can't afford.
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

Good to know:
- The secret key can read and write everything in your project. Treat it like a password: keep it only in
  secrets, never in the code or in a chat.
- Supabase's free plan pauses a project after about a week with no use. If the app says it can't reach
  Supabase, open the Supabase dashboard and click **Restore project**.
- Everyone who can open your app shares the same no-bet list and record.

## Project layout

See `CLAUDE.md` for the full file-by-file map, workflow notes and next steps, and `docs/PLAN.md` for the
build history.
