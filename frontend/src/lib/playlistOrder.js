// Moving a song to a new place in a playlist's list by dragging it.

/**
 * The index the song dragged from `from` ends at once moved, when it is
 * dropped above (`after` false) or below the row at `over`.
 */
export function reorderTarget(from, over, after) {
  const slot = after ? over + 1 : over
  return slot > from ? slot - 1 : slot
}

/**
 * Where a row dragged from `from` by `offset` pixels lands, rows being
 * `rowHeight` tall and the list `count` long.
 */
export function dragTarget(from, offset, rowHeight, count) {
  if (!rowHeight || count < 1) return from
  const to = from + Math.round(offset / rowHeight)
  return Math.max(0, Math.min(count - 1, to))
}

/**
 * How far row `index` slides while the row from `from` hovers at `to`:
 * the rows between make room for it, a row's height up or down.
 */
export function rowShift(index, from, to, rowHeight) {
  if (from < 0 || index === from) return 0
  if (from < to && index > from && index <= to) return -rowHeight
  if (to < from && index >= to && index < from) return rowHeight
  return 0
}

/**
 * How fast (px per frame) to scroll while dragging near the edge of the
 * visible area: 0 in the middle, up to `max` at the very edge.
 */
export function edgeScroll(y, top, bottom, zone = 72, max = 18) {
  if (y < top + zone)
    return -Math.ceil(max * Math.min(1, (top + zone - y) / zone))
  if (y > bottom - zone)
    return Math.ceil(max * Math.min(1, (y - (bottom - zone)) / zone))
  return 0
}
