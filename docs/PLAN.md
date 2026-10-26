# Build plan

Each step is roughly one Sonnet session. Use `/clear` between steps.

1. **Setup**: Python project, requirements.txt, a "hello" Streamlit page, .gitignore. (Haiku)
2. **NBA stats**: given a player name, show their last 10 game logs. (Sonnet)
3. **Odds**: get a free key from the-odds-api.com, then fetch today's NBA player-point props and cache them in SQLite. (Sonnet)
4. **Hit rates**: for each prop, show how often the player went over the line in the last 5, 10 and 20 games, plus home/away splits. (Sonnet)
5. **Dashboard**: a sortable table of today's props by hit rate, with filters. (Sonnet)
6. **NFL**: repeat steps 2–5 with nfl_data_py. (Sonnet)
7. **Deploy**: Streamlit Community Cloud, then share the link with friends. (Haiku)
8. **Extras**: AI write-ups for each pick (Claude Haiku via the API), line-movement tracking, opponent defense rankings.

## Learning with REA (optional, step 8+)
Install it with `npx rea-agents setup` on your own machine. Point it at a competitor's public
website to understand its UI and feature design, then build your own version on the data above.
