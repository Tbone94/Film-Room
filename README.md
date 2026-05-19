# Gridiron Intel — GitHub + Netlify Function Build

This is the GitHub-ready version of **Gridiron Intel / Film Room Scout Network**.

It includes the static fantasy football app plus Netlify Functions for the Reddit Scout Network proxy.

## Why this version exists

The Reddit scan failed on static-only Netlify deploys because the browser was receiving HTML instead of JSON. The app needs a server-side proxy at:

```txt
/.netlify/functions/reddit-search
```

This project includes that proxy in:

```txt
netlify/functions/reddit-search.js
```

It also includes a simple health-check function:

```txt
/.netlify/functions/health
```

## Required folder structure

Keep this exact structure at the root of the GitHub repository:

```txt
index.html
manifest.webmanifest
sw.js
icon.svg
package.json
netlify.toml
netlify/functions/health.js
netlify/functions/reddit-search.js
```

## Netlify build settings

When connecting the GitHub repo to Netlify, use:

```txt
Build command: npm run build
Publish directory: .
Functions directory: netlify/functions
```

The `netlify.toml` file already defines these, but it is okay if Netlify asks you to confirm them.

## Test URLs after deploy

Replace `YOUR-SITE` with your Netlify site name.

### 1. Health check

```txt
https://YOUR-SITE.netlify.app/.netlify/functions/health
```

Expected:

```json
{"ok":true,"service":"gridiron-intel-netlify-functions","message":"Netlify Functions are deployed."}
```

### 2. Reddit proxy check

```txt
https://YOUR-SITE.netlify.app/.netlify/functions/reddit-search?subreddit=fantasyfootball&q=Ja%27Marr%20Chase&limit=3
```

Expected outcomes:

- JSON array of posts = proxy works.
- JSON error object = function deployed, but Reddit blocked the upstream request.
- HTML page / homepage / 404 = functions did not deploy correctly.
- Browser says Failed to fetch = request did not reach the function or the function crashed before responding.

## Important cache note

If you previously installed the app as a PWA or tested an earlier Netlify version, clear site data after deploy.

Desktop Chrome:

```txt
DevTools → Application → Storage → Clear site data
```

Phone/PWA:

```txt
Remove the home-screen app → clear browser site data for the Netlify URL → reinstall after the new deploy works.
```


Update 4.2 Navigation + Buzz:
- Removed Deep from bottom nav; player cards now open Deep Dive as a contextual overlay.
- Added Reddit Buzz Lens: automatic non-scraping buzz score from Sleeper trends, value gap, tags, role profile, and risk signals.
- Added quick Reddit search links for team subreddit, r/fantasyfootball, and r/nfl manual research.


Full UX overhaul update: Option A navigation, Deep Dive overlay, onboarding, search dropdown, smart filters, improved player cards, Buzz Lens, quick Reddit research links, dual trade search, waiver context cards, My Rankings tier dividers/jump controls/batch tagging, loading skeletons, haptic tag feedback, and updated PWA cache version.


## Mobile Polish Pass
- Simplified Board controls into a calmer mobile-first Board Control card.
- Moved advanced sort/tag/view/cheat-sheet controls behind a More toggle.
- Reduced front-page button clutter while preserving all power features.
- Improved position filtering with a single select plus optional quick chips.
- Updated PWA/service worker cache version.


## Mobile App Icon Patch
This build explicitly includes manifest icons, Apple touch icons, favicon.ico, root apple-touch-icon.png, and service worker cache entries so phones use the Film Room icon when added to the home screen. After deploying, remove the old home-screen icon and re-add the app so iOS/Android refreshes the icon.


## Killer Features Phase
Added Positional Scarcity Visualizer, Drop-Off Analysis, Story Behind the Score, Confidence Score, and Roster Construction Coach. These features use existing local player/ranking/trend/roster data and do not require Reddit API approval.


## v5 Phase 1 Product Cleanup
Removed prototype/developer copy, tightened section heroes, simplified Settings, added brand typography, reduced visual noise, shortened toasts, renamed Buzz Lens to Market Buzz, and kept existing draft tools stable.


## Multi-Source Data Phase 1

This build includes a daily GitHub Action and `scripts/fetch-all-sources.js` to generate `data/players.json` from Sleeper player data, Sleeper add/drop trends, nflverse previous-season stats, and ESPN headlines. The app loads `data/players.json` first and falls back to live Sleeper if the data deck has not been generated yet.


## v5 Multi-Source Phase 3
- Adds optional FantasyPros ECR parsing in the daily data builder.
- Adds source health diagnostics and source counts to data/players.json.
- Adds news sentiment scoring and stronger confidence/source display.
- All optional sources are non-blocking; Sleeper + static fallback remain intact.
