// Tells an iPhone user once that the equalizer or volume normalization
// may stop the music with the screen locked (see lib/iosAudio.js), with a
// button that turns both off.
import { computed, watch } from 'vue'
import { useEqualizer } from '/src/model/equalizer'
import { usePlayerPrefs } from '/src/model/playerPrefs'
import { useUi } from '/src/model/ui'
import { backgroundAudioAtRisk, isIOS } from '/src/lib/iosAudio'
import { useI18n } from '/src/i18n'

const SEEN_KEY = 'downtify-ios-background-notice'
const ios = isIOS()

function seen() {
  try {
    return localStorage.getItem(SEEN_KEY) === '1'
  } catch {
    return false
  }
}

function remember() {
  try {
    localStorage.setItem(SEEN_KEY, '1')
  } catch {
    // Shown again next visit, nothing worse.
  }
}

/** Whether music may stop with the screen locked here (a reactive flag). */
export function useBackgroundAudioRisk() {
  const eq = useEqualizer()
  const { normalizeVolume } = usePlayerPrefs()
  return computed(() =>
    backgroundAudioAtRisk({
      ios,
      equalizer: eq.enabled.value,
      normalization: normalizeVolume.value,
    })
  )
}

let started = false

/** Watch for the risk and say so once, on this device. */
export function startIosAudioNotice() {
  if (started || !ios) return
  started = true
  const { t } = useI18n()
  const ui = useUi()
  const eq = useEqualizer()
  const { normalizeVolume } = usePlayerPrefs()
  const risk = useBackgroundAudioRisk()
  watch(
    risk,
    (now) => {
      if (!now || seen()) return
      remember()
      ui.toast(t('iosAudio.notice'), {
        timeout: 15000,
        action: {
          label: t('iosAudio.turnOff'),
          run: () => {
            eq.setEnabled(false)
            normalizeVolume.value = false
          },
        },
      })
    },
    { immediate: true }
  )
}
