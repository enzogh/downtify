---
icon: lucide/users
---

# Jam

A Jam lets several accounts listen together. One person starts it, the others join with its code, and everyone adds songs to the same queue. Every device in the Jam plays the same song at the same moment, each on its own speakers or headphones.

Jams need [accounts](users.md): every member signs in to the same Castify server with their own account. Only songs already in the library can be added.

## Starting a Jam

The Jam opens in a sheet over whatever you're listening to, like Spotify's — no page to leave. Open it from the **Devices** button in the player (**Start a Jam**), the people button in the player bar, the **Jam** tile on the Search page or **Jam** in the side menu (on phones: **More → Jam**), then:

- **Start a Jam** opens an empty one.
- **Start with what's playing** takes the song playing now (at the same position) and the songs after it in your queue into the new Jam.

The sheet then shows a QR code to scan with a phone's camera and the Jam's six-character code. **Invite** opens the phone's share menu (**Copy link** where there is none) and **Copy code** copies the code: the link opens the Jam sheet with the code already filled in. While you're in a Jam, a blue strip above the player shows who's in and the code; tap it to open the sheet again.

## Joining a Jam

In the Jam sheet, type the code under **Join a Jam** (case, spaces and dashes don't matter; a pasted join link works too) and press **Join**. Joining another Jam leaves the one you were in.

As soon as you join, your player switches to the Jam's queue and catches up with the song and the position everyone else is at.

## Adding songs

While you are in a Jam, the usual queue actions feed the Jam instead of your own queue:

- **Add to queue** puts songs at the end of the Jam.
- **Play next** puts them right after the current song.
- **Play** on a song, album or playlist puts it right after the current song and starts it, for everyone.

The Jam sheet lists the shared queue with who added each song. Anyone can remove a song they added.

::: info Streams don't join
Songs that are only streamed (search results, Discover, charts) can't go into a Jam: everybody plays the same file from the library. Download a song first to share it.
:::

## Controlling playback

Play, pause, previous, next and seeking — from the player bar, the full-screen player, media keys or the Jam sheet — act on the Jam for everyone. A song that ends moves the whole Jam on to the next one.

The host can turn **Guests can control playback** off in the Jam sheet. Then only the host can play, pause, skip, seek, reorder or remove other people's songs; guests can still add songs and remove their own.

Shuffle, repeat and autoplay are off during a Jam: the shared queue plays in its order.

## Listening on another device

**Listen on this device** (on by default, remembered per browser) decides whether this device makes sound. Turn it off to use a laptop or phone as a remote for a Jam that plays on another device — your controls still work and the player still shows where the song is.

## Leaving and ending

**Leave** takes you out of the Jam; your player keeps its queue, paused. When the host presses **End Jam**, it ends for everyone.

A Jam lives in the server's memory: restarting the server ends every Jam, and a Jam nobody has touched for 12 hours is closed.

## How devices stay in step

The server keeps the Jam's clock: the current song, the position it was at and when, and whether it is playing. Every change is sent to the members over the [WebSocket](../api-reference.md#websocket), and each device works out where the song should be from that. A device more than two seconds off jumps back in step, which it checks every few seconds while playing.

The endpoints are listed under [Jam](../api-reference.md#jam) in the API reference.
