# Sports Props App

Personal NBA/NFL player-prop research tool. See `docs/PLAN.md` for the build plan.

## Run locally
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Community Cloud (free)

1. **Merge to `main`.** Streamlit deploys one branch of your GitHub repo, and `main` is the usual choice.
2. Go to <https://share.streamlit.io>, sign in with GitHub, and click **Create app** (or **New app**).
3. Pick this repo, the `main` branch, and `app.py` as the main file.
4. Open **Advanced settings → Secrets** and paste your keys in TOML form (same names as
   `.streamlit/secrets.toml.example`):
   ```toml
   ODDS_API_KEY = "..."
   BALLDONTLIE_API_KEY = "..."
   ANTHROPIC_API_KEY = "..."   # optional, only for the AI write-ups
   ```
5. Click **Deploy**. The first build takes a couple of minutes while it installs `requirements.txt`.
6. **Protect your API quota.** Your keys are shared by everyone who opens the app, and the Odds API
   free plan is only ~500 requests a month. In the app's **Settings → Sharing**, choose
   *Only specific people can view this app* and add your friends' email addresses.

Notes:
- The SQLite cache (`data/cache.db`) lives on the server's disk, which is wiped whenever the app
  restarts or goes to sleep. The app just refetches, and each button click shows what it costs.
- To update the app, push to `main`. Streamlit redeploys automatically.
