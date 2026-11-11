// Queue list layout: rows for the window virtualizer.
// Rows sit in one panel, split by a 1px line. Compact queued/done rows are
// a 40px tile + py-2.5; section headings (the "All" tab) are an eyebrow
// line with its count badge.

export const QUEUE_ROW_DIVIDER = 1
export const QUEUE_HEADER_HEIGHT = 44

// Order of the sections in the "All" tab.
export const QUEUE_SECTION_ORDER = ['active', 'failed', 'queued', 'done']

// Finished downloads shown at most, newest first: a long-running server
// keeps thousands, and nobody scrolls through them.
export const MAX_DONE_SHOWN = 100

/**
 * `items` with only the `max` most recently finished of its done ones
 * (newest first among them); the others keep their order.
 */
export function latestDone(items, max = MAX_DONE_SHOWN) {
  const done = items
    .filter((item) => item.state === 'done')
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .slice(0, max)
  return [...items.filter((item) => item.state !== 'done'), ...done]
}

/** Estimated row height including the line above it. */
export function queueRowEstimate(state) {
  if (state === 'header') return QUEUE_HEADER_HEIGHT
  if (state === 'failed') return 148
  if (state === 'active') return 100
  return 60 + QUEUE_ROW_DIVIDER
}

/**
 * The "All" tab's rows: each non-empty section opens with a heading row,
 * in QUEUE_SECTION_ORDER. Other tabs show their items as they are.
 */
export function queueRows(items, grouped) {
  const rows = items.map((item) => ({ key: item.key, item }))
  if (!grouped) return rows
  const out = []
  for (const state of QUEUE_SECTION_ORDER) {
    const section = rows.filter((row) => row.item.state === state)
    if (!section.length) continue
    out.push({ key: `header:${state}`, header: state, count: section.length })
    out.push(...section)
  }
  return out
}
