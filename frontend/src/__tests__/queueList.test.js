import { describe, expect, it } from 'vitest'
import {
  QUEUE_HEADER_HEIGHT,
  QUEUE_ROW_DIVIDER,
  queueRowEstimate,
  queueRows,
} from '../lib/queueList.js'

describe('queueRowEstimate', () => {
  it('sizes compact queued/done rows as the cover tile plus the line', () => {
    expect(queueRowEstimate('queued')).toBe(60 + QUEUE_ROW_DIVIDER)
    expect(queueRowEstimate('done')).toBe(60 + QUEUE_ROW_DIVIDER)
  })

  it('gives active and failed rows extra room for progress / forms', () => {
    expect(queueRowEstimate('active')).toBeGreaterThan(
      queueRowEstimate('queued')
    )
    expect(queueRowEstimate('failed')).toBeGreaterThan(
      queueRowEstimate('active')
    )
  })

  it('sizes section headings', () => {
    expect(queueRowEstimate('header')).toBe(QUEUE_HEADER_HEIGHT)
  })
})

describe('queueRows', () => {
  const item = (key, state) => ({ key, state })
  const items = [
    item('a', 'done'),
    item('b', 'queued'),
    item('c', 'active'),
    item('d', 'done'),
  ]

  it('keeps a single tab as it is', () => {
    expect(queueRows(items, false).map((row) => row.key)).toEqual([
      'a',
      'b',
      'c',
      'd',
    ])
  })

  it('opens each non-empty section with a counted heading', () => {
    const rows = queueRows(items, true)
    expect(rows.map((row) => row.key)).toEqual([
      'header:active',
      'c',
      'header:queued',
      'b',
      'header:done',
      'a',
      'd',
    ])
    expect(rows.find((row) => row.key === 'header:done').count).toBe(2)
    expect(rows.some((row) => row.header === 'failed')).toBe(false)
  })
})
