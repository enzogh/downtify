// What the "Share as image" dialog is open for (one at a time, for the
// whole app - see ShareCardDialog in AppShell).
import { ref } from 'vue'

// { song: { title, artist, album, cover, hasCover }, link: () => Promise
// of the public URL ('' when there is none) }
const target = ref(null)

function open(song, link = () => Promise.resolve('')) {
  if (!song?.title) return
  target.value = { song, link }
}

function close() {
  target.value = null
}

export function useShareCard() {
  return { target, open, close }
}
