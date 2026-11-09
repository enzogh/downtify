---
icon: lucide/share-2
---

# Sharing a song

Like Spotify's **Share → Copy link**, any song in your library can be sent to someone as a link. Whoever opens it can listen to that song in their browser **without an account and without signing in** — and sees nothing else on your server.

## Making a link

Open a song's **⋯** menu (or right-click it, or long-press it on a phone) in any track list — an album, an artist, the Library, a playlist — and choose **Share link**.

- On a computer the link is copied to the clipboard.
- On a phone your system's share sheet opens, so you can send it straight to a messaging app.

Asking again for the same song gives the same link back. The link looks like `https://your-server/s/AbCdEf…`.

::: warning The link only works where the server can be reached
A link points at the address you opened Castify with. If that is `http://192.168.1.20:8000`, it only works on your home network. To share with people outside, open Castify through the public address you set up (see [Behind a reverse proxy](mobile-apps.md#behind-a-reverse-proxy)) before you copy the link.
:::

## What the person you send it to sees

A page with the song's cover, title, artist and album, and a player. Messaging apps that show link previews show the cover and title too. The page plays only that one song: there is no download button, no way to browse the library, and search engines are told not to index it.

## When a link stops working

A link plays nothing — it answers *not found*, as if it had never existed — when:

- the song was deleted (or moved to the [music trash](music-trash.md));
- an admin [hid the song from users](users.md#hiding-from-users), or its album or artist;
- an admin turned the whole feature off (below).

A song rewritten in place — by a [library upgrade](library-upgrade.md) or [Replace Audio](replace-audio.md) — keeps its links.

## Turning it off

Song links are on by default. An admin can turn them off with **Settings › Library › Allow public song links**. While it is off nobody can make a link and every existing link stops working; they all work again when it is switched back on.

Anyone who has a link can listen to the song as often as they like and pass the link on, so leave this off on a server whose music shouldn't leave the house.

## For scripts

The endpoints are listed in the [API reference](../api-reference.md#song-links).
