// Pure helpers of the "Edit info" dialog (components/library/EditTagsDialog).

/** The form's fields from a server row (`GET /api/library/metadata`). */
export function formFrom(row) {
  return {
    name: row?.name || '',
    artists: (row?.artists || []).join(', '),
    album_name: row?.album_name || '',
    album_artist: row?.album_artist || '',
    year: row?.year || '',
    track_number: row?.track_number || '',
    genre: row?.genre || '',
    explicit: Boolean(row?.explicit),
  }
}

/**
 * `form` with what a suggestion knows: its non-empty fields replace the
 * form's, its empty ones leave them as they are (a catalog without a genre
 * doesn't erase the one you have). Explicit is only ever turned on.
 */
export function applySuggestion(form, row) {
  const next = formFrom(row)
  const out = { ...form }
  for (const key of Object.keys(next)) {
    if (key === 'explicit') out.explicit = form.explicit || next.explicit
    else if (next[key] !== '') out[key] = next[key]
  }
  return out
}

/** The POST body: the form plus the file and the picked cover. */
export function editBody(file, form, coverUrl = '') {
  const year = String(form.year || '').trim()
  return {
    file,
    name: form.name.trim(),
    artists: form.artists,
    album_name: form.album_name.trim(),
    album_artist: form.album_artist.trim(),
    year,
    release_date: '',
    track_number: Number(form.track_number) || 0,
    genre: form.genre.trim(),
    explicit: form.explicit,
    cover_url: coverUrl,
  }
}
