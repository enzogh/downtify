---
icon: lucide/cloud-off
---

# Offline listening

Like Spotify's **Download** switch, a playlist or an album can be kept on the phone or computer you're using, and it plays when there's no connection to your server: on a plane, in the metro, or when the server is off. Everything stays on that one device. Your library on the server doesn't change, and other devices have to download it on their own.

::: warning Needs HTTPS
Browsers only let a page store files when it's opened over **HTTPS**, or on `localhost`. When you open Castify at a plain `http://192.168.x.x:8000` address, the button shows up but tells you this. Put the server behind a reverse proxy with a certificate (Caddy, Traefik, Nginx Proxy Manager, a Tailscale HTTPS name…) to use it.
:::

## Downloading a playlist or album

Open a playlist or an album and click **Download to device**, next to the play and shuffle buttons. The button shows how far it has got (**Downloading 12/40**) and turns into **On this device** when every song is saved. You can keep browsing and playing while it works.

- Only songs that are in your library are saved. A playlist's songs that are only streamed (not downloaded on the server yet) are skipped. Download them to the server first, for example with **Download missing**.
- A song in two saved playlists is stored once.
- When the songs of a saved playlist change (songs added, removed or reordered), opening that playlist again brings the copy on this device up to date: new songs are downloaded and the removed ones are deleted.
- If a few songs can't be saved, the button says how many (**3 songs couldn't be saved — try again**). Clicking it again only fetches those.
- When the device runs out of space it stops and says **Out of space on this device**.

Click **On this device** to remove it from this device. It asks first and shows how much space that frees.

## On this device

**Library → ⋯ → On this device** (`/library/offline`) lists everything saved on this device, newest first. For each one you get the number of songs and their size, **Play**, **Shuffle**, **Open** (while you're online) and **Remove**. Click a row to see its songs and start one.

At the top you see how much space the saved songs use, how much the browser still lets Castify use, and whether the browser will keep the songs for good. **Remove everything** deletes every saved song from this device.

When the device goes offline, a bar above the player says **You're offline**, with a **Downloaded music** link to this page. The rest of the app needs the server, so it can't load while you're offline. The page and the player work without it.

## Playing offline

Saved songs play from the device even while you're online, so they don't use any data. Offline, the player works as usual on them: seeking, shuffle, repeat, **Up next**, the lock screen controls, the equalizer and [gapless playback](player.md#gapless-playback). The queue you had is remembered too.

Covers are saved with the songs. Lyrics, volume normalization levels and recommendations come from the server, so they're missing offline. A song plays at its file's own level until the connection comes back.

## How much it can hold

It's the browser that decides how much room a site gets, not Castify:

| Browser | Room for Castify |
|---------|------------------|
| Chrome, Edge, Samsung Internet (Android and computers) | Up to about 60 % of the device's total storage |
| Firefox | Up to 50 % of the disk once the songs are kept for good; otherwise 10 % of the disk, at most 10 GB |
| Safari 17 and later (iPhone, iPad, Mac) | Up to about 60 % of the device's total storage |

A song takes about 1 MB per minute at 256–320 kbps (MP3, M4A, OPUS), so a 4-minute song is about 8–10 MB. A FLAC file takes about four times that. In practice that's **thousands of songs** on a phone with a few dozen free gigabytes. **On this device** shows the real figure for your device.

Castify asks the browser to keep the songs for good (the [persistent storage](https://developer.mozilla.org/en-US/docs/Web/API/StorageManager/persist) permission). Installed apps usually get it without a prompt. Without it, the browser may delete them when the device runs low on space, and Safari also clears a site's data after seven days of use without opening it, unless Castify is [installed on the home screen](pwa.md). Removing site data in the browser's settings also deletes them.

## How it works

- `frontend/public/sw.js` is a service worker at the site root. It keeps the app itself (the page and its hashed files) for the current and previous version, so the app opens offline, and asks the server for the page first while it's online, so an upgrade still shows up at once. The server sends `sw.js` with `Cache-Control: no-cache`, so a new version of it is picked up on the next visit.
- Songs and covers are fetched by the page (`src/model/offline.js`) into the browser's Cache Storage (`castify-offline-v1`), along with an index of what was saved. The service worker serves `/downloads/…` and `/media/…` from it, answering the byte ranges an audio element asks for, and serves the saved cover of a song when `/cover` can't be reached.
- Nothing is sent to or stored on the server, and there's no setting or environment variable: it's per device, like the volume.
- The service worker is only registered by the production build that the backend serves (`make run` after `npm --prefix frontend run build`, or the Docker image), not by `npm run dev`.
