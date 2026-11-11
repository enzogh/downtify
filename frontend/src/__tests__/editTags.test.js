import { describe, expect, it } from 'vitest'
import { applySuggestion, editBody, formFrom } from '../lib/editTags'
import { coverURL } from '../lib/paths'

describe('edit info form', () => {
  it('takes what a suggestion knows and keeps the rest', () => {
    const form = formFrom({
      name: 'animals',
      artists: ['Garrix'],
      genre: 'EDM',
      explicit: true,
    })
    const next = applySuggestion(form, {
      name: 'Animals',
      artists: ['Martin Garrix'],
      album_name: 'Animals',
      year: '2013',
      track_number: 1,
      genre: '',
      explicit: false,
    })
    expect(next).toMatchObject({
      name: 'Animals',
      artists: 'Martin Garrix',
      album_name: 'Animals',
      genre: 'EDM',
      explicit: true,
    })
    expect(editBody('a.mp3', next, 'https://c').track_number).toBe(1)
  })
  it('versions a cover so a re-tagged one is fetched again', () => {
    expect(coverURL('a b.mp3', 1234)).toBe('/cover?file=a%20b.mp3&v=1234')
    expect(coverURL('a.mp3')).toBe('/cover?file=a.mp3')
  })
})
