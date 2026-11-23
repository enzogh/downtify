import { describe, expect, it, vi } from 'vitest'

// No browser here: just what src/config.js and the router read.
vi.stubGlobal('window', {
  location: { protocol: 'http:', hostname: 'localhost', port: '' },
})
vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, createWebHistory: () => actual.createMemoryHistory() }
})

const { jamOverPage } = await import('../router/index.js')
const { useJamSheet } = await import('../model/jamSheet.js')

const queue = { name: 'Queue', matched: [{}] }
const jam = (code) => ({ name: 'Jam', query: code ? { code } : {} })

describe('the Jam entry', () => {
  it('opens the sheet over the page instead of leaving it', () => {
    const sheet = useJamSheet()
    sheet.closeJamSheet()
    // Leaving for /jam and coming back remounted the page (it looked
    // like a reload): the navigation is cancelled, the sheet opens.
    expect(jamOverPage(jam('abc123'), queue)).toBe(false)
    expect(sheet.open.value).toBe(true)
    expect(sheet.pendingCode.value).not.toBe('')
  })

  it('lets an invitation link opened directly land on its page', () => {
    expect(jamOverPage(jam('abc123'), { matched: [] })).toBe(true)
  })

  it('leaves every other navigation alone', () => {
    expect(jamOverPage({ name: 'Home', query: {} }, queue)).toBe(true)
  })
})
