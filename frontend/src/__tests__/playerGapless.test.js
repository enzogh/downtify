import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('/src/model/streamResolve', () => ({
  resolveTrackUrl: vi.fn(),
  warmServerCache: vi.fn(),
}))

const audios = vi.hoisted(() => ({ list: [] }))

function stubAudio() {
  const handlers = {}
  const audio = {
    src: '',
    currentTime: 0,
    duration: 0,
    volume: 1,
    playbackRate: 1,
    muted: false,
    paused: true,
    readyState: 0,
    error: null,
    buffered: { length: 0, end: () => 0 },
    play: vi.fn(() => {
      audio.paused = false
      handlers.play?.()
      return Promise.resolve()
    }),
    pause: vi.fn(() => {
      audio.paused = true
      handlers.pause?.()
    }),
    removeAttribute: vi.fn((name) => {
      if (name === 'src') audio.src = ''
    }),
    addEventListener: vi.fn((event, fn) => {
      handlers[event] = fn
    }),
    load: vi.fn(),
    fire: (event) => handlers[event]?.(),
  }
  audios.list.push(audio)
  return audio
}

const lib = (title) => ({
  file: `${title}.mp3`,
  title,
  artist: 'Artist',
  url: `/downloads/${title}.mp3`,
})

/** Play the current element up to `time` of a `length`-second song. */
function playTo(audio, time, length = 200) {
  audio.duration = length
  audio.fire('loadedmetadata')
  audio.currentTime = time
  audio.fire('timeupdate')
}

describe('gapless playback', () => {
  let player
  let store

  beforeEach(async () => {
    vi.resetModules()
    vi.useFakeTimers()
    audios.list.length = 0
    store = {}
    globalThis.window = {
      innerWidth: 1280,
      addEventListener: () => {},
      location: { protocol: 'http:', hostname: 'localhost', port: '' },
    }
    globalThis.localStorage = {
      getItem: (key) => store[key] ?? null,
      setItem: (key, value) => {
        store[key] = String(value)
      },
      removeItem: (key) => {
        delete store[key]
      },
    }
    globalThis.Audio = function () {
      return stubAudio()
    }
    player = (await import('../model/player.js')).usePlayer()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads the next song in a second element near the end', () => {
    player.playList([lib('A'), lib('B')])
    const [first] = audios.list
    playTo(first, 100)
    expect(audios.list).toHaveLength(1)
    playTo(first, 185)
    expect(audios.list).toHaveLength(2)
    expect(audios.list[1].src).toBe('/downloads/B.mp3')
    expect(audios.list[1].muted).toBe(true)
    expect(audios.list[1].play).not.toHaveBeenCalled()
  })

  it('starts the loaded song just before the current one ends', () => {
    player.playList([lib('A'), lib('B')])
    const [first] = audios.list
    playTo(first, 185)
    const second = audios.list[1]
    second.readyState = 4
    second.duration = 180
    playTo(first, 199.6)
    expect(second.play).not.toHaveBeenCalled()
    first.currentTime = 199.98
    vi.advanceTimersByTime(400)
    expect(second.play).toHaveBeenCalled()
    expect(second.muted).toBe(false)
    expect(first.pause).toHaveBeenCalled()
    expect(player.currentTrack.value.title).toBe('B')
    expect(player.duration.value).toBe(180)
    expect(player.isPlaying.value).toBe(true)
  })

  it('hands over on `ended` when the timer could not run', () => {
    player.playList([lib('A'), lib('B'), lib('C')])
    const [first] = audios.list
    playTo(first, 185)
    const second = audios.list[1]
    first.fire('ended')
    expect(second.play).toHaveBeenCalled()
    expect(player.currentTrack.value.title).toBe('B')
    // The element that finished now loads the song after.
    playTo(second, 185)
    expect(first.src).toBe('/downloads/C.mp3')
  })

  it('ignores events from the element that is only loading', () => {
    player.playList([lib('A'), lib('B')])
    const [first] = audios.list
    playTo(first, 185)
    const second = audios.list[1]
    second.fire('error')
    second.currentTime = 50
    second.fire('timeupdate')
    expect(player.playError.value).toBe('')
    expect(player.currentTime.value).toBe(185)
  })

  it('stays off while a fade is set', () => {
    player.setFadeSeconds(4)
    player.playList([lib('A'), lib('B')])
    playTo(audios.list[0], 190)
    expect(audios.list).toHaveLength(1)
  })

  it('can be turned off, and remembers it', () => {
    player.setGapless(false)
    expect(store['downtify-player-gapless']).toBe('0')
    player.playList([lib('A'), lib('B')])
    playTo(audios.list[0], 190)
    expect(audios.list).toHaveLength(1)
  })

  it('drops the loaded song when the listener picks another one', () => {
    player.playList([lib('A'), lib('B'), lib('C')])
    const [first] = audios.list
    playTo(first, 185)
    const second = audios.list[1]
    player.playAt(2)
    expect(second.src).toBe('')
    expect(first.src).toBe('/downloads/C.mp3')
  })

  it('loads the song in the playing element when the second one may not play', async () => {
    player.playList([lib('A'), lib('B')])
    const [first] = audios.list
    playTo(first, 185)
    const second = audios.list[1]
    second.play.mockImplementationOnce(() => Promise.reject(new Error('no')))
    first.fire('ended')
    await Promise.resolve()
    await Promise.resolve()
    expect(first.src).toBe('/downloads/B.mp3')
    expect(first.play).toHaveBeenCalledTimes(2)
    expect(player.currentTrack.value.title).toBe('B')
  })
})
