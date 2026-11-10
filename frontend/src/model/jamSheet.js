// The Jam lives in a sheet over whatever is playing, like Spotify's -
// not on a page of its own. Anything can open it (the player, the
// devices list, a `/jam?code=` invitation link).
import { ref } from 'vue'
import { codeFromInput } from '/src/lib/jam'

const open = ref(false)
// A code to join, from an invitation link.
const pendingCode = ref('')

function openJamSheet(code = '') {
  const clean = codeFromInput(code)
  if (clean) pendingCode.value = clean
  open.value = true
}

function closeJamSheet() {
  open.value = false
}

export function useJamSheet() {
  return { open, pendingCode, openJamSheet, closeJamSheet }
}
