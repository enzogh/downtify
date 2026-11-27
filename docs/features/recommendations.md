---
icon: lucide/sparkles
---

# Recommendations

Home suggests music you don't have yet, picked from what you actually listen to: the **Discover mix** (artists you have never heard), **For you** (songs around the artists you love) and **Recommended for you**, a few songs to try right away. Everything they suggest streams until you download it.

## Where they show

| Where | What |
|-------|------|
| Home → **Made for you** | **Discover mix** and **For you** come first, before the [Daily Mixes](building-playlists.md#made-for-you). Each opens its own page: `/mix/discover`, `/mix/foryou`. |
| Home → **Recommended for you** | Six songs from **For you**, each saying why it is there (*Because you play PLK*). **See all** opens `/mix/foryou`. |
| A mix page | **Play**, **Shuffle**, **New picks** (another selection now instead of tomorrow) and **Download all (n)**, which queues every song the server still lacks. The **×** on a row is **Not for me**: that song is never suggested again on this device. |

Nothing is suggested in [library-only mode](library-only.md).

## Listening history

Every song the player plays becomes one row of your **listening history**, on the server, for your account — so a phone and a computer learn together. A row says how long the song played and whether it was **skipped**: stopped before a minute, before half its length and before its last seconds. A play of less than five seconds (a mis-tap, browsing a list) isn't kept. Streamed songs count as well as downloaded ones.

The player sends the rows in batches as songs end; a play made offline waits on the device and is sent later, and a song still playing when the app closes is kept where it stopped (not as a skip). The log each browser kept before this (library songs only) is sent once as history, so nobody starts from nothing. The server keeps a year of plays, 20,000 at most per account. The API is [`GET|DELETE /api/history`](../api-reference.md#get-apihistory) and [`POST /api/history/plays`](../api-reference.md#post-apihistoryplays).

## How songs are picked

1. **Your taste.** Every play weighs on its song and its artist: played through counts most, played in part a little less, a skip counts against. Older plays fade — a play loses half its weight in 30 days — and a song played over and over counts less and less, so one song on loop isn't your whole taste. Liked songs and songs added to the library lately count too, and the library alone speaks for someone with no history yet.
2. **Seeds.** Eight songs to start from: what is on heavy rotation, what you played these last days, and a few deeper picks drawn from further down that change every day. Never more than two of one artist, and never an artist you mostly skip.
3. **Candidates.** YouTube Music's radio mix of each seed. A song near the top of a radio counts more, and a song found by several seeds counts much more — it fits your taste, not one song.
4. **Shaping.** Songs on the server, songs you skipped, songs marked **Not for me** and [hidden artists](discover.md) are left out, and an artist you often skip counts less.
    - **Discover mix**: artists you don't know (no song on the server, never played through) come first; songs you already played through lately are left out.
    - **For you**: the artists you love count more. A song you keep streaming without downloading can come back (*You keep playing it*), a fifth of the list at most — on Home, one.
5. **Variety.** One artist appears at most twice (three times in **For you**) and never twice in a row, and one seed can't fill the list. A song offered day after day without being played steps aside for others.

The seeds and their radio mixes are kept for the day in the browser (the server keeps each radio for six hours), so the lists don't reshuffle while you listen; they are made again the next day, or at once with **New picks**.
