---
icon: lucide/list-ordered
---

# Playlist order & repeated songs

A playlist you made in the Library — with **New playlist**, **Save a copy**, [Detach from source](library-catalog.md#detach-an-imported-playlist) or [an import from your music folders](external-playlists.md) — keeps its songs in the order you choose, and can play a song more than once. Playlists that follow a Spotify, YouTube Music or Deezer link — or a Playlist Monitor watch — keep their source's order until their owner (or an admin) reorders them, and **Liked songs** is ordered by when you liked each song.

## Reorder a playlist

Each song of a playlist you may reorder has a grip (⋮⋮) at the start of its row — always shown on a phone, on hover with a mouse. Press it and drag the song up or down, with a finger or the mouse: the other songs slide aside to show where it will land, and the page scrolls when you reach the top or bottom of the screen. Let go and the song is in its new place at once; the order is saved in the background. If it can't be saved — someone changed the playlist meanwhile — the list goes back to the playlist's order and says so.

With the keyboard, focus a song's grip and press **↑** or **↓** to move it one place.

The list as it is shown becomes the order, even when it was sorted another way. Dragging is off while you search the playlist.

Moving a song switches the page's sort to **Playlist order**, so you see the order you just made. The order is written to the playlist's M3U file, which media servers that read it (Jellyfin, Navidrome, Plex) pick up too.

**Imported playlists** — those following a link or a watch — can be reordered the same way by their owner or an admin. They don't stop following their source: Castify remembers the order you chose, and every sync keeps it. Songs the source adds go at the end; songs it removes disappear. Detaching the playlist from its source makes that order its own for good.

The owner, admins and the playlist's [editors](collaborative-playlists.md) can reorder it. A few things keep it safe:

- **Nobody's change is lost.** If someone else added or removed a song while you were reordering, saving reloads the playlist and asks you to arrange it again instead of dropping their change.
- **Songs hidden from you stay put.** A song an admin [hid from users](users.md#hiding-from-users) is not in your list, and keeps its place in the playlist when you save.

## Repeat a song

Adding a song the playlist already has asks first:

- From **Add to playlist** in a song's **⋯** menu, a dialog says it is **Already in this playlist**: pick **Add anyway** to add it again at the end, or **Don’t add**. Adding several songs at once asks once about all the ones already there; the others are added either way.
- In the **Add songs** dialog on the playlist's page, songs already there are marked **Already added**. Ticking one adds it again.

Each copy is a row of its own: it plays in its place, has its own number, and can be moved on its own. **Save a copy** keeps the repeats. A playlist holds up to 500 songs, copies included.

## Remove one copy

**Remove from playlist** in a row's **⋯** menu takes out that copy only; the song's other copies stay where they are.

## For apps and scripts

- [`PUT /api/library/playlists/order`](../api-reference.md#put-apilibraryplaylistsorder) saves a new order: every song the caller sees, copies included, in its new place. `409` when the playlist changed in the meantime.
- [`POST /api/library/playlists/tracks`](../api-reference.md#post-apilibraryplayliststracks) takes `allow_duplicates` to add a song again, answers which songs it skipped as `already`, and takes `remove_entries` to remove one copy.
- Playlist rows from [`GET /playlists`](../api-reference.md#get-playlists) and [`GET /api/v1/playlists`](../api-reference.md#get-apiv1playlists) list a repeated song once per copy, in order. The Android app shows every copy; reordering is done in the web app.
