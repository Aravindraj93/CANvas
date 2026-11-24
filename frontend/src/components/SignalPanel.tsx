import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Send, RefreshCw, Play, Square, Star, ShieldCheck } from 'lucide-react'
import { api } from '../hooks/useApi'
import type { DbcMessage, DbcSignal, MessageTraffic, Verification } from '../types'

interface Props {
  message: DbcMessage
  messageFavorite: boolean
  signalFavorites: string[]
  favoritesOnly: boolean
  favoriteBusy: boolean
  onToggleFavorite: (signalName?: string) => void
  traffic?: MessageTraffic
  cyclic: boolean
  cyclicError?: string
  onActivityChanged: () => Promise<void>
}

export function SignalPanel({ message, messageFavorite, signalFavorites, favoritesOnly, favoriteBusy, onToggleFavorite, traffic, cyclic, cyclicError, onActivityChanged }: Props) {
  const [expanded, setExpanded] = useState(true)
  const [values, setValues] = useState<Record<string, number>>(() => {
    const init: Record<string, number> = {}
    for (const s of message.signals) init[s.name] = s.initial_value ?? s.min_value
    return init
  })
  const [sending, setSending] = useState<string | null>(null)
  const [periodMs, setPeriodMs] = useState(message.cycle_time && message.cycle_time > 0 ? message.cycle_time : 100)
  const [error, setError] = useState<string | null>(null)
  const [lastSent, setLastSent] = useState<string | null>(null)

  const [verification, setVerification] = useState<Verification | null>(null)
  const [maxAge, setMaxAge] = useState(Math.max(1000, (message.cycle_time ?? 0) * 3))
  const visibleSignals = favoritesOnly && !messageFavorite
    ? message.signals.filter(sig => signalFavorites.includes(sig.name)) : message.signals
  const valuesToSend = favoritesOnly && !messageFavorite
    ? Object.fromEntries(visibleSignals.map(sig => [sig.name, values[sig.name]])) : values
  const statusLabel: Record<string, string> = {
    disconnected: 'Disconnected', tx_error: 'TX error', receiving: 'Receiving', stale: 'RX stale',
    decode_error: 'RX decode error', tx_echo: 'TX echo observed', tx_only: 'Send accepted', not_seen: 'Not seen',
  }
  const statusColor = traffic?.state === 'receiving' ? 'text-canvas-green' :
    ['tx_error', 'decode_error', 'stale'].includes(traffic?.state ?? '') ? 'text-canvas-red' : 'text-canvas-muted'
  useEffect(() => { setVerification(null) }, [values, message.key])

  const verify = async () => {
    setSending('__verify__'); setError(null)
    try {
      const expected = Object.fromEntries(visibleSignals.map(sig => [sig.name, values[sig.name]]))
      setVerification(await api.verifyMessage(message.name, message.dbc_id, expected, maxAge))
    } catch (e: any) { setError(e.message) }
    finally { setSending(null) }
  }

  const sendSignal = async (sig: DbcSignal) => {
    setSending(sig.name)
    setError(null)
    try {
      await api.sendSignal(message.name, sig.name, values[sig.name], message.dbc_id)
      await onActivityChanged()
      setLastSent(`${sig.name} = ${values[sig.name]?.toFixed(2)} ${sig.unit}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSending(null)
      setTimeout(() => setLastSent(null), 3000)
    }
  }

  const sendAll = async () => {
    setSending('__all__')
    setError(null)
    try {
      await api.sendMessage(message.name, valuesToSend, message.dbc_id)
      await onActivityChanged()
      setLastSent(`Sent ${message.name} (${message.signals.length} signals)`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSending(null)
      setTimeout(() => setLastSent(null), 3000)
    }
  }

  const toggleCyclic = async () => {
    setSending('__cyclic__')
    setError(null)
    try {
      if (cyclic) {
        await api.stopCyclic(message.name, message.dbc_id)
      } else {
        await api.startCyclic(message.name, valuesToSend, periodMs, message.dbc_id)
      }
      await onActivityChanged()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSending(null)
    }
  }

  return (
    <div className={`bg-canvas-surface border rounded overflow-hidden transition-colors
      ${cyclic ? 'border-canvas-green' : 'border-canvas-border'}`}>
      {/* Favorites button is separate from the expand button. */}
      <div className="flex items-center">
      <button aria-label={`Favorite message ${message.name}`} aria-pressed={messageFavorite} disabled={favoriteBusy}
        onClick={() => onToggleFavorite()} className={`pl-3 pr-1 ${messageFavorite ? 'text-canvas-amber' : 'text-canvas-muted'}`}>
        <Star size={16} fill={messageFavorite ? 'currentColor' : 'none'} />
      </button>
      <button
        onClick={() => setExpanded(!expanded)}
        className="min-w-0 flex-1 flex items-center gap-3 px-3 py-3 hover:bg-canvas-surface2 transition-colors text-left"
      >
        <span className="text-canvas-muted">{expanded ? <ChevronDown size={14}/> : <ChevronRight size={14}/>}</span>
        <span title={message.name} className="font-semibold text-canvas-text text-sm truncate">{message.name}</span>
        <span className="can-data text-xs text-canvas-blue bg-blue-900/20 px-2 py-0.5 rounded">
          {message.arbitration_id_hex}
        </span>
        {message.is_fd && <span className="text-xs text-canvas-amber">FD</span>}
        <span className="text-xs text-canvas-muted ml-auto">{message.signals.length} signals</span>
        {cyclic && (
          <span className="text-xs text-canvas-green flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-canvas-green animate-pulse" />
            CYCLIC
          </span>
        )}
      </button>
      </div>
      <div className="px-4 pb-2 text-xs text-canvas-muted truncate" title={message.dbc_filename ?? ''}>{message.dbc_filename}</div>
      <div className="px-4 py-2 border-t border-canvas-border/50 text-xs">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className={`font-semibold ${statusColor}`}>{statusLabel[traffic?.state ?? 'not_seen']}</span>
          <span className="text-canvas-muted">TX {traffic?.tx_count ?? 0} · Echo {traffic?.tx_echo_count ?? 0} · RX {traffic?.rx_count ?? 0}</span>
          {traffic?.rx_age_ms != null && <span className="text-canvas-muted">RX age {traffic.rx_age_ms.toFixed(0)} ms</span>}
        </div>
        {(traffic?.last_tx_error || traffic?.decode_error || cyclicError) && <p className="mt-1 text-canvas-red break-words">{cyclicError || traffic?.last_tx_error || traffic?.decode_error}</p>}
      </div>

      {/* Signals */}
      {expanded && (
        <div className="border-t border-canvas-border">
          {visibleSignals.map(sig => (
            <div key={sig.name} className="px-4 py-3 border-b border-canvas-border/50 last:border-b-0">
              <div className="flex items-center gap-2 mb-2">
                <button aria-label={`Favorite signal ${sig.name}`} aria-pressed={signalFavorites.includes(sig.name)} disabled={favoriteBusy}
                  onClick={() => onToggleFavorite(sig.name)} className={signalFavorites.includes(sig.name) ? 'text-canvas-amber' : 'text-canvas-muted'}>
                  <Star size={13} fill={signalFavorites.includes(sig.name) ? 'currentColor' : 'none'} />
                </button>
                <span className="text-canvas-text text-sm font-medium">{sig.name}</span>
                {sig.unit && <span className="text-xs text-canvas-muted">[{sig.unit}]</span>}
                {traffic?.decoded[sig.name] !== undefined && <span className={`text-xs ${traffic.state === 'receiving' ? 'text-canvas-blue' : 'text-canvas-muted'}`}>RX {traffic.decoded[sig.name].toFixed(2)}</span>}
                <span className="can-data text-xs text-canvas-muted ml-auto">
                  {sig.min_value} – {sig.max_value}
                </span>
              </div>

              {sig.default_warning && <p className="text-xs text-canvas-amber mb-2">{sig.default_warning}</p>}
              <div className="flex items-center flex-wrap gap-3">
                {sig.choices?.length ? <select aria-label={`Text value for ${sig.name}`} value={sig.choices.some(c => c.value === values[sig.name]) ? String(values[sig.name]) : ''}
                  onChange={e => { if (e.target.value !== '') setValues(v => ({ ...v, [sig.name]: Number(e.target.value) })) }} className="max-w-full bg-canvas-dark border border-canvas-border rounded px-2 py-1 text-canvas-text text-sm">
                  <option value="">Numeric value</option>
                  {sig.choices.map(choice => <option key={choice.raw_value} value={choice.value}>{choice.label} (raw {choice.raw_value})</option>)}
                </select> : null}
                <input
                  type="range"
                  aria-label={`Adjust ${sig.name}`}
                  min={sig.min_value}
                  max={sig.max_value}
                  step={(sig.max_value - sig.min_value) / 200}
                  value={values[sig.name] ?? sig.min_value}
                  onChange={e => setValues(v => ({ ...v, [sig.name]: parseFloat(e.target.value) }))}
                  className="flex-1"
                />
                <input
                  type="number"
                  aria-label={`Set ${sig.name}`}
                  min={sig.min_value}
                  max={sig.max_value}
                  value={(values[sig.name] ?? sig.min_value).toFixed(2)}
                  onChange={e => {
                    const v = parseFloat(e.target.value)
                    if (!isNaN(v)) setValues(prev => ({ ...prev, [sig.name]: v }))
                  }}
                  className="w-24 bg-canvas-dark border border-canvas-border rounded px-2 py-1
                    text-canvas-text can-data text-sm text-right focus:outline-none focus:border-canvas-green"
                />
                <button
                  onClick={() => sendSignal(sig)}
                  disabled={sending !== null}
                  className="flex items-center gap-1 px-2.5 py-1.5 bg-canvas-green/10 border border-canvas-green/30
                    text-canvas-green rounded text-xs font-medium hover:bg-canvas-green/20 transition-colors
                    disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Send size={11} />
                  {sending === sig.name ? '…' : 'Send'}
                </button>
              </div>
            </div>
          ))}

          <div className="px-4 py-2 border-t border-canvas-border/50 text-xs">
            <div className="flex items-center flex-wrap gap-2">
              <button onClick={verify} disabled={sending !== null || maxAge < 1} className="flex items-center gap-1 text-canvas-blue border border-canvas-border rounded px-2 py-1 disabled:opacity-50">
                <ShieldCheck size={12} /> Verify latest RX
              </button>
              <label className="text-canvas-muted flex items-center gap-1">Max age
                <input aria-label={`Maximum RX age for ${message.name}`} type="number" min="1" value={maxAge} onChange={e => setMaxAge(Number(e.target.value))} className="w-20 bg-canvas-dark border border-canvas-border rounded px-1 py-1" /> ms
              </label>
            </div>
            {verification && <div role="status" className={`mt-2 ${verification.status === 'PASS' ? 'text-canvas-green' : 'text-canvas-red'}`}>
              <p>Snapshot check: {verification.status} · {verification.reason}</p>
              {verification.comparisons.filter(c => !c.match).map(c => <p key={c.signal}>{c.signal}: expected {c.expected}, received {c.actual ?? 'missing'}</p>)}
            </div>}
          </div>
          {/* Footer actions */}
          {error && <p role="alert" className="px-4 py-2 text-xs text-canvas-red break-words">{error}</p>}
          {cyclic && <p className="px-4 py-1 text-xs text-canvas-muted">Click Apply & Send after editing values to update cyclic transmission.</p>}
          <div className="flex items-center gap-2 flex-wrap px-4 py-2.5 bg-canvas-dark/40">
            {lastSent && (
              <span className="text-xs text-canvas-muted truncate flex-1">{lastSent}</span>
            )}
            <div className="flex gap-2 ml-auto">
              <label className="flex items-center gap-1 text-xs text-canvas-muted">
                <input aria-label="Cycle time in milliseconds" type="number" min="1" value={periodMs} disabled={cyclic} onChange={e => setPeriodMs(Number(e.target.value))} className="w-16 bg-canvas-dark border border-canvas-border rounded px-1 py-1 text-canvas-text" /> ms
              </label>
              <button
                onClick={toggleCyclic}
                disabled={sending !== null || periodMs < 1}
                className={`flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium transition-colors border
                  ${cyclic
                    ? 'border-canvas-red/40 text-canvas-red bg-red-900/10 hover:bg-red-900/20'
                    : 'border-canvas-border text-canvas-muted hover:text-canvas-amber hover:border-canvas-amber'
                  }`}
              >
                {cyclic ? <><Square size={11}/> Stop</> : <><RefreshCw size={11}/> Cyclic</>}
              </button>
              <button
                onClick={sendAll}
                disabled={sending !== null}
                className="flex items-center gap-1 px-3 py-1.5 bg-canvas-green/15 border border-canvas-green/40
                  text-canvas-green rounded text-xs font-medium hover:bg-canvas-green/25 transition-colors
                  disabled:opacity-50"
              >
                <Play size={11} />
                {cyclic ? 'Apply & Send' : favoritesOnly && !messageFavorite ? 'Send visible' : 'Send All'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
