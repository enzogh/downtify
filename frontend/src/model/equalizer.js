// The player's equalizer: a Web Audio filter bank between the player's
// <audio> elements and the speakers, plus its saved settings. The player
// keeps two elements (the second one loads the next song ahead of time
// for gapless playback); both feed the same filters.
//
// The audio graph is only built once the equalizer (or volume
// normalization, which uses its output gain) is on and the user switches
// it on or presses play (a gesture, so the browser lets the AudioContext
// run). Until then
// playback is a plain <audio> element, exactly as before. Once built it
// stays for the life of the page — an element can only be routed into
// Web Audio once — and switching off just flattens every filter.
import { computed, ref, watch } from 'vue'
import {
  normalizationEnabled,
  normalizationGain,
} from '/src/model/normalization'
import {
  BAND_Q,
  BANDS,
  CUSTOM,
  GAIN_LIMIT,
  PREAMP_LIMIT,
  dbToGain,
  defaultSettings,
  headroomDb,
  matchPreset,
  parseSettings,
  presetGains,
  snapGain,
} from '/src/lib/equalizer'

const STORAGE_KEY = 'downtify-equalizer'
// Time constant for gain changes: fast enough to feel instant, slow
// enough not to click.
const RAMP = 0.03

function storage() {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

function load() {
  return parseSettings(storage()?.getItem(STORAGE_KEY))
}

const initial = load()
const enabled = ref(initial.enabled)
const preset = ref(initial.preset)
const gains = ref(initial.gains)
const preamp = ref(initial.preamp)
const supported =
  typeof window !== 'undefined' &&
  typeof (window.AudioContext || window.webkitAudioContext) === 'function'

// Headroom depends on the filters' sample rate; 48 kHz is close enough
// before the context exists.
const sampleRate = ref(48000)
const headroom = computed(() => headroomDb(gains.value, sampleRate.value))

let elements = []
let context = null
let filters = []
let output = null
let failed = false
const graphState = ref('none') // 'none' | 'suspended' | 'running' | 'error'

function save() {
  try {
    storage()?.setItem(
      STORAGE_KEY,
      JSON.stringify({
        enabled: enabled.value,
        preset: preset.value,
        gains: gains.value,
        preamp: preamp.value,
      })
    )
  } catch {
    // Not persisted; still applied for this visit.
  }
}

function set(param, value) {
  param.setTargetAtTime(value, context.currentTime, RAMP)
}

function apply(immediate = false) {
  if (!context) return
  const on = enabled.value
  filters.forEach((filter, i) => set(filter.gain, on ? gains.value[i] : 0))
  const normalDb = normalizationEnabled.value ? normalizationGain.value : 0
  const target = dbToGain((on ? preamp.value + headroom.value : 0) + normalDb)
  if (immediate && typeof output.gain.setValueAtTime === 'function') {
    output.gain.cancelScheduledValues(context.currentTime)
    output.gain.setValueAtTime(target, context.currentTime)
  } else set(output.gain, target)
}

function build() {
  if (context || failed || !elements.length || !supported) return
  try {
    const Context = window.AudioContext || window.webkitAudioContext
    context = new Context()
    sampleRate.value = context.sampleRate
    filters = BANDS.map((band) => {
      const filter = context.createBiquadFilter()
      filter.type = band.type
      filter.frequency.value = band.frequency
      filter.Q.value = BAND_Q
      filter.gain.value = 0
      return filter
    })
    output = context.createGain()
    let node = filters[0]
    for (const filter of filters.slice(1)) {
      node.connect(filter)
      node = filter
    }
    node.connect(output)
    output.connect(context.destination)
    elements.forEach(route)
    context.addEventListener('statechange', () => {
      graphState.value = context.state
    })
    graphState.value = context.state
    apply()
  } catch (error) {
    console.error('Equalizer unavailable', error)
    graphState.value = 'error'
    failed = true
    context = null
  }
}

// An element can only be routed into Web Audio once, for good.
function route(audio) {
  context.createMediaElementSource(audio).connect(filters[0])
}

function allPaused() {
  return elements.every((audio) => audio.paused)
}

/** Called by the player for each <audio> element it creates. */
export function attachEqualizer(audio) {
  if (!audio || elements.includes(audio)) return
  elements.push(audio)
  if (!context) return
  try {
    route(audio)
  } catch (error) {
    console.error('Equalizer could not route an element', error)
  }
}

/**
 * Called from the player's play actions. That's where a saved "on"
 * equalizer gets built (a play is a user gesture, so the AudioContext may
 * start), and where a suspended context is woken — without it the routed
 * element would play in silence.
 */
export function resumeEqualizer() {
  if ((enabled.value || normalizationEnabled.value) && !context) build()
  if (context && context.state !== 'running') {
    context.resume().catch(() => {})
  }
}

function setEnabled(value) {
  enabled.value = !!value
  if (enabled.value) {
    build()
    resumeEqualizer()
  }
  apply()
  save()
}

function setGain(index, value) {
  const next = gains.value.slice()
  next[index] = snapGain(value, GAIN_LIMIT)
  gains.value = next
  preset.value = matchPreset(next)
  if (!enabled.value) setEnabled(true)
  else {
    apply()
    save()
  }
}

function setPreamp(value) {
  preamp.value = snapGain(value, PREAMP_LIMIT)
  apply()
  save()
}

function selectPreset(id) {
  gains.value = [...presetGains(id)]
  preset.value = matchPreset(gains.value)
  if (!enabled.value && id !== 'flat') setEnabled(true)
  else {
    apply()
    save()
  }
}

function reset() {
  const defaults = defaultSettings()
  gains.value = defaults.gains
  preset.value = defaults.preset
  preamp.value = defaults.preamp
  setEnabled(false)
}

// Another tab changed the settings.
if (
  typeof window !== 'undefined' &&
  typeof window.addEventListener === 'function'
) {
  window.addEventListener('storage', (event) => {
    if (event.key !== STORAGE_KEY) return
    const next = load()
    enabled.value = next.enabled
    preset.value = next.preset
    gains.value = next.gains
    preamp.value = next.preamp
    // Built on the next play in this tab (no user gesture here).
    apply()
  })
}

watch(headroom, () => apply())
// A new song's gain is set before its first sample (the element is
// paused while it loads); a change during playback ramps like the rest.
watch(normalizationGain, () => apply(allPaused()), {
  flush: 'sync',
})
watch(normalizationEnabled, (on) => {
  // Switched on here, while a song plays: route it now so it can be
  // leveled. Switched on from another tab or the account (no gesture, so
  // the context couldn't start and the song would go silent): on the
  // next play.
  const gesture = globalThis.navigator?.userActivation?.isActive === true
  if (on && gesture && !allPaused()) resumeEqualizer()
  apply()
})

export function useEqualizer() {
  return {
    supported,
    enabled,
    preset,
    gains,
    preamp,
    headroom,
    graphState,
    isCustom: computed(() => preset.value === CUSTOM),
    setEnabled,
    setGain,
    setPreamp,
    selectPreset,
    reset,
  }
}
