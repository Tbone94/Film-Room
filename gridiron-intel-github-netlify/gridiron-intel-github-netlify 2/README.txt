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
