import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  canControl,
  clockOffset,
  codeFromInput,
  expectedPosition,
  jamTrackPayload,
  jamTracks,
  jammable,
  needsResync,
  shuffled,
} from '../lib/jam.js'

const snapshot = (over = {}) => ({
  id: 'j1',
  code: 'ABC234',
  host_id: 1,
  guests_can_control: true,
  queue: [
    {
      id: 'r1',
      file: 'Artist - One.mp3',
      title: 'One',
      artist: 'Artist',
      album: 'Album',
      duration: 100,
      added_by: 2,
      added_by_name: 'guest',
    },
  ],
  index: 0,
  position: 10,
  playing: true,
  updated: 1000,
  now: 1000,
  ...over,
})

describe('the shared clock', () => {
  it('reads the server clock from a frame', () => {
    expect(clockOffset(snapshot(), 990)).toBe(10)
    expect(clockOffset({}, 990)).toBe(0)
  })

  it('moves a playing song on with the time since the frame', () => {
    // Local clock 10 s behind the server, 5 s after the frame.
    expect(expectedPosition(snapshot(), 10, 995)).toBe(15)
  })

  it('keeps a paused song where it was', () => {
    expect(expectedPosition(snapshot({ playing: false }), 10, 2000)).toBe(10)
  })

  it('never runs past the end of the song', () => {
    expect(expectedPosition(snapshot(), 0, 5000)).toBe(100)
  })

  it('resyncs only past the allowed drift', () => {
    expect(needsResync(10, 11.5)).toBe(false)
    expect(needsResync(10, 12.5)).toBe(true)
    expect(needsResync(30, 10)).toBe(true)
  })
})

describe('the shared queue', () => {
  it('turns rows into player tracks that know their Jam row', () => {
    const [track] = jamTracks(snapshot())
    expect(track.file).toBe('Artist - One.mp3')
    expect(track.title).toBe('One')
    expect(track.jamId).toBe('r1')
    expect(track.addedByName).toBe('guest')
    expect(track.url).toContain('One.mp3')
  })

  it('sends only library songs, as the API takes them', () => {
    const songs = jammable([
      { file: 'a.mp3', title: 'A', duration: 3, extra: 1 },
      { file: '', stream: true, title: 'B' },
    ])
    expect(songs).toHaveLength(1)
    expect(jamTrackPayload(songs[0])).toEqual({
      file: 'a.mp3',
      title: 'A',
      artist: '',
      album: '',
      duration: 3,
    })
  })

  it('lets the host, and guests when allowed, control playback', () => {
    expect(canControl(snapshot(), 1)).toBe(true)
    expect(canControl(snapshot(), 2)).toBe(true)
    expect(canControl(snapshot({ guests_can_control: false }), 2)).toBe(false)
    expect(canControl(null, 1)).toBe(false)
  })

  it('reads a code typed loosely or inside a join link', () => {
    expect(codeFromInput(' abc-234 ')).toBe('ABC234')
    expect(codeFromInput('https://h/jam?code=xyz789&x=1')).toBe('XYZ789')
    // No O, I, 0 or 1 in codes.
    expect(codeFromInput('O1I0AB')).toBe('AB')
  })

  it('shuffles a copy, keeping every song', () => {
    const list = [1, 2, 3, 4]
    const out = shuffled(list, () => 0)
    expect(out.slice().sort()).toEqual(list)
    expect(list).toEqual([1, 2, 3, 4])
  })
})

describe('the player while a Jam controls it', () => {
  let player
  let hook

  beforeEach(async () => {
    vi.resetModules()
    globalThis.window = {
      innerWidth: 1280,
      addEventListener: () => {},
      location: { protocol: 'http:', hostname: 'localhost', port: '' },
    }
    globalThis.localStorage = {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    }
    globalThis.Audio = function () {
      return {
        src: '',
        currentTime: 0,
        volume: 1,
        muted: false,
        buffered: { length: 0, end: () => 0 },
        play: vi.fn(() => Promise.resolve()),
        pause: vi.fn(),
        removeAttribute: vi.fn(),
        addEventListener: vi.fn(),
        load: vi.fn(),
      }
    }
    const mod = await import('../model/player.js')
    player = mod.usePlayer()
    hook = vi.fn(() => true)
    player.setTransportHook(hook)
  })

  it('sends the listener’s controls to the Jam', () => {
    player.play()
    player.pause()
    player.next()
    player.prev()
    player.enqueue([{ file: 'a.mp3', url: '/a', title: 'A' }])
    player.setShuffle(true)

    expect(hook.mock.calls.map(([action]) => action)).toEqual([
      'play',
      'pause',
      'next',
      'prev',
      'insert',
      'shuffle',
    ])
    expect(player.shuffle.value).toBe(false)
    expect(player.remoteControlled.value).toBe(true)
  })

  it('applies the shared state past the hook', () => {
    const tracks = [
      { file: 'a.mp3', url: '/a', title: 'A' },
      { file: 'b.mp3', url: '/b', title: 'B' },
    ]
    player.withoutHook(() => player.adoptQueue(tracks, 1))
    player.cueAt(1, 30, false)

    expect(hook).not.toHaveBeenCalled()
    expect(player.currentTrack.value.title).toBe('B')
    expect(player.currentTime.value).toBe(30)
  })

  it('keeps the playing song when the queue around it changes', () => {
    const a = { file: 'a.mp3', url: '/a', title: 'A' }
    const b = { file: 'b.mp3', url: '/b', title: 'B' }
    player.withoutHook(() => player.adoptQueue([a], 0))
    player.cueAt(0, 0, true)

    const changed = player.withoutHook(() => player.adoptQueue([b, a], 1))

    expect(changed).toBe(false)
    expect(player.currentTrack.value.title).toBe('A')
  })

  it('mutes this device without touching the listener’s mute', () => {
    player.setOutputMuted(true)
    expect(player.outputMuted.value).toBe(true)
    expect(player.isMuted.value).toBe(false)
  })
})
