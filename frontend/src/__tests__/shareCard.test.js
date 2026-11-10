import { describe, expect, it } from 'vitest'
import {
  cardFileName,
  drawShareCard,
  ellipsize,
  wrapLines,
} from '../lib/shareCard'

// Every character is 10 wide.
const measure = (text) => text.length * 10

describe('share card text', () => {
  it('keeps a short title on one line', () => {
    expect(wrapLines('Hello there', measure, 200, 2)).toEqual(['Hello there'])
  })

  it('wraps a long title over the lines it may use', () => {
    expect(wrapLines('one two three four', measure, 90, 2)).toEqual([
      'one two',
      'three…',
    ])
  })

  it('cuts a single word too long for the line', () => {
    const [line] = wrapLines('Supercalifragilistic', measure, 80, 1)
    expect(line.endsWith('…')).toBe(true)
    expect(measure(line)).toBeLessThanOrEqual(80)
  })

  it('shortens text to fit, ending in an ellipsis', () => {
    expect(ellipsize('abcdefghij', measure, 50)).toBe('abcd…')
  })

  it('names the picture after the song', () => {
    expect(cardFileName('Café del Mar', 'Énergie 52')).toBe(
      'castify-energie-52-cafe-del-mar.png'
    )
    expect(cardFileName('', '')).toBe('castify.png')
  })
})

function recordingContext() {
  const calls = []
  const gradient = { addColorStop: () => {} }
  const ctx = new Proxy(
    { measureText: (text) => ({ width: measure(text) }) },
    {
      get(target, name) {
        if (name in target) return target[name]
        if (name === 'createLinearGradient') return () => gradient
        return (...args) => calls.push([name, ...args])
      },
      set(target, name, value) {
        calls.push([`set:${String(name)}`, value])
        return true
      },
    }
  )
  return { ctx, calls }
}

describe('drawShareCard', () => {
  const song = { title: 'Song', artist: 'Artist', album: 'Album' }
  const labels = { listen: 'Scan to listen', brand: 'Castify' }

  it('writes the title, artist, album and brand', () => {
    const { ctx, calls } = recordingContext()
    drawShareCard(ctx, { song, image: null, palette: null, url: '', labels })
    const texts = calls.filter(([n]) => n === 'fillText').map(([, t]) => t)
    expect(texts).toEqual(['Song', 'Artist', 'Album', 'Castify'])
  })

  it('adds a QR code and its label when there is a link', () => {
    const { ctx, calls } = recordingContext()
    drawShareCard(ctx, {
      song,
      image: null,
      palette: null,
      url: 'https://music.example/s/abcdefgh',
      labels,
    })
    const texts = calls.filter(([n]) => n === 'fillText').map(([, t]) => t)
    expect(texts).toContain('Scan to listen')
    // Plenty of dark modules drawn for the code.
    expect(calls.filter(([n]) => n === 'fillRect').length).toBeGreaterThan(100)
  })
})
