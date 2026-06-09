import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '@/api/client'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    headers: { get: () => 'application/json' },
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

describe('connections api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('getConnectionPresets GETs /api/v1/connection-presets', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ catalog: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await api.getConnectionPresets()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/connection-presets', expect.anything())
  })

  it('getClis GETs /api/v1/clis', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true, clis: {} }))
    vi.stubGlobal('fetch', fetchMock)
    await api.getClis()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/clis', expect.anything())
  })

  it('getConnections GETs /api/v1/connections', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ connections: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await api.getConnections()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/connections', expect.anything())
  })

  it('createConnection POSTs the body to /api/v1/connections', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true, connection: { id: 'conn-1' } }))
    vi.stubGlobal('fetch', fetchMock)
    const body = { provider: 'deepseek', engine: 'claude', authMethod: 'api_key', model: 'deepseek-chat', key: 'sk-x' }
    await api.createConnection(body)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/connections')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual(body)
  })

  it('deleteConnection DELETEs /api/v1/connections/{id}', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    await api.deleteConnection('conn-9')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/connections/conn-9')
    expect(init.method).toBe('DELETE')
  })

  it('testConnection POSTs /api/v1/connections/{id}/test', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true, status: 'connected', error: null }))
    vi.stubGlobal('fetch', fetchMock)
    const res = await api.testConnection('conn-7')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/connections/conn-7/test')
    expect(init.method).toBe('POST')
    expect(res.status).toBe('connected')
  })
})
