// Pages only an admin has: User view leaves them for Home.
export const ADMIN_ROUTES = ['Storage', 'Trash', 'Upgrade']

/** The first letter to draw in an account's avatar. */
export function avatarLetter(name) {
  const text = String(name || '').trim()
  return text ? text[0].toUpperCase() : '?'
}
