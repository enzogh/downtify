// A failed download's raw message (yt-dlp, ffmpeg, the network) as the
// key of a sentence anyone can read, or '' when it isn't one we know -
// the raw message is then shown as it is. The queue keeps the raw text in
// a tooltip, for whoever needs the detail.

const RULES = [
  [/sign in to confirm|not a bot|429|too many requests/i, 'blocked'],
  [
    /video unavailable|private video|has been removed|not available/i,
    'unavailable',
  ],
  [/age[- ]?restrict|confirm your age|inappropriate/i, 'ageRestricted'],
  [/copyright|blocked it in your country|geo[- ]?restrict/i, 'region'],
  [/postprocess|ffmpeg|ffprobe|conversion/i, 'conversion'],
  [/no (results|match)|nothing found|could not find/i, 'notFound'],
  [
    /timed? ?out|connection|network|resolve host|ssl|temporary failure/i,
    'network',
  ],
  [/no space|disk full|errno 28/i, 'diskFull'],
  [/permission denied|errno 13|read-only/i, 'permission'],
]

/** `queue.reason.<key>` for `message`, or ''. */
export function failureReasonKey(message) {
  const text = String(message || '')
  if (!text) return ''
  for (const [pattern, key] of RULES) {
    if (pattern.test(text)) return `queue.reason.${key}`
  }
  return ''
}
