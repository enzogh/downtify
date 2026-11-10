import { describe, expect, it } from 'vitest'
import {
  otherDevices,
  otherPlayers,
  queueToSend,
  pickRemote,
  remoteKey,
  remotePosition,
} from '../lib/remotePlayback'

const row = (player, values = {}) => ({
  player,
  client: 'Pixel 8',
  track: { file: `${player}.mp3`, duration: 200 },
  paused: false,
  position: 10,
  seconds_ago: 5,
  ...values,
})

describe('remote playback', () => {
  it('leaves this page and songless players out', () => {
    const rows = [row('me'), row('phone'), row('empty', { track: {} })]
    expect(otherPlayers(rows, 'me').map((r) => r.player)).toEqual(['phone'])
    expect(otherPlayers(null, 'me')).toEqual([])
  })

  it('picks a playing player first, then the freshest', () => {
    const rows = [
      row('paused', { paused: true, seconds_ago: 1 }),
      row('old', { seconds_ago: 50 }),
      row('fresh', { seconds_ago: 2 }),
    ]
    expect(pickRemote(rows, 'me').player).toBe('fresh')
    expect(pickRemote([row('me')], 'me')).toBeNull()
  })

  it('moves a playing song on, never past its end', () => {
    expect(remotePosition(row('p'), 3)).toBe(18)
    expect(remotePosition(row('p', { paused: true }), 3)).toBe(10)
    expect(remotePosition(row('p', { position: 198 }), 30)).toBe(200)
    expect(remotePosition(null)).toBe(0)
  })

  it('keys one song on one player', () => {
    expect(remoteKey(row('phone'))).toBe('phone|phone.mp3')
    expect(remoteKey(null)).toBe('')
  })
})

describe('devices', () => {
  it('lists playing, then paused, then idle devices, never this one', () => {
    const rows = [
      row('idle', { track: null }),
      row('me'),
      row('paused', { paused: true }),
      row('playing'),
    ]
    expect(otherDevices(rows, 'me').map((r) => r.player)).toEqual([
      'playing',
      'paused',
      'idle',
    ])
  })

  it('sends library songs only, keeping the current one in place', () => {
    const list = [
      { file: 'a.mp3' },
      { url: 'stream' },
      { file: 'b.mp3' },
      { file: 'c.mp3' },
    ]
    expect(queueToSend(list, 2, 31.26, false)).toEqual({
      files: ['a.mp3', 'b.mp3', 'c.mp3'],
      index: 1,
      position: 31.3,
      playing: false,
    })
    expect(queueToSend(list, 1)).toBeNull()
    expect(queueToSend([], 0)).toBeNull()
  })

  it('keeps a long queue around the current song', () => {
    const list = Array.from({ length: 800 }, (_, i) => ({ file: `${i}` }))
    const sent = queueToSend(list, 700)
    expect(sent.files).toHaveLength(500)
    expect(sent.files[sent.index]).toBe('700')
  })
})
