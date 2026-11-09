// The signed-in user's own playlists. An admin may open and change
// everyone's (they are all `mine` in the library), but the sidebar and
// the drop panel list only theirs - watched (imported) ones included.
import { computed } from 'vue'
import { isOwnPlaylist } from '/src/lib/library'
import { useAuth } from '/src/model/auth'
import { useLibrary } from '/src/model/library'

export function useMyPlaylists() {
  const library = useLibrary()
  const auth = useAuth()
  return computed(() =>
    library.ownPlaylists.value.filter((playlist) =>
      isOwnPlaylist(playlist, auth.user.value?.id || 0)
    )
  )
}
