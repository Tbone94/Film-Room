const CACHE_NAME = 'commanders-pulse-v1';
const SHELL_FILES = [
  './',
  './index.html',
  './manifest.webmanifest',
  './favicon.ico',
  './apple-touch-icon.png',
  './assets/logo/logo-icon-192.png',
  './assets/logo/logo-icon-512.png',
  './assets/mascot/viz-hero.png',
  './assets/mascot/viz-analyzing.png',
  './assets/mascot/viz-celebration.png',
  './assets/mascot/viz-warning.png',
  './assets/backgrounds/bg-card.png',
  './assets/backgrounds/bg-studio.png',
  './data/reddit-pulse.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL_FILES))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);

  if (url.pathname.startsWith('/.netlify/functions/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  if (url.pathname.endsWith('/data/reddit-pulse.json') || url.pathname.endsWith('/data/reddit-pulse-history.json')) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          if (response.ok) caches.open(CACHE_NAME).then(cache => cache.put(event.request, response.clone()));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(() => caches.match('./index.html')));
    return;
  }

  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
});
