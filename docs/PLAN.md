# Build plan

Each step is roughly one session. Use `/clear` between steps; `CLAUDE.md` carries the context.

## Done

1. **Setup**: Python project, requirements.txt, Streamlit page, .gitignore.
2. **NBA stats**: a player's last 10 game logs (balldontlie, since stats.nba.com blocks cloud hosts).
3. **Odds**: FanDuel player props from The Odds API, cached in SQLite.
4. **Hit rates**: over rates over the last 5/10/20 games, plus home/away splits.
5. **Dashboard**: sortable, filterable props table, best 5/5 parlay.
6. **NFL**: the same for NFL using nflverse data (read directly; `nfl_data_py` is unmaintained).
6.5. **Game lines**: FanDuel moneylines, spreads and totals with each team's recent win/cover/over rates.
7. **Deploy**: Streamlit Community Cloud guide in the README (the owner deploys from `main`).
8. **Extras (part 1)**: AI write-ups with injury and matchup facts (Claude Haiku), Odds API usage guard,
   NBA prop types (rebounds, assists, threes, PRA), balldontlie rate limiting.
9. **BetGuru** (this was the investors' request):
   - team-vs-team model, backtested on real NFL lines with Bayesian optimization
   - parlay builder with Safe / Balanced / Aggressive risk and a leg count
   - AI game talks
   - no-bet list: automatic (QB out, thin data, blowout spreads) plus your own
   - results log that grades parlays and shows a calibration table
   - rebrand to BetGuru with BetGuru / NBA props / NFL props tabs
10. **Durable storage** (Supabase): no-bet list, results record and Odds API answers survive restarts;
    local SQLite fallback when Supabase isn't configured; "Check storage connection" in the app.
11. **Props as parlay legs, lotto of the day, API savings**: prop legs in BetGuru (book's fair odds, consistency
    filters, injury flags, graded from stat lines); a lotto ticket mixing sports; betting-day cache, per-game
    props cache, NFL props default to today, started games never bought.
12. **Today-only slates, combined slates, legs per game**: the NFL slate is the next 24 hours (not started);
    parlays combine every built slate; 1 to 3 legs per game with near-duplicate pairs blocked; Supabase
    connected to a real project and working.

## Next

1. **Morning pre-warm** + **line-movement tracking** (needs stored snapshots, now possible in Supabase).
2. **Verify live**: prop-leg grading, NBA `/player_injuries`, NBA finals (`/games`), and how FanDuel really prices a
   same-game parlay versus the product of odds we show. Then NBA team injury flags and opponent-defense matchups.
3. ~~**Show when lines were pulled** and offer a refresh button~~ Done on the BetGuru tab (3 requests a refresh).
4. **Learn from the live record**: retrain/recalibrate once there are ≥100 graded legs per sport.
5. **Phone layout polish** (low priority).

## Learning with REA (optional)
Install it with `npx rea-agents setup` on your own machine. Point it at a competitor's public
website to understand its UI and feature design, then build your own version on the data above.
