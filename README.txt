GRIDIRON INTEL — FILM ROOM / SCOUT NETWORK PHASE A — PROXY HARDENING HOTFIX

WHAT THIS FIXES
- Prevents the service worker from answering Netlify Function/API requests with cached index.html.
- Bumps the service worker cache name so old app-shell caches are replaced.
- Adds strict content-type/body checks before JSON parsing.
- Shows a clearer error if the Netlify Function is missing or returning HTML.
- Uses the Netlify Function first and only tries direct Reddit as a last resort.

WHY YOU SAW "Unexpected token '<'"
The app expected JSON but received HTML. The most common causes are:
1. The Netlify Function is not deployed, so Netlify returns an HTML 404/app page.
2. The old service worker served cached index.html for the function request.
3. Reddit returned an HTML block page instead of JSON.

IMPORTANT AFTER DEPLOYING THIS HOTFIX
Because the old service worker may still be cached on your phone/browser, do this once:
- Chrome desktop: open the site, press Cmd+Shift+R / Ctrl+Shift+R.
- If it still shows the old error, go to DevTools > Application > Storage > Clear site data, then reload.
- On phone: clear the site data/cache for your Netlify app or uninstall/reinstall the PWA icon if you added it to the home screen.

DEPLOYMENT
Deploy the FULL folder, not just index.html:
- index.html
- manifest.webmanifest
- sw.js
- icon.svg
- netlify.toml
- netlify/functions/reddit-search.js

Best deployment method:
1. Put this folder in a GitHub repo.
2. Connect the repo to Netlify.
3. Netlify deploys the static site and the function together.

FUNCTION TEST
After deployment, visit:
https://YOUR-SITE.netlify.app/.netlify/functions/reddit-search?subreddit=fantasyfootball&q=Ja%27Marr%20Chase&limit=3

Expected result:
- JSON array of Reddit post objects = proxy works.
- HTML app page/404 = function did not deploy or old service worker/cache is still interfering.
- JSON with an error field = function deployed, but Reddit blocked/failed the upstream request. Manual paste remains available.


Visual cleanup update: added /assets folder, Film Room branding, header banners, mascot states, improved empty/loading states, and updated PWA icon references.


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


v5 Phase 2: added Player Intel architecture, curated starter scouting reports, richer fallbacks, ESPN latest news panel, and handcuff quick reference.
