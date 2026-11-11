"""FastAPI router exposed by Downtify.

This module is the facade: the routes themselves live in per-domain
modules - ``system_routes`` (version, health, settings, cookies,
connection tests, ``/api/ws``), ``discover_routes`` (search, discover,
finder, URL resolving), ``artist_routes``, ``download_routes``
(downloads and the queue), ``library_routes``, ``playlist_routes``,
``stream_routes`` and ``monitor_routes`` - on top of the shared
``api_core`` (``state``, ``ConnectionManager``, settings, who is asking
and what they may see) and ``api_pipeline`` (the download pipeline).
:data:`router` (defined in ``api_core`` with the library-only guard)
holds every route: importing the route modules registers theirs on it.
Each module keeps its routes in their old order, and no path of one
module overlaps a path of another, so which module registers first
doesn't matter. Every name they define stays reachable as
``api.<name>``; see :class:`_Facade` for how a patched
``api.<name>`` reaches the module that uses it.

The endpoints intentionally mirror the surface that the previous
``spotdl``-powered backend exposed so the existing Vue frontend keeps
working without changes.

The library is shared: every account browses every downloaded track,
album and artist - minus what an admin hid from users (see
:mod:`downtify.library_visibility`, ``GET|POST /api/library/visibility``
and ``docs/features/users.md``). Likes, playlists, batches and queue
jobs stay per-user (a ``user`` sees their own; an ``admin`` sees
everything), and who downloaded a file (:mod:`downtify.track_owners`)
decides who may delete it. Playing, streaming, searching and asking for
downloads are shared, and files are never stored twice.

* ``GET  /api/version``
* ``GET  /api/health`` (liveness probe for the Docker ``HEALTHCHECK`` -
  see ``healthcheck.sh``; always ``200`` once the server can answer
  requests, regardless of downloader/monitor readiness)
* ``GET  /api/songs/search``
* ``GET  /api/artists/search``
* ``GET  /api/discover/chart`` (Deezer's own global "what's trending"
  chart - no auth, no genre filter - as ``{tracks, albums, artists,
  playlists}``; tracks are shaped like ``/api/songs/search``
  (``source: 'deezer'``, plus ``preview_url`` when Deezer offers a 30s
  clip) and downloadable the same way; albums/artists/playlists are
  read-only summaries - Downtify has no Deezer discography resolver,
  so their ``url`` only opens on Deezer, unlike a YouTube Music/Spotify
  result)
* ``GET  /api/finder/search`` (the Finder page's Deezer-only free-text
  search: ``{songs, albums, artists}``; songs shaped like the chart's
  tracks plus ``deezer_artist_id``/``deezer_album_id``, albums/artists
  as summaries with Deezer ids, fans and track/album counts)
* ``GET  /api/finder/artist`` (``artist_id``, ``lang``: a Deezer
  artist's photo, fans, album count, plain-text ``bio``, ``social``
  links, ``related`` artists and ``top_songs``)
* ``GET  /api/finder/artist/songs`` (``artist_id``, ``name``: the
  artist's songs as a Finder search's ``{songs, albums, artists}`` - a
  name search kept to rows by that Deezer id; albums/artists empty)
* ``GET  /api/finder/artist/albums`` (``artist_id``: their whole
  discography, most recent first; ``track_count`` is ``null`` until
  known)
* ``GET  /api/finder/albums/track_counts`` (``ids``, comma-separated, 50
  at most: ``{album_id: track_count}`` for the ones Deezer answered -
  throttled under Deezer's request quota)
* ``GET  /api/finder/album`` (``album_id``: label, genres, UPC, length,
  fans, contributors and ``tracks``, downloadable song rows)
* ``GET  /api/artists/top_songs`` (an artist's "Top songs" shelf preview,
  same shape as ``/api/songs/search`` - no further pagination offered)
* ``GET  /api/artists/top_albums`` (an artist's 5 most popular albums,
  sorted by YouTube Music's own "Popularity" order; same shape as
  ``/api/albums/search``; for every album/single, use ``/api/url`` on
  the artist's channel URL instead)
* ``GET  /api/artists/info`` (an artist's own profile: name, thumbnail,
  bio - not their releases)
* ``GET  /api/artists/similar`` (an artist's "Fans might also like"
  shelf, same shape as ``/api/artists/search``)
* ``GET  /api/artists/art`` (``{photo_url, banner_url, photo_version,
  banner_version}`` - the version, the file's modified time in ms, goes in
  the URL as ``?v=`` so a replaced image isn't served from a browser
  cache - whichever of an
  artist's saved photo/banner sidecar files exist under
  ``/downloads/.metadata/...``)
* ``GET  /api/artists/photo-proxy`` (DISPLAY-ONLY photo of an artist
  that has no saved one - a related artist, or a Library artist (in the
  grid and on its own page) nobody picked a photo for - relayed from
  Deezer and never stored - see
  ``downtify.artist_photo_proxy``; browser-cached for three hours - a
  photo, or Deezer having none (404) - but a photo already saved locally
  is served uncached instead, and a failure is a 503 that is never cached;
  ``?url=``, optional, is the artist's Deezer picture when the page
  already has it - Discover, the Finder - base64url-encoded, relayed
  without a search by name)
* ``POST /api/artists/art/bulk`` (the same, for many artists at once -
  body ``{names}``, response ``{<name>: {photo_url, banner_url,
  photo_version, banner_version}}`` - used
  by the Library page's artist grid)
* ``GET  /api/artists/art/search`` (free-text artist photo candidates from
  YouTube Music + Deezer, each ``{source, name, image_url}``)
* ``GET  /api/artists/art/spotify_candidate`` (a Spotify photo or banner
  candidate - ``kind`` query param - resolved from one already-downloaded
  track's Spotify id when ``file`` gives one (see
  ``downtify.track_index``), else from an exact-name search on the
  optional ``name`` param)
* ``POST /api/artists/art/from_url`` (fetch and save a chosen candidate or
  a pasted image link as an artist's photo or banner)
* ``POST /api/artists/art/upload`` (save an uploaded photo/banner - the
  raw image bytes as the request body, like ``POST /api/cookies``)
* ``DELETE /api/artists/art`` (remove a saved photo or banner)
* ``GET  /api/artists/profile`` (an artist's saved profile JSON: bio,
  origin, formation year, group flag, banner colour, social links,
  related artists, platform ids, which source their current photo/
  banner came from - a blank skeleton if nothing was saved yet; never
  seeds one, see ``POST .../ensure`` below for that)
* ``GET  /api/artists/top_songs/spotify`` (the artist's first five Spotify
  top songs, same shape as ``/api/artists/top_songs/url`` plus
  ``fetched_at``/``stale`` - read from ``.metadata/ArtistTopSongs/`` while
  fresh (7 days), fetched and saved when missing, refreshed in the
  background when stale; needs ``platforms_id.spotify`` in the profile)
* ``POST /api/artists/profile/ensure`` (seed a brand-new artist's
  profile the first time it's needed - Spotify/YouTube Music photo and
  banner (each only when its ``download_cover_art_artist``/``..._banner``
  setting is on), then everything ``.../bio`` below would fetch - a no-op
  once a profile file exists at all, even an empty one; body
  ``{name, lang, track_files}``)
* ``POST /api/artists/profile/bio`` (fetch bio and save it - Apple Music
  primary (also brings origin/formation year/genre/group flag/banner
  colour), Deezer secondary (bio fallback + social links + related artists) -
  body ``{name, lang, source?}`` (``source`` = ``applemusic`` or ``deezer``
  to save only that service's bio, no fallback; default: both, in that
  order); resolves and caches the artist's Apple Music/Deezer ids on first
  use)
* ``POST /api/artists/profile/bio/preview`` (one service's bio text only -
  body ``{name, lang, source}``, ``source`` = ``applemusic`` or ``deezer``;
  response ``{bio}``; saves nothing, the edit modal loads it into its text
  box and the user keeps it with ``PUT .../bio``)
* ``DELETE /api/artists/profile/bio`` (clear only the saved bio text -
  everything else is kept)
* ``PUT  /api/artists/profile/bio`` (manually set the bio text directly -
  body ``{name, bio}``; the user's own text, never fetched)
* ``PUT  /api/artists/profile/social`` (manually set all five social
  links directly - body ``{name, social: {twitter, facebook, website,
  instagram, youtube}}``; replaces the whole object, never fetched)
* ``GET  /api/song/url`` and ``GET /api/url`` (alias; ``/api/url`` also
  resolves an artist channel/``@handle`` (YouTube Music) or artist link
  (Deezer) URL into every one of their albums/singles as lightweight
  summaries, same shape as ``/api/albums/search`` - no tracklists;
  resolve a chosen release's tracks separately). A YouTube Music or
  Deezer playlist URL resolves to its tracks, like a Spotify playlist.
  Accepts a Spotify, YouTube Music or Deezer track/album/playlist URL,
  or a SoundCloud track URL (plus a YouTube Music/Deezer artist URL, as
  above).
* ``GET  /api/url/resolve`` (the same links, always as
  ``{kind, name, subtitle, cover_url, year, tracks, albums}`` - adds the
  playlist/album name and cover the plain track list lacks; a Deezer
  track's own ``preview_url`` survives into its song row, same as
  ``/api/discover/chart``)
* ``GET  /api/artists/top_songs/url`` (a Spotify, YouTube Music or Deezer
  artist URL - ``open.spotify.com/artist/...``, ``/channel/UC...``,
  ``/@handle`` or ``deezer.com/artist/...`` - resolved to ``{source,
  artist_id, name, cover_url, songs}``: the artist's own "Popular" /
  "Top songs" / "top" shelf, in the order the source ranks it)
* ``POST /api/download/url`` (optional JSON body: resolved Spotify row so
  ``track_number`` / ``album_track_total`` survive re-fetch by URL; a
  ``"source": "deezer"`` body is taken as-is instead, see
  ``_song_from_download_request``)
* ``POST /api/download/batch`` (JSON body ``{songs, playlist_url,
  generate_m3u}``; instead of ``playlist_url`` a caller may pass an
  explicit ``playlist_name`` and ``cover_url`` - e.g. an artist's top
  songs selection, which isn't backed by a real playlist id; a Deezer
  ``playlist_url`` gets the same per-playlist folder, M3U and cover as a
  Spotify/YouTube Music one, but isn't tracked as a resumable batch)
* ``POST /api/download/album`` (YouTube Music album/browse URL only;
  downloads every track from one shared, already-resolved tracklist so
  metadata stays consistent across the whole release)
* ``POST /api/download/csv`` (import a library-export CSV from Soundiiz,
  TuneMyMusic, Exportify, etc.; JSON body ``{csv, playlist_name,
  generate_m3u}`` - the raw CSV text, read client-side, not a multipart
  upload)
* ``POST /api/playlist/m3u``
* ``GET  /api/queue``, ``DELETE /api/queue``, ``DELETE /api/queue/item``
  and ``DELETE /api/queue/completed`` (drop finished jobs only); rows
  carry ``mine`` and, for an admin, ``users`` (who asked for it).
  ``DELETE /api/queue/others`` (admin: drop every job they aren't
  waiting on)
* ``GET  /api/queue/state``, ``POST /api/queue/pause`` and ``POST
  /api/queue/resume`` (``{paused, state, active}``: a paused queue starts
  nothing new and lets running downloads finish - ``state`` is
  ``running``, ``pausing`` while some still run, then ``paused``; the
  switch and the unfinished jobs survive a restart, see
  :mod:`downtify.download_queue`)
* ``DELETE /api/library/playlist`` (delete a downloaded playlist's
  tracks, M3U and catalog entry; a manual playlist only loses the M3U)
* ``GET  /api/library/summary`` (Home page: counts + recent albums)
* ``GET  /api/library/albums`` (Library albums tab: albums without tracks)
* ``GET  /api/library/artists`` (Library artists tab / Discover)
* ``POST /api/library/lookup`` (search/link songs already in the library)
* ``POST /api/library/playlists`` (create an empty editable playlist)
* ``POST /api/library/playlists/tracks`` (add or remove tracks on a
  manual playlist - its owner's, or one shared with you as an editor;
  ``allow_duplicates`` adds a song it already has again,
  ``remove_entries`` takes out one copy of a repeated song)
* ``GET|POST|DELETE /api/library/playlists/pending`` (songs added to a
  manual playlist before they are downloaded: ``{name, songs}``; each is
  written into the playlist when its download ends)
* ``PUT  /api/library/playlists/order`` (put a playlist's songs in a
  new order: ``{name, files}``, every song in its new place - an
  imported one's order is kept through its syncs)
* ``POST /api/library/playlists/rename`` (rename a manual playlist)
* ``PUT  /api/library/playlists/visibility`` (share a playlist you own:
  private, with named users - some of them editors of a Library
  playlist - or public),
  ``POST /api/library/playlists/copy`` (save a copy of a playlist you can
  open) and ``POST /api/library/playlists/detach`` (turn an imported
  playlist into an editable one)
* ``GET  /api/library/playlists/details`` (what the playlist page
  filters by: ``{name, providers: {file: provider}, navidrome: {enabled,
  unmatched}}`` - see ``downtify/file_providers.py``)
* ``GET|POST /api/library/playlists/hidden`` (songs hidden from an
  imported playlist - ``POST`` body ``{name, hide, show}``: library
  paths to hide, hidden song keys to show again; a hidden song stays
  out of the playlist when its watch or link brings it back - see
  ``downtify/playlist_hidden.py``)
* ``POST /api/library/reconcile`` (fix stored library paths after files
  moved on disk, then refresh M3U/Navidrome playlists)
* ``POST /api/library/external/sync`` (start a background scan of
  extra folders) and ``GET /api/library/external/sync`` (running or
  last-finished status)
* ``POST /api/library/external/unmap`` (drop one extra folder from
  the library without deleting the audio files)
* ``GET  /api/library/metadata`` (a track's tags plus suggestions from
  Apple Music, Deezer and YouTube Music - ``?file=&query=``) and
  ``POST /api/library/metadata`` (body ``{file, name, artists, ...}``:
  rewrite its tags in place, admins only - see
  ``downtify/track_metadata.py``)
* ``GET  /api/library/replace/candidates`` (versions of a library track
  to pick from: YouTube Music and YouTube results, or a pasted link) and
  ``POST /api/library/replace`` (body ``{file, video_id}``: replace the
  track's audio with that video in place, as a queue job - see
  ``downtify/audio_replace.py``)
* ``POST /api/library/compilation`` (body ``{files, compilation}``: mark
  or unmark an album as a various-artists compilation - rewrites its
  album-artist tag and compilation flag in place and remembers it for
  later downloads; see ``downtify/compilation.py``)
* ``GET  /api/library/upgrade`` and ``GET /api/library/upgrade/jobs``
  (an upgrade run's state, queue counts and per-track rows)
* ``POST /api/library/upgrade/scan`` (look for tracks with low-resolution
  artwork, no lyrics or incomplete tags; writes nothing),
  ``POST /api/library/upgrade/start`` (body ``{categories}``) and
  ``POST /api/library/upgrade/{pause,resume,cancel}``
* ``GET  /api/library/loudness`` (``?file=``: a visible track's playback
  loudness profile ``{state, gain_db, ...}``; ``unanalysed`` with a
  zero gain when it has no valid measurement - see
  ``downtify/loudness.py``), ``GET /api/library/loudness/status`` and
  ``POST /api/library/loudness/{start,pause,resume}`` (admin: the
  analysis queue's counts; ``start`` queues the whole library again,
  reusing the measurements of unchanged files)
* ``GET  /api/library/usage`` (admin; ``?days=``, 1-365, default 30:
  ``{library, period, growth, downloads, duplicates, working, disk}`` -
  the library's size by provider, location and format, what came in
  during the period, its size per day or week (daily snapshots,
  estimated from file dates before the first one), how downloads ended,
  songs stored more than once and slskd's working copies, apart from
  the library - see ``downtify/library_usage.py``) and ``GET
  /api/library/usage/scan`` (``?refresh=``: what the downloads, slskd
  and lyrics folders hold by kind, leftover temporary files and orphaned
  sidecars - a walk of the folders, kept for a few minutes; see
  ``downtify/storage_scan.py``)
* ``GET  /api/playlists/batches`` and
  ``GET|DELETE /api/playlists/batches/{spotify_playlist_id}`` (Spotify
  playlist downloads and their completeness against Spotify)
* ``GET  /api/playlists/incomplete`` and
  ``POST /api/playlists/incomplete/download-missing`` (queue only the
  tracks a downloaded playlist is still missing)
* ``GET  /api/settings``
* ``POST /api/settings/update``
* ``GET  /api/fs/dirs`` (admin: directory-name suggestions for path
  fields, ``?path=``)
* ``POST /api/slskd/test`` and ``POST /api/navidrome/test`` (try the
  connection with the settings as they are in the form, saved or not)
* ``POST /api/proxy/test`` (admin: test outbound proxy reachability)
* ``GET  /api/cookies`` (current YouTube cookie configuration)
* ``POST /api/cookies`` (upload a Netscape cookies.txt as the raw request
  body - no multipart, so no ``python-multipart`` dependency)
* ``DELETE /api/cookies`` (remove the uploaded cookies.txt)
* ``GET|POST /api/monitor/playlists`` and
  ``PATCH|DELETE /api/monitor/playlists/{playlist_id}`` (playlist and
  artist watches; ``PATCH`` takes ``interval_minutes``, ``enabled`` and
  ``url`` - a link to a different playlist/artist of the same kind
  retargets the watch; artist watches also take ``release_types``
  (``album``/``single``/``ep``) and ``new_only``, on ``POST`` too),
  ``POST /api/monitor/playlists/{id}/check``
* ``GET  /api/monitor/stats`` (``?days=``, 1-365, default 30: per watch
  ``{id, storage, status, providers, period, rate, series, trend,
  last_added_at}`` plus ``totals`` - a file several watches hold is
  counted once; activity leaves out what a watch found already in the
  library and its first check's backfill), ``GET
  /api/monitor/provenance`` (``?file=``: ``{origin, watches, others}`` -
  the watch that first downloaded the file, every watch holding it; a
  user only sees their own watches by name) and ``GET
  /api/monitor/playlists/{id}/tracks`` (``{watch, tracks, missing,
  failures}``: the watch's songs as ``GET /tracks`` rows, newest first,
  each with ``watch: {added_at, outcome, initial, provider,
  shared_with}``) - see ``downtify/watch_stats.py`` and
  ``downtify/watch_history.py``
* ``GET  /api/monitor/artist-suggestions`` (``?listening_offset=``,
  ``?library_offset=``, ``?limit=`` 1-100, default 20: ``{listening,
  library, half_life_days}``, each list ``{items, total, next_offset}`` -
  artists to follow from the user's own listens and the library they
  can see, minus the ones they watch; no search) and ``GET
  /api/monitor/artist-suggestions/resolve`` (``?name=``: ``{candidates,
  url}`` - the YouTube Music artist to follow, ``url`` only when exactly
  one is named so) - see ``downtify/artist_suggestions.py``
* ``GET|PUT /api/likes`` and ``POST /api/likes/clear`` (the heart on a
  library track; while any song is liked they are also written out as a
  playlist)
* ``POST /api/discover`` (suggested artists the library doesn't have
  yet - body ``{library: [{name, tracks, liked}]}``, the Library page's
  own artist grouping; response ``{artists: [{name, deezer_id,
  picture_url, fans, score, because}], seeds, partial}`` - see
  ``downtify.discover``), ``POST /api/discover/collections`` (albums and
  playlists built on those artists - same body plus ``albums: [{artist,
  title}]`` and ``playlist_ids``; response ``{albums, more_albums,
  playlists, artist_urls, partial}``; Spotify only), ``POST
  /api/discover/collections/deezer`` (the same shelves from Deezer
  alone, the web page's first answer - body adds ``playlist_names``;
  every item carries ``source: 'deezer'`` and Deezer ids, albums also
  ``key``, playlists are Deezer's "100% <artist>"), ``POST
  /api/discover/collections/spotify`` (what Spotify adds, the second
  answer - body adds ``shown``, the album ``key``\\ s already on the page;
  albums matched to Deezer by name come with ``source: 'deezer'``, the
  rest ``'spotify'``; playlists are only Spotify's "This Is <artist>"),
  ``POST|DELETE
  /api/discover/listens`` (count
  one listen to an artist - body ``{artist}`` - or forget them all) and
  ``GET|POST|DELETE /api/discover/blocked`` (artists never to suggest -
  ``POST`` body ``{name}``, ``DELETE`` takes ``?name=``)
 * ``GET  /api/preview`` (a song's 30 s preview clip from Deezer, for a
   song with no ``preview_url`` of its own - ``?artist=&title=&duration=``,
   response ``{preview_url}``, ``""`` when Deezer has no matching song)
 * ``GET  /api/buy`` (where to buy a song, album or artist's music to
   support them - ``?artist=&title=&album=&country=``, response ``{kind,
   query, links}``: the iTunes Store item with its price when found,
   Bandcamp and Qobuz searches, the artist's website from their saved
   profile - see ``downtify.buy_links``)
 * ``GET  /api/similar/tracks`` (tracks similar to ``?artist=&track=``
   via YouTube Music's own radio mix for the track - downloadable song
   rows plus ``match`` - see
   ``downtify.providers.youtube_similar_tracks``)
 * ``GET  /api/stream`` (a track's full audio as a fresh,
   short-lived direct URL - ``?video_id=`` - for third-party clients;
   the web player behind a song that isn't downloaded yet uses
   ``/api/stream/live`` below instead - see ``downtify.stream``)
 * ``GET  /api/stream/file`` (that same audio downloaded once into
   ``/data/stream_cache`` and served from this server with seeking
   support - ``?video_id=``; playback never depends on the browser
   reaching YouTube itself, but starts only once the download is done)
 * ``POST /api/stream/prefetch`` (body ``{video_id}``: start caching
   that audio in the background and answer ``{queued: true}`` at once)
 * ``GET  /api/stream/live`` (that same audio relayed from YouTube as
   it arrives, nothing stored - ``?video_id=&duration=``; honours
   ``Range`` for seeking; what the web player streams, so a song starts
   within a second or two - see ``downtify.live_stream``)
 * ``POST /api/stream/live/prefetch`` (body ``{video_id}``: resolve
   that video's audio URL in the background and answer ``{queued:
   true}`` at once - how the player warms the next track up)
* ``GET|POST /api/song-links`` and ``DELETE /api/song-links/{token}``
  (public links to one song), and the pages they open without signing
  in, ``GET /s/{token}`` (plus ``/info``, ``/audio``, ``/cover``) - see
  ``downtify/song_link_routes.py``
* ``GET  /api/server/info`` (public: server id, name, version,
  ``api_version``, ``require_sign_in`` (always true), capabilities) and
  ``PATCH /api/server`` (``{name}``) - see ``downtify/auth_routes.py``
* ``GET  /api/auth/status``, ``POST /api/auth/login`` (``{username,
  password}``), ``POST /api/auth/logout`` (signing in), ``GET|PATCH|DELETE
  /api/auth/devices[/{id}]`` (your paired apps; everyone's for an admin),
  ``POST /api/auth/revoke-all`` (everyone signed out), ``POST
  /api/auth/pairing``, ``GET|DELETE /api/auth/pairing/{id}``, ``POST
  /api/auth/pair`` (pairing an app), ``POST /api/auth/token`` (an app
  signs in: ``{username, password, device_name, platform}``) and ``POST
  /api/auth/ws-ticket`` - see ``downtify/auth.py`` for who may call what
* ``GET|PATCH /api/me``, ``PUT /api/me/password``, ``GET|PUT
  /api/me/preferences``, ``POST /api/me/sign-out-everywhere`` (your
  account), ``GET|POST /api/users``, ``PATCH|DELETE /api/users/{id}``
  (admins), ``GET /api/activity``, ``GET /api/activity/now`` (admins) and
  ``POST /api/activity/playback`` (players report what they play) - see
  ``downtify/account_routes.py``
* ``/api/v1/...``: the apps' API, by track id - ``GET /api/v1/library``
  (``?since=`` change feed), ``GET /api/v1/tracks/{id}`` (and
  ``/stream``, ``/cover``, ``/lyrics``), ``GET /api/v1/playlists``,
  ``POST|DELETE /api/v1/playlists/follow``, ``POST /api/v1/playlists/seen``,
  ``GET|POST /api/v1/playlists/hidden``,
  ``GET /api/v1/usernames``, ``GET|PUT /api/v1/likes`` and
  ``POST /api/v1/sign`` - see
  ``downtify/mobile_routes.py`` and ``docs/mobile-client-contract.md``
* ``WS   /api/ws`` (also ``library_changed``, ``playlists_changed``,
  ``device_paired`` messages; a device token, session cookie or ``?ticket=`` is needed)
* ``GET  /api/check_update``
"""

