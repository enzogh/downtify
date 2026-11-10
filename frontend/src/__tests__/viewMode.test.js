import { beforeEach, describe, expect, it, vi } from 'vitest'

// A browser's localStorage, for the switch to be remembered in.
const storage = new Map()
globalThis.localStorage = {
  getItem: (key) => (storage.has(key) ? storage.get(key) : null),
  setItem: (key, value) => storage.set(key, String(value)),
  removeItem: (key) => storage.delete(key),
  clear: () => storage.clear(),
}
import { ADMIN_ROUTES, avatarLetter } from '../lib/viewMode.js'

const fixture = vi.hoisted(() => ({
  api: {
    getAuthStatus: vi.fn(),
    onUnauthorized: vi.fn(),
  },
}))

vi.mock('/src/model/api', () => ({ default: fixture.api }))

describe('avatar letter', () => {
  it('is the first letter, upper-cased', () => {
    expect(avatarLetter('enzo')).toBe('E')
    expect(avatarLetter('  maria ')).toBe('M')
    expect(avatarLetter('')).toBe('?')
  })

  it('names the admin-only pages', () => {
    expect(ADMIN_ROUTES).toContain('Storage')
  })
})

describe('User view', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  async function signedInAs(role) {
    fixture.api.getAuthStatus.mockResolvedValue({
      data: { signed_in: true, user: { id: 1, username: 'enzo', role } },
    })
    const { useAuth } = await import('../model/auth.js')
    const auth = useAuth()
    await auth.load()
    return auth
  }

  it('hides admin rights until switched back, and is remembered', async () => {
    const auth = await signedInAs('admin')
    expect(auth.isAdmin.value).toBe(true)
    expect(auth.viewRole.value).toBe('admin')

    auth.toggleUserView()
    expect(auth.isAdmin.value).toBe(false)
    expect(auth.realIsAdmin.value).toBe(true)
    expect(auth.viewRole.value).toBe('user')
    expect(localStorage.getItem('downtify-user-view')).toBe('1')

    vi.resetModules()
    const again = await signedInAs('admin')
    expect(again.userView.value).toBe(true)
    expect(again.isAdmin.value).toBe(false)

    again.toggleUserView()
    expect(again.isAdmin.value).toBe(true)
    expect(localStorage.getItem('downtify-user-view')).toBeNull()
  })

  it('changes nothing for a plain user', async () => {
    const auth = await signedInAs('user')
    auth.setUserView(true)
    expect(auth.isAdmin.value).toBe(false)
    expect(auth.realIsAdmin.value).toBe(false)
    expect(auth.viewRole.value).toBe('user')
  })
})
