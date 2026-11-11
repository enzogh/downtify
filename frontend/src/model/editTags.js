// Which track the "Edit info" dialog is open for (one at a time, for the
// whole app - see EditTagsDialog in AppShell).
import { ref } from 'vue'

const track = ref(null)

function open(next) {
  track.value = next
}

function close() {
  track.value = null
}

export function useEditTags() {
  return { track, open, close }
}
