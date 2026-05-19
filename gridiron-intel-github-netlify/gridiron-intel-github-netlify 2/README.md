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
