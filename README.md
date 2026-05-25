# Commanders Pulse

A fresh Washington Commanders fan dashboard powered by a scheduled GitHub Action that writes `data/reddit-pulse.json`.

## What is included

- Fresh static app in `index.html`
- Commanders Pulse mood meter
- Hot topics board
- Player buzz rankings
- Hype vs concern cards
- Community headline list
- Admin manual-paste fallback
- PWA manifest/icons
- GitHub Action: `.github/workflows/scrape-reddit.yml`
- Python scraper: `scripts/scrape-commanders-reddit.py`
- Seed files: `data/reddit-pulse.json` and `data/reddit-pulse-history.json`

## Deploy

Netlify publish directory should be the repo root / `.`. The ZIP has `index.html` at the root.

## Run the pulse builder

1. Push this project to GitHub.
2. Go to GitHub → Actions → **Build Commanders Pulse**.
3. Click **Run workflow**.
4. Wait for the workflow to commit `data/reddit-pulse.json`.
5. Refresh the Netlify site.

No Reddit username, password, OAuth token, or app approval is needed for this version.

## Local testing

```bash
python -m http.server 8080
```

Open `http://localhost:8080`.

To test the scraper locally:

```bash
pip install -r no root requirements.txt
python scripts/scrape-commanders-reddit.py
```

The scraper is a best-effort public community signal, not an official report or a factual player evaluation.


## Visual refresh

This build swaps out the old Film Room imagery and uses the newer custom burgundy/gold visual pack supplied by the user for hero and card backgrounds.


## Netlify dependency note

There is intentionally no root `requirements.txt` file in this build. Netlify should only run the static app build. The GitHub Action scraper uses Python standard-library public Reddit JSON requests, so it does not need `yars` or any pip dependency install.
