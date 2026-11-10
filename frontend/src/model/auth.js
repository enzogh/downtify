// Who is signed in to this browser. Until someone is, the app shows the
// sign-in page instead of itself (see AppShell); any request refused
// with a 401 gets it there too.
import { computed, ref } from 'vue'

import API from '/src/model/api'
import { ROLE_ADMIN, needsSignIn } from '/src/lib/auth'

const status = ref(null)
const mustSignIn = ref(false)
const loaded = ref(false)

// An admin can look at the app as a plain user ("User view"): every
// admin-only control, page and badge goes away until they switch back.
// Only what this browser shows changes - the server still answers them
// as an admin. Remembered per browser.
const USER_VIEW_KEY = 'downtify-user-view'

function store() {
  try {
    return globalThis.localStorage || null
  } catch {
    return null
  }
}

function readUserView() {
  try {
    return store()?.getItem(USER_VIEW_KEY) === '1'
  } catch {
    return false
  }
}

const user = computed(() => status.value?.user || null)
const realIsAdmin = computed(() => user.value?.role === ROLE_ADMIN)
const userView = ref(readUserView())
const isAdmin = computed(() => realIsAdmin.value && !userView.value)
/** The role the interface is drawn for (`user` while in User view). */
const viewRole = computed(() => {
  if (isAdmin.value) return ROLE_ADMIN
  return realIsAdmin.value ? 'user' : user.value?.role || ''
})

/** Switch between the admin's own view and User view. */
function setUserView(on) {
  userView.value = Boolean(on)
  try {
    if (userView.value) store()?.setItem(USER_VIEW_KEY, '1')
    else store()?.removeItem(USER_VIEW_KEY)
  } catch {
    // Private mode: the switch lasts until the page closes.
  }
}

function toggleUserView() {
  setUserView(!userView.value)
}
// DOWNTIFY_DISABLE_AUTH: nobody signs in, so there is nothing to sign out
// of and no accounts to manage.
const authDisabled = computed(() => Boolean(status.value?.auth_disabled))

async function load() {
  try {
    const res = await API.getAuthStatus()
    status.value = res.data
    mustSignIn.value = needsSignIn(res.data)
  } catch {
    // An unreachable server is shown elsewhere; don't block the app on it.
  } finally {
    loaded.value = true
  }
  return status.value
}

API.onUnauthorized(() => {
  mustSignIn.value = true
})

/** Sign in; resolves `true`, or the error's message. */
async function signIn(username, password) {
  try {
    await API.login(username, password)
  } catch (err) {
    if (err?.response?.status === 429) return 'tooMany'
    return err?.response?.data?.detail || err?.message || 'failed'
  }
  // Every model and the WebSocket start over, now signed in.
  window.location.reload()
  return true
}

async function signOut() {
  try {
    await API.logout()
  } finally {
    window.location.reload()
  }
}

/** Replace what's known about the signed-in user (after a change). */
function setUser(next) {
  if (status.value && next) status.value = { ...status.value, user: next }
}

export function useAuth() {
  return {
    status,
    loaded,
    mustSignIn,
    user,
    isAdmin,
    realIsAdmin,
    userView,
    viewRole,
    setUserView,
    toggleUserView,
    authDisabled,
    load,
    signIn,
    signOut,
    setUser,
  }
}

load()
