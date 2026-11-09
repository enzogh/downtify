import { describe, expect, it } from 'vitest'
import { moveItem } from '../lib/library'
import { reorderTarget } from '../lib/playlistOrder'

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
