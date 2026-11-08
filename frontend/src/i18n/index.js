import { ref } from 'vue'
import en from './locales/en.js'
import es from './locales/es.js'
import ptBR from './locales/pt-BR.js'
import el from './locales/el.js'
import fr from './locales/fr.js'
import tr from './locales/tr.js'
import hu from './locales/hu.js'
import bg from './locales/bg.js'
import de from './locales/de.js'
import ko from './locales/ko.js'
import zhCN from './locales/zh-CN.js'

// Registry of available locales. To add a new language:
//   1. Create ./locales/<code>.js exporting the same key shape as en.js
//   2. Import it above
//   3. Add an entry below — `code` is the value stored in localStorage,
//      `name` is the label shown in the language picker.
export const AVAILABLE_LOCALES = [
  { code: 'en', name: 'English', messages: en },
  { code: 'es', name: 'Español', messages: es },
  { code: 'pt-BR', name: 'Português (BR)', messages: ptBR },
  { code: 'el', name: 'Ελληνικά', messages: el },
  { code: 'fr', name: 'Français', messages: fr },
  { code: 'tr', name: 'Türkçe', messages: tr },
  { code: 'hu', name: 'Magyar', messages: hu },
  { code: 'bg', name: 'Български', messages: bg },
  { code: 'de', name: 'Deutsch', messages: de },
  { code: 'ko', name: '한국어', messages: ko },
  { code: 'zh-CN', name: '简体中文', messages: zhCN },
]

// Messages a locale lacks fall back to English, the source language.
const DEFAULT_LOCALE = 'en'
// What everyone sees until they pick another language.
export const INITIAL_LOCALE = 'fr'
const STORAGE_KEY = 'downtify-locale'
// Set once English (the old default, saved automatically) has been
// switched to French in this browser - after that, English is a choice.
const FRENCH_DEFAULT_KEY = 'downtify-locale-fr-default'

function readStorage(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

/**
 * The language to use for a saved one: French when nothing (valid) is
 * saved, and once, French for the English the old default saved.
 */
export function defaultedLocale(saved, migrated) {
  const known = AVAILABLE_LOCALES.some((l) => l.code === saved)
  if (!known) return INITIAL_LOCALE
  if (saved === DEFAULT_LOCALE && !migrated) return INITIAL_LOCALE
  return saved
}

/** True the first time this browser meets the French default. */
export function takeFrenchDefault() {
  if (readStorage(FRENCH_DEFAULT_KEY)) return false
  try {
    localStorage.setItem(FRENCH_DEFAULT_KEY, '1')
  } catch {
    // ignore
  }
  return true
}

const migratedBefore = Boolean(readStorage(FRENCH_DEFAULT_KEY))
const initial = defaultedLocale(readStorage(STORAGE_KEY), migratedBefore)

export const currentLocale = ref(initial)

function localeData(code) {
  return (
    AVAILABLE_LOCALES.find((l) => l.code === code) ||
    AVAILABLE_LOCALES.find((l) => l.code === DEFAULT_LOCALE)
  )
}

const PLURAL_FORMS = ['zero', 'one', 'two', 'few', 'many', 'other']

/** `{ one: '…', other: '…' }` — a message with plural forms. */
function isPlural(value) {
  return (
    value !== null &&
    typeof value === 'object' &&
    typeof value.other === 'string' &&
    Object.keys(value).every((form) => PLURAL_FORMS.includes(form))
  )
}

function lookup(messages, key) {
  if (!messages) return undefined
  const parts = key.split('.')
  let cur = messages
  for (const p of parts) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = cur[p]
  }
  return typeof cur === 'string' || isPlural(cur) ? cur : undefined
}

const numberFormats = new Map()
const pluralRules = new Map()

function cached(map, code, make) {
  if (!map.has(code)) map.set(code, make(code))
  return map.get(code)
}

function format(template, params, code) {
  if (!params) return template
  const numbers = cached(numberFormats, code, (c) => new Intl.NumberFormat(c))
  return template.replace(/\{(\w+)\}/g, (_, name) => {
    const value = params[name]
    if (value === undefined || value === null) return `{${name}}`
    return typeof value === 'number' ? numbers.format(value) : String(value)
  })
}

export function t(key, params) {
  const code = currentLocale.value
  let msg = lookup(localeData(code).messages, key)
  let msgCode = code
  if (msg === undefined && code !== DEFAULT_LOCALE) {
    msg = lookup(localeData(DEFAULT_LOCALE).messages, key)
    msgCode = DEFAULT_LOCALE
  }
  if (msg === undefined) return key
  if (isPlural(msg)) {
    const rules = cached(pluralRules, msgCode, (c) => new Intl.PluralRules(c))
    const count = Number(params?.count ?? 0)
    msg = msg[rules.select(count)] ?? msg.other
  }
  return format(msg, params, code)
}

export function setLocale(code) {
  if (!AVAILABLE_LOCALES.find((l) => l.code === code)) return
  currentLocale.value = code
  try {
    localStorage.setItem(STORAGE_KEY, code)
  } catch {
    // ignore storage errors (private mode, etc.)
  }
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('lang', code)
  }
}

export function useI18n() {
  return {
    t,
    locale: currentLocale,
    setLocale,
    locales: AVAILABLE_LOCALES,
  }
}

// Apply on initial load
if (typeof document !== 'undefined') {
  document.documentElement.setAttribute('lang', currentLocale.value)
}
