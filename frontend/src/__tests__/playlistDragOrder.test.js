import { describe, expect, it } from 'vitest'
import { moveItem } from '../lib/library'
import {
  dragTarget,
  edgeScroll,
  reorderTarget,
  rowShift,
} from '../lib/playlistOrder'

const list = ['a', 'b', 'c', 'd']
const drop = (from, over, after) =>
  moveItem(list, from, reorderTarget(from, over, after)).join('')

describe('reorderTarget', () => {
  it('moves a song down, above or below the row it is dropped on', () => {
    expect(drop(0, 2, false)).toBe('bacd')
    expect(drop(0, 2, true)).toBe('bcad')
    expect(drop(0, 3, true)).toBe('bcda')
  })

  it('moves a song up', () => {
    expect(drop(3, 0, false)).toBe('dabc')
    expect(drop(3, 1, true)).toBe('abdc')
  })

  it('leaves it in place when dropped on itself or next to it', () => {
    expect(reorderTarget(1, 1, false)).toBe(1)
    expect(reorderTarget(1, 1, true)).toBe(1)
    expect(reorderTarget(1, 0, true)).toBe(1)
    expect(reorderTarget(1, 2, false)).toBe(1)
  })
})

describe('dragging a row by its grip', () => {
  it('lands a row height at a time, inside the list', () => {
    expect(dragTarget(0, 56 * 3, 56, 4)).toBe(3)
    expect(dragTarget(0, 56 * 1.4, 56, 4)).toBe(1)
    expect(dragTarget(0, 56 * 1.6, 56, 4)).toBe(2)
    expect(dragTarget(3, -56 * 9, 56, 4)).toBe(0)
    expect(dragTarget(1, 56 * 9, 56, 4)).toBe(3)
  })

  it('slides the rows in between out of the way', () => {
    const shifts = (from, to) =>
      [0, 1, 2, 3].map((i) => rowShift(i, from, to, 56))
    expect(shifts(0, 3)).toEqual([0, -56, -56, -56])
    expect(shifts(3, 1)).toEqual([0, 56, 56, 0])
    expect(shifts(2, 2)).toEqual([0, 0, 0, 0])
    expect(shifts(-1, 2)).toEqual([0, 0, 0, 0])
  })

  it('scrolls faster the closer the pointer is to an edge', () => {
    expect(edgeScroll(400, 0, 800)).toBe(0)
    expect(edgeScroll(0, 0, 800)).toBe(-18)
    expect(edgeScroll(800, 0, 800)).toBe(18)
    const near = edgeScroll(780, 0, 800)
    expect(near).toBeGreaterThan(0)
    expect(near).toBeLessThan(18)
  })
})
