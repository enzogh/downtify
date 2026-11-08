---
icon: lucide/smartphone
---

# Install as an App (PWA)

Castify's web UI is a Progressive Web App: on both iOS and Android you can add it to your home screen and it launches full-screen, like a native app, with no browser address bar or navigation chrome.

## iOS (Safari)

1. Open Castify in Safari
2. Tap the **Share** button
3. Tap **Add to Home Screen**

The Castify icon appears on your home screen and launches in a standalone window.

## Android (Chrome)

1. Open Castify in Chrome
2. Tap the **⋮** menu
3. Tap **Add to Home screen** (or **Install app**, if Chrome offers it directly)

## How it works

`frontend/index.html` links a [web app manifest](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest) (`/manifest.json`) that sets `"display": "standalone"` and `start_url: "/"`, plus the icons Android uses for the home screen shortcut and app switcher. This is what Chrome/Android reads to install the app full-screen with its own icon.

iOS Safari doesn't read the manifest's `display` or icon fields at all for "Add to Home Screen" — it needs its own `apple-mobile-web-app-capable` and `apple-touch-icon` `<meta>`/`<link>` tags in `index.html`, which are set alongside the manifest so both platforms get the same standalone, full-screen behavior with the Castify icon.

There's no offline support or service worker — Castify's UI is only useful while it can reach the backend it's paired with, so this is "installable, full-screen web app," not an offline-capable one.
