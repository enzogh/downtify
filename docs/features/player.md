---
icon: lucide/headphones
---

# Built-in Player

Castify ships with a web player so you can listen to your downloaded music without a separate app. Hit play on any track, album, artist or playlist in the Library — or on a finished download in the Queue — and the player starts.

## Player bar

While a track is loaded, a player bar floats at the bottom of every page: cover art, title and artist, shuffle, previous, play/pause, next, repeat, elapsed/total time, and shortcuts to the lyrics and up-next panels (the lyrics one can be [hidden](#hiding-the-lyrics)). On wide screens it also has a volume slider and a seek bar along its top edge; on phones it shrinks to the essentials and shows a thin progress line.

Next to the title there is a heart to [like the song](liked-songs.md); phones leave it out of the bar to keep room for the title, and have it in **Now playing** and in the track lists instead.

Click the title or cover, or the expand button, to open **Now playing**.

On a phone, swipe the song in the bar to the left for the next song or to the right for the previous one, and hold it to open its menu (album, artist, lyrics, **Up next** and details).

When a song can't be played, the bar and **Now playing** say so and offer **Try again** — a song that isn't downloaded is looked up again — and **Skip**. A song that goes silent while it loads shows the loading state even when the browser doesn't report the wait (iPhones in particular), as soon as the progress stops moving for a couple of seconds.

## Playing on another device

Castify works like Spotify Connect between the places you're signed in to with the same account — browsers, tabs, the phone app. The **Devices** button in the player bar and in Now playing (green while music plays on another of them) opens **Connect to a device**:

- **This device**, with what plays here, and every other open device below it: playing ones first with their song, then paused ones, then idle ones.
- Pick another device to **send what plays here** there — the whole queue, the song and the spot in it — and this page pauses once it plays there. An iPhone won't start music nobody tapped for: it shows *Playback was sent here* with a **Play** button, and this page keeps playing (saying to tap Play over there) until it starts. Its own button pauses or resumes it from here.
- When music plays elsewhere and nothing plays here, a bar above the player shows that song with a green strip, **Playing on** *device*. **Listen here** (or **This device** in the list) brings the music — queue, song and spot — to this page and pauses the other device. A device that can't send its queue (the phone app) hands over its song alone. The cross hides the bar until that device plays another song.

Only your own devices show up, and a closed or reloaded tab leaves the list at once.

Changes to your playlists reach your other devices at once too: songs added, removed or put in another order show there without a reload.

## Now playing

A full-screen view tinted with colours picked from the current album cover:

- **Large cover art**, title and artist (click the artist or the *Playing from* label to jump to that artist, album or playlist), with a heart beside the title to [like the song](liked-songs.md). The cover and the lyrics shrink with the window — including when you only change its height — so they stay below the header.
- **Seek bar** — click or drag, or use the arrow keys when it's focused. While a track plays, soft waves drift over the played part in colours picked from the album cover; they settle flat when paused, and stay still if your system asks for reduced motion
- **Playback controls** — shuffle, previous, play/pause, next, repeat (off → repeat all → repeat one)
- **Volume** with mute toggle, saved between sessions. Hidden on phones, where the hardware buttons control the level
- **Sleep timer** — stop playback in 15, 30, 45, 60 or 90 minutes, or at the end of the current track. The remaining time shows next to the timer button
- **File info** — format and size of the playing file
- **⋯ menu** — add the song to one of your playlists (or a new one; a streamed song downloads into it first), go to its album or artist, and more. The player bar's song has the same menu on a long press

Four panels sit next to the cover on wide screens, or replace it on phones — their buttons sit under the controls there, in a row you can slide sideways with a finger when they don't all fit:

- **Lyrics** — time-synced lyrics highlight the current line and scroll with the song; click a line to jump there. Plain lyrics are shown as-is. Lyrics come from the `.lrc` file next to the track, or those embedded in its tags — see [Lyrics](lyrics.md). You can hide this panel — see [Hiding the lyrics](#hiding-the-lyrics).
- **Up next** — the play queue. Drag tracks to reorder them, remove single tracks, or clear everything after the current one.
- **Details** — title, artist, album, track number, year, length, format, size, date added and file path.
- **Equalizer** — shape the sound with ten frequency bands; see [Equalizer](#equalizer).

When the song changes, Now playing doesn't jump: the new cover fades in over the old one, the blurred background follows, and the title and lyrics slide out and back in. While Now playing is open, the lyrics of the next three library songs in **Up next** load ahead of time, so a song's lyrics are on screen as soon as it starts. Streamed songs have no saved lyrics and are skipped. With the system's *reduce motion* setting on, the change is instant.

Now playing is part of the page address (`?np=1`, plus `&panel=lyrics|queue|details|equalizer`), so the browser's Back button closes it and a reload keeps it open.

## Hiding the lyrics

Prefer the artwork and the queue without the words? Turn off **Settings → General → Player → Show lyrics in the player**. It applies at once, and takes away everything that leads to lyrics in the player:

- the **Lyrics** panel and its tab (on phones, its button in the Now playing footer);
- the lyrics button on the player bar;
- the `L` shortcut, which is also dropped from the shortcut list (`?`).

Now playing then opens on **Up next** instead. A link to `&panel=lyrics` from before you turned it off lands there too, rather than on an empty tab. The player doesn't ask for a track's lyrics at all while they're hidden.

::: info Hiding is not deleting
This only changes what the player shows. Your files keep the lyrics Castify embedded in them, and the `.lrc` files next to them stay in place, so media servers and other players still see them. Downloads keep fetching lyrics too — that's the separate **Download lyrics** setting under **Tags & lyrics** (see [Lyrics](lyrics.md)).
:::

Like the theme and the equalizer, the choice is saved in the browser (`localStorage`), so it is per device and per browser, not per Castify server — you can hide the lyrics on a phone and keep them on a desktop.

## Equalizer

A ten-band graphic equalizer, in the **Equalizer** panel of Now playing (or press `E`). It's marked **Experimental**: it may still change, and it may misbehave in some browsers (see [Browser support](#browser-support)).

- **Bands** at 31, 62, 125, 250, 500 Hz and 1, 2, 4, 8, 16 kHz, each ±12 dB in 0.5 dB steps. The 31 Hz and 16 kHz bands are shelves, so they also lift or cut everything below / above them. Drag a band, or focus it and use the arrow keys (`Page Up`/`Page Down` for 1 dB, `Home`/`End` for the limits); double-click resets it to 0.
- **Presets** — Flat, Bass boost, Treble boost, Vocal, Rock, Electronic and Acoustic. Moving any band afterwards turns the preset into **Custom**.
- **Preamp** — ±12 dB on top of everything.
- **On/off switch** and **Reset** (back to Flat, preamp 0, off). Moving a band or picking a preset also switches the equalizer on.
- The curve behind the sliders is the combined response of all bands.

Boosting bands would push loud music past full scale and distort it, so Castify automatically lowers the volume by the curve's highest boost — the panel says by how much. That keeps the peak at 0 dB, so a boosted preset reshapes the sound rather than just making it louder. Raising the preamp above 0 dB removes that safety margin, and the panel warns that loud passages may distort.

The settings are saved in the browser (`localStorage`) and apply to everything you play, in every tab, until you change them. They're per browser, not per Castify server.

### Browser support

The equalizer uses the Web Audio API, available in all current browsers. Until you switch it on, playback doesn't touch Web Audio at all. Once it's on, audio for the rest of the visit runs through it — switching off just flattens every band.

::: warning Safari on iPhone and iPad
iOS may pause Web Audio when the screen locks or you switch apps, which stops playback while the equalizer is on. If you listen with the screen off, turn the equalizer off and reload the page. Volume normalization uses Web Audio too. On an iPhone, Castify says so once, with a button that turns both off, and warns in their settings.
:::

## Building the queue

Playing an album, artist, playlist or the track list queues those tracks in order, starting from the one you picked. **Shuffle** on a collection starts it in a random order. Tracks you haven't downloaded play in full right in the queue, streamed live: the server relays YouTube's audio as it arrives, so a song starts within a second or two instead of after a download, and seeking works at once. While one plays, the next one is already being prepared one track ahead, and the two after it are looked up on the server too (when the song already points at its YouTube video), so playback runs through undownloaded rows without stopping — even after a double skip or a tap further down **Up next**, and even where the browser itself can't reach YouTube. When a song still isn't playing after a moment — being found, or waiting on a slow connection — the player bar and Now playing say so (**Finding the song…**, **Loading…**, then **Still loading…**) with a spinner on the play button, and the progress bar holds still until the sound actually starts. When matching an undownloaded track, the player skips search results more than 10 seconds away from its known duration. A streamed track is never saved or liked, but it stays in the remembered queue: after a reload it is matched again when it plays. To keep one, add it to a playlist: it downloads and moves in.

Every track's menu (the **⋯** button, or right-click on desktop) has:

- **Play next** — insert right after the current track
- **Add to queue** — append to the end
- **Go to album** / **Go to artist**
- **Save to this device** — download the file through the browser
- **Delete from library**

The same actions apply to a multi-track selection in the Library.

The queue, the current track, its position, shuffle and repeat are remembered, so reopening Castify resumes where you left off (queues of more than 2000 tracks aren't remembered). Deleted files drop out of the queue automatically.

**Autoplay** (Settings → General, or the switch at the top of **Up next**; on by default, saved per device) keeps the music going when the queue runs out. As soon as something plays, Up next lists ten songs like the last ones in the queue, under **Recommended · Autoplay**, right after it. Click one to play it now. When the queue reaches its last track they join it, and the next suggestions are fetched from its new end. Songs you haven't downloaded stream, and the next one is prepared ahead like any other streamed track, so playback carries on without a pause. With repeat on they stay listed but don't join the queue until you turn repeat off. Autoplay doesn't run in library-only mode.

Whatever comes next is prepared as soon as it is queued, and again 30 seconds before the current track ends if it still isn't ready, so a song added late (by autoplay or by hand) also starts without waiting.

**Fade between songs** (Settings → General) fades a song out over its last seconds and the next one in, from off up to 12 seconds. It applies when the queue moves on by itself. A song you pick yourself starts at full volume, and nothing fades when no song follows (the end of the queue, repeat one, or a sleep timer set to stop after the track). The setting is saved per device, like the volume.

## Gapless playback

**Gapless playback** (Settings → General, under **Fade between songs**; on by default, saved per device) runs songs into each other with no silence between them, the way a live album or a concept album was recorded. About 30 seconds before a song ends, the next one loads in a second, silent player, which starts a few milliseconds before the first one stops. The gap that remains is a few milliseconds at most, where loading the next song after the end of the first one used to leave a short silence.

- It only applies when the queue moves on by itself, and only while **Fade between songs** is off: a fade overlaps the songs on purpose, so the switch is greyed out then.
- The padding encoders add at the start and end of MP3 and M4A files is cut by the browser from the files' own gapless headers. Files without that header can keep a few milliseconds of silence that is in the file itself.
- Repeat one, a sleep timer set to stop after the track, and a [Jam](jam.md) (where the server keeps the devices in step) use the usual change.
- On an iPhone, Safari may refuse to start the second player without a tap. The song then loads in the usual player, with the short pause there was before.
- A song whose [volume level](playback-normalization.md) isn't known yet changes the usual way too, so it never plays a moment at the wrong level.

## Keyboard and media keys

| Key | Action |
|-----|--------|
| `Space` | Play / pause |
| `←` / `→` | Seek 5 seconds |
| `Shift` + `←` / `→` | Previous / next track |
| `↑` / `↓` | Volume |
| `M` | Mute |
| `S` | Shuffle |
| `R` | Repeat |
| `L` | Open lyrics (unless [hidden](#hiding-the-lyrics)) |
| `Q` | Open up next |
| `E` | Open the equalizer |
| `Ctrl` / `⌘` + `K` or `/` | Search |
| `Ctrl` / `⌘` + `F` | Search the playlist (on a playlist page) |
| `G` then `L` / `D` | Go to library / queue |
| `Esc` | Close now playing |
| `?` | Show all shortcuts |

Shortcuts are ignored while you type in a field or while a dialog is open.

The player also reports the current track to the operating system (Media Session), so lock-screen controls, headset buttons and keyboard media keys work, with the cover shown where the system supports it. As on Spotify, the lock screen of an iPhone or an Android phone (the installed app too) shows **previous** and **next** for a song, never 10-second jumps, with a progress bar you can drag.

## How it works

Tracks come from the library listing (`GET /tracks`), which reads title, artist, album, track number, year and length from each file's tags. Files are served from the `/downloads` static mount; slskd downloads [left in place](slskd-navidrome.md#leave-files-in-place) are played through `/media/slskd/…`. Cover art comes from `/cover` and lyrics from `/lyrics` — see the [API reference](../api-reference.md#file-management).

Playback uses the browser's native HTML5 audio. No plugins, no extra processes.

## Supported formats

The player can play any format your browser's HTML5 audio engine supports. This typically includes MP3, M4A/AAC, OGG and OPUS in all modern browsers. FLAC support varies — Chrome and Edge support it natively; Firefox and Safari may not.