from __future__ import annotations

import sys
import types
from typing import Any

from . import (
    api_core,
    api_pipeline,
    artist_routes,
    discover_routes,
    download_routes,
    library_routes,
    monitor_routes,
    playlist_routes,
    stream_routes,
    system_routes,
)

#: Every module whose names ``api.<name>`` reaches, shared ones first.
_PARTS: tuple[types.ModuleType, ...] = (
    api_core,
    api_pipeline,
    system_routes,
    discover_routes,
    artist_routes,
    download_routes,
    library_routes,
    playlist_routes,
    stream_routes,
    monitor_routes,
)

_MISSING = object()


def _lookup(name: str) -> Any:
    for part in _PARTS:
        value = vars(part).get(name, _MISSING)
        if value is not _MISSING:
            return value
    return _MISSING


def __getattr__(name: str) -> Any:
    value = _lookup(name)
    if value is _MISSING:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    return value


def __dir__() -> list[str]:
    names = set(globals())
    for part in _PARTS:
        names.update(vars(part))
    return sorted(names)


class _Facade(types.ModuleType):
    """Make ``api.<name> = value`` rebind the name where it is used.

    Tests (and a few modules) patch ``api.state``, ``api._run_download``
    and friends with ``monkeypatch.setattr(api, ...)`` or
    ``unittest.mock.patch('downtify.api....')``. The code that reads
    those names now lives in the route modules, so setting one here
    rebinds it in every part that holds the same object - the module
    that defines it and each one that imported it. Deleting it (how
    ``mock.patch`` and pytest's ``monkeypatch`` undo a patch of a name
    this module doesn't hold itself) puts back what it held before the
    latest patch, so nested patches unwind in order.
    """

    def __setattr__(self, name: str, value: Any) -> None:
        current = _lookup(name)
        if current is _MISSING or name in vars(self):
            super().__setattr__(name, value)
            return
        _PATCHED.setdefault(name, []).append(current)
        _rebind(name, current, value)

    def __delattr__(self, name: str) -> None:
        if name in vars(self):
            super().__delattr__(name)
            return
        if _lookup(name) is _MISSING:
            raise AttributeError(name)
        previous = _PATCHED.get(name)
        if previous:
            _rebind(name, _lookup(name), previous.pop())


#: What each patched name held before each of its patches, oldest first.
_PATCHED: dict[str, list[Any]] = {}


def _rebind(name: str, current: Any, value: Any) -> None:
    for part in _PARTS:
        if vars(part).get(name, _MISSING) is current:
            setattr(part, name, value)


sys.modules[__name__].__class__ = _Facade
