# Film Room v6 Working Overhaul

This build focuses on making Film Room useful immediately on draft day:

- Loads the daily multi-source player deck when available
- Falls back to live Sleeper player data if the deck is empty
- Adds on-demand ESPN fetches inside Deep Dive for missing stats, projections, and news
- Shows a clear Source Breakdown for Projection, Production, Market, Movement, News, and Context
- Adds position-specific stat cards
- Tightens the broadcast-style card/navigation design

## After upload

1. Upload the contents of this folder to the GitHub repo root.
2. Run `Actions → Refresh Film Room Data → Run workflow`.
3. Wait for Netlify to redeploy.
4. Open the app and test player cards / Deep Dive.
