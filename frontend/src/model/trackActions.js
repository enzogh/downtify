// Play / queue / delete actions shared by every track list and page.
import { useRouter } from 'vue-router'

import { usePlayer } from '/src/model/player'
import { useLibrary } from '/src/model/library'
import { useHistory } from '/src/model/history'
import { useUi } from '/src/model/ui'
import { useAuth } from '/src/model/auth'
import { useReplaceAudio } from '/src/model/replaceAudio'
import { useEditTags } from '/src/model/editTags'
import { useBuyLinks } from '/src/model/buyLinks'
import { useTrackOrigin } from '/src/model/trackOrigin'
import { useShareCard } from '/src/model/shareCard'
import { buyTargetForTrack } from '/src/lib/buyLinks'
import { useVisibility } from '/src/model/visibility'
import { canReplace } from '/src/lib/replaceAudio'
import { groupingArtistName } from '/src/lib/library'
import { saveName } from '/src/lib/paths'
import { useI18n } from '/src/i18n'
import API from '/src/model/api'
import { previewLines, trashError, useTrashCapability } from '/src/lib/trash'
import {
  shareSongUrl,
  songLinkUrl,
  streamSongPayload,
} from '/src/lib/songLinks'
import { videoIdFor } from '/src/model/streamResolve'
import { libraryOnly } from '/src/model/musicPolicy'

