import { describe, expect, it } from 'vitest'
import { isGatewayError, requestErrorText } from '../lib/httpError.js'

const opts = { gatewayText: 'server failed', fallback: 'check it' }

describe('request errors', () => {
  it("hides Cloudflare's own error behind ours", () => {
    const cloudflare = {
      response: {
        status: 502,
        data: {
          title: 'Error 502: Bad gateway',
          detail:
            'The origin web server returned an invalid or incomplete response to Cloudflare.',
        },
      },
    }
    expect(isGatewayError(cloudflare)).toBe(true)
    expect(requestErrorText(cloudflare, opts)).toBe('server failed')
    const page = { response: { status: 504, data: '<!DOCTYPE html><html>' } }
    expect(requestErrorText(page, opts)).toBe('server failed')
  })

  it("keeps the server's own reason", () => {
    const ours = { response: { status: 404, data: { detail: 'Not found' } } }
    expect(isGatewayError(ours)).toBe(false)
    expect(requestErrorText(ours, opts)).toBe('Not found')
    const mine502 = { response: { status: 502, data: { detail: 'Boom' } } }
    expect(requestErrorText(mine502, opts)).toBe('Boom')
    expect(requestErrorText({ message: 'Network Error' }, opts)).toBe(
      'check it'
    )
  })
})
