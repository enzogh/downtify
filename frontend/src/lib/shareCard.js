// A song as a picture for stories (Instagram, WhatsApp, ...): the cover,
// title and artist on the cover's colours, with a QR code of the song's
// public link when there is one. Drawn on a canvas, 9:16 like a story.
import { encode } from 'uqr'

export const CARD_WIDTH = 1080
export const CARD_HEIGHT = 1920
const COVER = 760
const COVER_Y = 300
const RADIUS = 36
const SIDE = 110
const DISPLAY = "'Sora Variable', 'Segoe UI', system-ui, sans-serif"
const TEXT = "'DM Sans Variable', 'Segoe UI', system-ui, sans-serif"
const FALLBACK_BACKGROUND = '#1b2a22'
const FALLBACK_ACCENT = '#1ad05c'

/**
 * `text` in at most `maxLines` lines of `maxWidth`, as measured by
 * `measure(text) → width`; the last line ends in "…" when it is cut.
 */
export function wrapLines(text, measure, maxWidth, maxLines) {
  const words = String(text || '')
    .split(/\s+/)
    .filter(Boolean)
  const lines = []
  let line = ''
  let i = 0
  for (; i < words.length; i++) {
    const word = words[i]
    const next = line ? `${line} ${word}` : word
    if (measure(next) <= maxWidth) {
      line = next
      continue
    }
    if (line) {
      lines.push(line)
      if (lines.length === maxLines) break
    }
    line = word
  }
  if (lines.length < maxLines && line) {
    lines.push(line)
    i = words.length
  }
  const cut = i < words.length
  return lines.map((value, index) =>
    index === lines.length - 1 && (cut || measure(value) > maxWidth)
      ? ellipsize(value, measure, maxWidth)
      : value
  )
}

/** `text` shortened to fit `maxWidth`, ending in "…". */
export function ellipsize(text, measure, maxWidth) {
  let value = String(text)
  if (measure(`${value}…`) <= maxWidth && !/…$/.test(value)) {
    return `${value}…`
  }
  while (value.length > 1 && measure(`${value}…`) > maxWidth) {
    value = value.slice(0, -1)
  }
  return `${value.trimEnd()}…`
}

/** A file name for the picture: `castify-artist-title.png`. */
export function cardFileName(title, artist) {
  const slug = [artist, title]
    .filter(Boolean)
    .join(' ')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
  return `castify${slug ? `-${slug}` : ''}.png`
}

function roundedRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

function drawBackground(ctx, image, palette) {
  const base = palette?.background || FALLBACK_BACKGROUND
  const gradient = ctx.createLinearGradient(0, 0, 0, CARD_HEIGHT)
  gradient.addColorStop(0, palette?.secondary || base)
  gradient.addColorStop(0.45, base)
  gradient.addColorStop(1, '#0b0b0b')
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, CARD_WIDTH, CARD_HEIGHT)
  if (!image) return
  // The cover, huge and soft, behind everything.
  ctx.save()
  ctx.globalAlpha = 0.35
  if ('filter' in ctx) ctx.filter = 'blur(70px)'
  const size = CARD_HEIGHT * 0.9
  ctx.drawImage(image, (CARD_WIDTH - size) / 2, -size * 0.15, size, size)
  ctx.restore()
  const shade = ctx.createLinearGradient(0, CARD_HEIGHT * 0.35, 0, CARD_HEIGHT)
  shade.addColorStop(0, 'rgba(0,0,0,0)')
  shade.addColorStop(1, 'rgba(0,0,0,0.75)')
  ctx.fillStyle = shade
  ctx.fillRect(0, 0, CARD_WIDTH, CARD_HEIGHT)
}

function drawCover(ctx, image, palette) {
  const x = (CARD_WIDTH - COVER) / 2
  ctx.save()
  ctx.shadowColor = 'rgba(0,0,0,0.55)'
  ctx.shadowBlur = 80
  ctx.shadowOffsetY = 30
  roundedRect(ctx, x, COVER_Y, COVER, COVER, RADIUS)
  ctx.fillStyle = palette?.primary || FALLBACK_ACCENT
  ctx.fill()
  ctx.restore()
  if (!image) return
  ctx.save()
  roundedRect(ctx, x, COVER_Y, COVER, COVER, RADIUS)
  ctx.clip()
  ctx.drawImage(image, x, COVER_Y, COVER, COVER)
  ctx.restore()
}

function drawQr(ctx, url, x, y, size) {
  const { size: modules, data } = encode(url, { ecc: 'M', border: 0 })
  const pad = 26
  ctx.fillStyle = '#ffffff'
  roundedRect(ctx, x, y, size, size, 28)
  ctx.fill()
  const cell = (size - pad * 2) / modules
  ctx.fillStyle = '#111111'
  for (let row = 0; row < modules; row++) {
    for (let col = 0; col < modules; col++) {
      if (data[row][col]) {
        ctx.fillRect(
          x + pad + col * cell,
          y + pad + row * cell,
          Math.ceil(cell),
          Math.ceil(cell)
        )
      }
    }
  }
}

/**
 * Draw the card on `ctx` (a CARD_WIDTH × CARD_HEIGHT canvas).
 * `song`: { title, artist, album }; `image`: the loaded cover or null;
 * `palette`: lib/palette.js colours or null; `url`: the public link or ''.
 * `labels`: { listen, brand } in the interface's language.
 */
export function drawShareCard(ctx, { song, image, palette, url, labels }) {
  drawBackground(ctx, image, palette)
  drawCover(ctx, image, palette)
  const width = CARD_WIDTH - SIDE * 2
  ctx.textAlign = 'left'
  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = '#ffffff'
  ctx.font = `700 76px ${DISPLAY}`
  const measure = (text) => ctx.measureText(text).width
  let y = COVER_Y + COVER + 150
  for (const line of wrapLines(song.title, measure, width, 2)) {
    ctx.fillText(line, SIDE, y)
    y += 88
  }
  ctx.font = `500 46px ${TEXT}`
  ctx.fillStyle = 'rgba(255,255,255,0.78)'
  const artist = wrapLines(song.artist, measure, width, 1)[0]
  if (artist) {
    ctx.fillText(artist, SIDE, y + 4)
    y += 62
  }
  if (song.album) {
    ctx.font = `400 36px ${TEXT}`
    ctx.fillStyle = 'rgba(255,255,255,0.55)'
    ctx.fillText(wrapLines(song.album, measure, width, 1)[0], SIDE, y + 6)
  }

  const bottom = CARD_HEIGHT - 120
  if (url) {
    const qr = 220
    drawQr(ctx, url, CARD_WIDTH - SIDE - qr, bottom - qr, qr)
    ctx.fillStyle = 'rgba(255,255,255,0.85)'
    ctx.font = `600 38px ${TEXT}`
    const label = wrapLines(labels.listen, measure, width - qr - 40, 2)
    let ly = bottom - qr + 70
    for (const line of label) {
      ctx.fillText(line, SIDE, ly)
      ly += 50
    }
  }
  ctx.fillStyle = palette?.primary || FALLBACK_ACCENT
  ctx.font = `700 52px ${DISPLAY}`
  ctx.fillText(labels.brand, SIDE, bottom)
}
