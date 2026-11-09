---
icon: lucide/list-plus
---

# Building playlists

Playlists you create in the Library work like a streaming service's. Any song can go into one, whether it is already downloaded or not. The library is one place to pick songs from, and a search is another.

## Adding songs that aren't downloaded yet

Songs from a search, the charts or the recommendations below a playlist can go straight into a playlist you created (or one shared with you as an [editor](collaborative-playlists.md)):

- the **+** button on a search result, or a right click on it, then **Add to playlist** → the playlist (or **New playlist**);
- **Add songs** on the playlist page: the search box looks in the library *and* for new songs, listed under **Not in your library yet**;
- dragging the song onto a playlist in the sidebar.

A song that is already in the library goes into the playlist at once. Any other song is queued for download and shows on the playlist page under **songs downloading**. You can play it there straight away (it streams), and it moves into the playlist, at the end, as soon as its download finishes: an open playlist page shows it there without a reload, on every device and for every editor. The same happens when the queue finds the song already in the library. If a download fails, the song stays in that list until you retry it from the [queue](download-queue.md) or take it out with the **×** next to it.

::: info Where the waiting songs live
A playlist's M3U file only ever lists files that exist, so media servers reading it never see a missing song. The songs still waiting are kept in Castify's database (`/data/downtify_library.db`). Renaming the playlist keeps them, and deleting it forgets them.
:::

In [library-only mode](library-only.md) nothing can be downloaded, so the **+** button and the **Not in your library yet** list are hidden.

## Drag and drop

Drag any song from a track list (an album, an artist, the Library, a playlist) or from a search result — the **Top result** card included — to add it to a playlist. To drag several songs at once, select them first.

As soon as you start dragging, an **Add to a playlist** panel opens on the right with every playlist you can add to (yours, empty ones included, and those shared with you as an editor). Drop the songs on one of them, or on **New playlist…** to create a playlist with them. On a wide screen you can also drop onto the playlists in the sidebar.

## Recommended songs

Below a playlist you can edit, **Recommended songs** suggests ten songs that fit it. They come from YouTube Music's radio mixes of a few of its songs, most recently added first, and leave out what the playlist already has. **Add** puts a song into the playlist and downloads it when needed. **Refresh** uses other songs of the playlist to suggest again.

The suggestions are kept in the browser for a day, so opening the playlist again shows them at once without asking YouTube Music. They are made again when a new song lands in the playlist, when you press **Refresh**, or after that day. The server also keeps each radio mix for six hours, so other playlists and devices that start from the same songs get them straight away.

## Search

When you search, the results open with a **Top result**: the artist, album or song your search names (the first song otherwise). Its first songs sit beside it, as on Spotify. **In your library** lists the matching songs you already have, including those from [extra folders](external-library.md), which play straight from disk. A song you already have is marked with a small green check rather than a download button.

## Made for you

Home shows up to four **Daily Mix** playlists, plus **On repeat** once you have played some songs often enough. Each opens its own page (`/mix/1` … `/mix/4`, `/mix/repeat`) with the list and **Play** / **Shuffle**.

A daily mix is led by one artist you play (or like, or simply have the most songs from) and held together by YouTube Music's radio mix for one of their songs:

- up to half of it is that artist's songs from your library;
- then songs you have by the artists of that radio mix;
- then the radio mix's own songs, streamed until you download them.

An artist that isn't in that radio mix never ends up in the mix. A mix keeps the same order for the day and is made again the next day; the radio mixes are kept in the browser for the day. In [library-only mode](library-only.md) a mix is the lead artist's songs alone. **On repeat** lists the songs you played at least three times in the last 30 days.

The mixes use a listening log kept on this device: a song counts once it has played for 30 seconds. The log is stored only in the browser (`localStorage`) and keeps 30 days. Nothing about it is sent to the server, so each device has its own mixes.
