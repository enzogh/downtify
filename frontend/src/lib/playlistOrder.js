// Dragging a song into a new place in a playlist's list.

/**
 * The index the song dragged from `from` ends at once moved, when it is
 * dropped above (`after` false) or below the row at `over`.
 */
export function reorderTarget(from, over, after) {
  const slot = after ? over + 1 : over
  return slot > from ? slot - 1 : slot
}
