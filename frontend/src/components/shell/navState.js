import { computed } from 'vue'
import { useAuth } from '/src/model/auth'
import { useProgressTracker } from '/src/model/download'

/** Downloads still waiting or running — the Queue badge. */
export function usePendingCount() {
  const { downloadQueue, queueVersion } = useProgressTracker()
  const auth = useAuth()
  return computed(() => {
    queueVersion.value
    // An admin's queue holds everyone's jobs; the badge counts them
    // only in the admin view.
    return downloadQueue.value.filter(
      (item) =>
        (item.isQueued() || item.isDownloading()) &&
        (auth.isAdmin.value || item.mine)
    ).length
  })
}
