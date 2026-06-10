/* -----------------------------------------------------------------------------
 * Copyright (c) 2024 Franck OLLIVIER
 * Tous droits reserves.  PolyForm Strict License 1.0.0.
 * -----------------------------------------------------------------------------
 * ELY service worker -- network-first for navigations, cache shell for offline.
 *
 * Never caches:
 *   /api/*   -- backend REST  (privacy, freshness)
 *   /ws/*    -- WebSockets    (not cacheable anyway)
 *   /auth/*  -- auth endpoints (must never be stale)
 *   /tts/*   -- generated TTS audio (one-shot)
 * --------------------------------------------------------------------------- */

// Bump this on any sw.js change so browsers fetch the new file and the
// activate handler purges the old caches.
const VERSION = "ely-sw-v16";
const RUNTIME_CACHE = `${VERSION}-runtime`;
const SHELL_CACHE = `${VERSION}-shell`;

const SHELL_URLS = [
  "/",
  "/offline",
  "/manifest.json",
  "/icons/icon.svg",
];

const NEVER_CACHE_PREFIXES = ["/api/", "/ws/", "/auth/", "/tts/"];

// ---- Install: prefetch the shell -------------------------------------------
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => {
      return Promise.allSettled(
        SHELL_URLS.map((url) =>
          cache.add(new Request(url, { cache: "reload" })).catch(() => null),
        ),
      );
    }).then(() => self.skipWaiting()),
  );
});

// ---- Activate: cleanup old versions ----------------------------------------
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => !k.startsWith(VERSION))
          .map((k) => caches.delete(k)),
      ),
    ).then(() => self.clients.claim()),
  );
});

// ---- Fetch strategies ------------------------------------------------------
self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Only handle GET
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Never cache live endpoints
  if (NEVER_CACHE_PREFIXES.some((p) => url.pathname.startsWith(p))) {
    return; // let the browser handle it (no SW interference)
  }

  // Navigation requests -- network first, fall back to offline page
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(RUNTIME_CACHE).then((c) => c.put(request, copy)).catch(() => {});
          return resp;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          if (cached) return cached;
          const offline = await caches.match("/offline");
          return offline || new Response("Offline", { status: 503 });
        }),
    );
    return;
  }

  // Same-origin static assets -- stale-while-revalidate.
  // CRITICAL : every code path MUST resolve to a real Response object, never
  // undefined — otherwise the browser throws
  // "Failed to convert value to 'Response'" and the request hangs / fails.
  // This was the root cause of admin page load errors observed in the console.
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(request).then(async (cached) => {
        // Best-effort background refresh — never blocks the response below
        const refresh = fetch(request)
          .then((resp) => {
            if (resp && resp.ok) {
              const copy = resp.clone();
              caches.open(RUNTIME_CACHE)
                .then((c) => c.put(request, copy))
                .catch(() => {});
            }
            return resp;
          })
          .catch(() => null);

        if (cached) {
          // We have a cached version — serve it immediately, refresh in background
          refresh.catch(() => {});
          return cached;
        }
        // No cache — wait for the network. Guarantee a Response either way.
        try {
          const fresh = await refresh;
          if (fresh) return fresh;
        } catch {
          // fall through to safe Response below
        }
        return new Response("", { status: 504, statusText: "Gateway Timeout" });
      }),
    );
  }
});
