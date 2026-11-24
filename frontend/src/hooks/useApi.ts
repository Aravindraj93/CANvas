import type { BusStatus, WorkspaceState, Favorite, TrafficState, Verification } from '../types'

export const API_BASE = import.meta.env.DEV ? 'http://localhost:8765/api' : '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail) || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  health: () => request<{ status: string; version: string }>('/health'),

  // DBC
  createProgram: (name: string) => request<WorkspaceState>('/dbc/programs', { method: 'POST', body: JSON.stringify({ name }) }),
  selectProgram: (program_id: string) => request<WorkspaceState>('/dbc/programs/select', { method: 'POST', body: JSON.stringify({ program_id }) }),
  workspaceState: () => request<WorkspaceState>('/dbc/state'),
  uploadDbcs: async (files: File[]) => {
    const form = new FormData()
    files.forEach(file => form.append('files', file))
    const res = await fetch(`${API_BASE}/dbc/upload-many`, { method: 'POST', body: form })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail))
    }
    return res.json() as Promise<WorkspaceState>
  },
  activateDbcs: (dbc_ids: string[]) => request<WorkspaceState>('/dbc/active', { method: 'POST', body: JSON.stringify({ dbc_ids }) }),
  deleteDbc: (dbc_id: string) => request<WorkspaceState>(`/dbc/files/${dbc_id}`, { method: 'DELETE' }),
  setFavorite: (dbc_id: string, message_name: string, signal_name: string | null, favorite: boolean) =>
    request<{ favorites: Favorite[] }>('/dbc/favorites', { method: 'POST', body: JSON.stringify({ dbc_id, message_name, signal_name, favorite }) }),
  messageStatus: (keys: string[]) => {
    const query = new URLSearchParams({ visible_only: 'true' })
    keys.forEach(key => query.append('keys', key))
    return request<TrafficState>(`/signals/status?${query}`)
  },
  verifyMessage: (message_name: string, dbc_id: string | null | undefined, expected: Record<string, number>, max_age_ms: number) =>
    request<Verification>('/signals/verify', { method: 'POST', body: JSON.stringify({ message_name, dbc_id, expected, max_age_ms }) }),
  uploadDbc: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`${API_BASE}/dbc/upload`, { method: 'POST', body: form })
      .then(r => { if (!r.ok) return r.json().then(e => Promise.reject(new Error(e.detail))); return r.json() })
  },
  getMessages: () => request<{ messages: any[]; message_count: number }>('/dbc/messages'),
  unloadDbc: () => request('/dbc/unload', { method: 'DELETE' }),

  // Signals
  sendSignal: (message_name: string, signal_name: string, value: number, dbc_id?: string | null) =>
    request('/signals/send', { method: 'POST', body: JSON.stringify({ message_name, signal_name, value, dbc_id }) }),
  sendMessage: (message_name: string, signals: Record<string, number>, dbc_id?: string | null) =>
    request('/signals/send-message', { method: 'POST', body: JSON.stringify({ message_name, signals, dbc_id }) }),
  startCyclic: (message_name: string, signals: Record<string, number>, period_ms: number, dbc_id?: string | null) =>
    request('/signals/start-cyclic', { method: 'POST', body: JSON.stringify({ message_name, signals, period_ms, dbc_id }) }),
  stopCyclic: (message_name: string, dbc_id?: string | null) =>
    request('/signals/stop-cyclic', { method: 'POST', body: JSON.stringify({ message_name, dbc_id }) }),
  cyclicStatus: () => request<{ cyclic_messages: string[]; errors: Record<string, string> }>('/signals/cyclic'),
  busStatus: () => request<any>('/signals/bus/status'),
  busConnect: (bus_type: string, channel?: string, bitrate?: number, options: { fd?: boolean; data_bitrate?: number; bitrate_switch?: boolean; serial?: string } = {}) =>
    request<BusStatus>('/signals/bus/connect', { method: 'POST', body: JSON.stringify({ bus_type, channel, bitrate: bitrate ?? 500000, ...options }) }),
  busDisconnect: () => request('/signals/bus/disconnect', { method: 'POST' }),

  // Tests
  runTest: (test_yaml: string) =>
    request<any>('/tests/run', { method: 'POST', body: JSON.stringify({ test_yaml }) }),
  cancelTest: () => request<{ cancellation_requested: boolean; detail: string }>('/tests/cancel', { method: 'POST' }),
  generateTest: (prompt: string) =>
    request<{ yaml: string }>('/tests/generate', { method: 'POST', body: JSON.stringify({ prompt }) }),
}
