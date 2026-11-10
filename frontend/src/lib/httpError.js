// What to tell someone when a request failed. A server behind Cloudflare
// that answers 502/504 (or doesn't answer) comes back as Cloudflare's own
// page or JSON ("The origin web server returned an invalid or incomplete
// response to Cloudflare...") - meaningless to a listener, so it is
// replaced by our own sentence.

const GATEWAY = new Set([502, 503, 504, 520, 521, 522, 523, 524, 525, 526])

/** Whether `err` is a proxy's (Cloudflare's) error rather than ours. */
export function isGatewayError(err) {
  const response = err?.response
  if (!response) return false
  const data = response.data
  const text =
    typeof data === 'string'
      ? data
      : String(data?.detail || data?.title || data?.message || '')
  if (/cloudflare/i.test(text)) return true
  if (typeof data === 'string' && /<html|<!doctype/i.test(data)) return true
  return GATEWAY.has(response.status) && !data?.detail
}

/**
 * The message to show for `err`: the server's own `detail` when it gave
 * one, `gatewayText` for a proxy's error page, else `fallback`.
 */
export function requestErrorText(
  err,
  { gatewayText = '', fallback = '' } = {}
) {
  if (isGatewayError(err)) return gatewayText || fallback
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  return fallback || err?.message || ''
}
