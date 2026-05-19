const CACHE_NAME = 'film-room-v5-phase1-cleanup';
const SHELL_FILES = ['./','./index.html','./manifest.webmanifest','./icon.svg','./favicon.ico','./apple-touch-icon.png','./assets/logo/logo-icon-32.png','./assets/logo/logo-icon-120.png','./assets/logo/logo-icon-152.png','./assets/logo/logo-icon-167.png','./assets/logo/logo-icon-180.png','./assets/logo/logo-icon-192.png','./assets/logo/logo-icon-512.png'];

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

  // Never answer API/function requests with cached index.html. That caused the "Unexpected token '<'" issue.
  if (url.pathname.startsWith('/.netlify/functions/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Only use app-shell fallback for page navigations, not JSON/API requests.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put('./index.html', copy));
          return response;
        })
        .catch(() => caches.match('./index.html'))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cached => cached || fetch(event.request).then(response => {
      if (url.origin === self.location.origin && response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
      }
      return response;
    }))
  );
});