export function useTrackActions() {
  const trashCapability = useTrashCapability()
  const player = usePlayer()
  const library = useLibrary()
  const history = useHistory()
  const ui = useUi()
  const auth = useAuth()
  const replaceAudio = useReplaceAudio()
  const editTags = useEditTags()
  const buyLinks = useBuyLinks()
  const trackOrigin = useTrackOrigin()
  const shareCard = useShareCard()
  const visibility = useVisibility()
  const router = useRouter()
  const { t } = useI18n()

  /**
   * Play `tracks` from `index`. `context`: { type, title, subtitle,
   * route, cover } — remembered for "Jump back in".
   */
  function play(tracks, index = 0, context = null, { shuffled = false } = {}) {
    if (!tracks.length) return
    if (shuffled) {
      player.playList(tracks, { context, shuffled: true })
    } else {
      player.setPlaylist(tracks, { startIndex: index, context })
    }
    if (context && context.type !== 'library') history.remember(context)
  }

  function playNext(tracks) {
    player.playNext(tracks)
    ui.toast(t('toast.playingNext', { count: tracks.length }), {
      kind: 'success',
    })
  }

  function enqueue(tracks) {
    player.enqueue(tracks)
    ui.toast(t('toast.addedToQueue', { count: tracks.length }), {
      kind: 'success',
    })
  }

  function saveToDevice(track) {
    const a = document.createElement('a')
    a.href = track.url
    a.download = saveName(track.file)
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  async function downloadZip(tracks) {
    try {
      await library.downloadZip(tracks.map((track) => track.file))
      ui.toast(t('toast.zipStarted', { count: tracks.length }), {
        kind: 'success',
      })
    } catch (err) {
      ui.toast(err?.response?.data?.detail || t('toast.zipFailed'), {
        kind: 'error',
      })
    }
  }

  /** Confirm, delete for good and report; resolves the deleted files. */
  async function legacyRemove(tracks) {
    if (!tracks.length) return []
    const ok = await ui.confirm({
      title:
        tracks.length === 1
          ? t('confirm.deleteTrackTitle', { title: tracks[0].title })
          : t('confirm.deleteTracksTitle', { count: tracks.length }),
      body: t('confirm.deleteTracksBody'),
      confirmLabel: t('common.delete'),
      danger: true,
    })
    if (!ok) return []
    try {
      const { deleted, released, failed } = await library.deleteFiles(
        tracks.map((track) => track.file)
      )
      if (failed) {
        ui.toast(t('toast.deletePartial', { count: failed }), { kind: 'error' })
      } else if (deleted.length) {
        ui.toast(t('toast.deleted', { count: deleted.length }), {
          kind: 'success',
        })
      }
      // Others downloaded these too: they stay in the shared library.
      if (released.length) {
        ui.toast(t('toast.releasedShared', { count: released.length }))
      }
      return deleted
    } catch {
      ui.toast(t('toast.deleteFailed'), { kind: 'error' })
      return []
    }
  }

  /** Confirm, delete and report; resolves the files that left the
   * library. With the music trash on, they go there instead (admins
   * only), after the server has checked exactly what will move. */
  async function remove(tracks) {
    await trashCapability.refresh()
    if (!trashCapability.enabled.value) return legacyRemove(tracks)
    if (!tracks.length) return []
    if (!auth.isAdmin.value) {
      ui.toast(t('trash.errors.admin_required'), { kind: 'error' })
      return []
    }
    let preview
    try {
      ui.toast(t('trash.preparing'))
      preview = (await API.trashPreview(tracks.map((track) => track.file))).data
    } catch (error) {
      ui.toast(trashError(error, t), { kind: 'error' })
      return []
    }
    const { lines, more } = previewLines(preview.items)
    const ok = await ui.confirm({
      title: t('trash.confirmTitle', { count: preview.items.length }),
      body: [
        t('trash.confirmBody', { days: trashCapability.retentionDays.value }),
        '',
        ...lines,
        ...(more ? [t('trash.confirmMore', { count: more })] : []),
      ].join('\n'),
      confirmLabel: t('trash.move'),
      danger: true,
    })
    if (!ok) return []
    try {
      await API.trashConfirm(preview.confirmation)
      await library.load({ force: true })
      ui.toast(t('trash.pending', { count: preview.items.length }), {
        kind: 'success',
      })
      return preview.items.map((item) => item.file)
    } catch (error) {
      ui.toast(trashError(error, t), { kind: 'error' })
      return []
    }
  }

  /** Context-menu items for one track inside `list`. */
  // Shares the library copy when there is one, else the video the
  // player would stream.
  async function createLink(track) {
    const file =
      track.file ||
      library.findTrack(
        (track.artists || [])[0] || track.artist,
        track.name || track.title
      )?.file
    if (file) return API.createSongLink({ file })
    const videoId = await videoIdFor(track)
    return API.createSongLink({ song: streamSongPayload(track, videoId) })
  }

  // A library track (it has a `file`) or a song that isn't downloaded:
  // a search, chart or recommendation row, or what the player streams.
  async function shareSong(track) {
    const title = track.title || track.name || ''
    const artist =
      track.artist || (Array.isArray(track.artists) ? track.artists[0] : '')
    // Not awaited first: the copy has to start within the click.
    const pending = createLink(track).then(({ data }) => songLinkUrl(data))
    try {
      const how = await shareSongUrl(pending, {
        title,
        text: [title, artist].filter(Boolean).join(' · '),
      })
      if (how === 'copied') {
        ui.toast(t('songLink.copied'), { kind: 'success' })
      }
    } catch (err) {
      if (err?.url) {
        // No clipboard (a page served over plain HTTP): show the link.
        ui.toast(t('songLink.copyThis', { url: err.url }), { timeout: 20000 })
        return
      }
      ui.toast(
        err?.response?.status === 403
          ? t('songLink.disabled')
          : t('toast.actionFailed'),
        { kind: 'error' }
      )
    }
  }

  function shareImage(track) {
    shareCard.open(
      {
        title: track.title || track.name || '',
        artist:
          track.artist ||
          (Array.isArray(track.artists) ? track.artists[0] : ''),
        album: track.album || '',
        cover: track.cover || '',
        hasCover: track.hasCover,
      },
      // The public link when the server allows them; the card goes
      // without its QR code otherwise.
      () =>
        libraryOnly.value && !track.file
          ? Promise.resolve('')
          : createLink(track).then(({ data }) => songLinkUrl(data))
    )
  }

  function menuFor(
    track,
    { list = [track], index = 0, context = null, hide = [] } = {}
  ) {
    return [
      {
        label: t('actions.play'),
        icon: 'play',
        action: () => play(list, index, context),
      },
      {
        label: t('actions.playNext'),
        icon: 'play-next',
        action: () => playNext([track]),
      },
      {
        label: t('actions.addToQueue'),
        icon: 'queue',
        action: () => enqueue([track]),
      },
      { divider: true },
      {
        label: t('actions.goToAlbum'),
        icon: 'disc',
        hidden: !track.album || hide.includes('album'),
        action: () =>
          router.push({
            name: 'Album',
            query: { artist: track.albumArtist, title: track.album },
          }),
      },
      {
        label: t('actions.goToArtist'),
        icon: 'user',
        hidden: !groupingArtistName(track) || hide.includes('artist'),
        action: () =>
          router.push({
            name: 'Artist',
            query: { name: groupingArtistName(track) },
          }),
      },
      {
        // Where to buy it, to support the artist.
        label: t('buy.menu'),
        icon: 'tag',
        hidden: !track.artist,
        action: () => buyLinks.open(buyTargetForTrack(track)),
      },
      {
        // Which Playlist Monitor watch brought it in, and which hold it.
        label: t('origin.menu'),
        icon: 'radar',
        action: () => trackOrigin.open(track),
      },
      {
        // A public link anyone can listen to without signing in.
        label: t('songLink.menu'),
        icon: 'share',
        hidden: (!track.file && libraryOnly.value) || hide.includes('share'),
        action: () => shareSong(track),
      },
      {
        // A story-sized picture of the song, with its link as a QR code.
        label: t('shareCard.menu'),
        icon: 'image',
        hidden: hide.includes('share'),
        action: () => shareImage(track),
      },
      {
        label: t('library.saveToDevice'),
        icon: 'download',
        action: () => saveToDevice(track),
      },
      {
        label: t('tagEdit.menu'),
        icon: 'pencil',
        hidden: !auth.isAdmin.value || !canReplace(track),
        action: () => editTags.open(track),
      },
      {
        // Wrong song or version: pick the right one by hand (admins).
        label: t('replace.menu'),
        icon: 'retry',
        hidden: !auth.isAdmin.value || !canReplace(track),
        action: () => replaceAudio.open(track),
      },
      // Admins: take the song out of (or back into) what users see.
      ...visibility.trackMenu(track),
      { divider: true },
      {
        label: trashCapability.enabled.value
          ? t('trash.move')
          : t('actions.delete'),
        icon: 'trash',
        danger: true,
        hidden: trashCapability.enabled.value && !auth.isAdmin.value,
        action: () => remove([track]),
      },
    ]
  }

  return {
    play,
    playNext,
    enqueue,
    saveToDevice,
    downloadZip,
    remove,
    menuFor,
    shareSong,
    shareImage,
  }
}
