import { useState, useRef, useEffect } from 'react'
import { Pause, Play, Trash2, Filter } from 'lucide-react'
import type { CanFrame } from '../types'

interface Props {
  frames: CanFrame[]
  connected: boolean
  onClear: () => void
}

export function BusMonitor({ frames, connected, onClear }: Props) {
  const [paused, setPaused] = useState(false)
  const [filter, setFilter] = useState('')
  const [displayedFrames, setDisplayedFrames] = useState<CanFrame[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const prevLenRef = useRef(0)

  useEffect(() => {
    if (!paused) {
      const filtered = filter
        ? frames.filter(f =>
            f.id_hex.toLowerCase().includes(filter.toLowerCase()) ||
            (f.message_name?.toLowerCase().includes(filter.toLowerCase())))
        : frames
      setDisplayedFrames(filtered)
    }
  }, [frames, paused, filter])

  useEffect(() => {
    if (!paused && displayedFrames.length > prevLenRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
    prevLenRef.current = displayedFrames.length
  }, [displayedFrames, paused])

  return (
    <div className="flex flex-col h-full bg-canvas-surface border border-canvas-border rounded overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-canvas-border bg-canvas-dark/60 shrink-0">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${connected ? 'bg-canvas-green animate-pulse' : 'bg-canvas-red'}`} />
          <span className="text-xs text-canvas-muted">{connected ? 'Monitoring' : 'Disconnected'}</span>
        </div>
        <span className="text-xs text-canvas-muted can-data">{displayedFrames.length} frames</span>

        <div className="flex items-center gap-1.5 ml-auto">
          <div className="flex items-center gap-1.5 bg-canvas-surface2 border border-canvas-border rounded px-2 py-1">
            <Filter size={11} className="text-canvas-muted" />
            <input
              type="text"
              placeholder="Filter by ID or name…"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              className="bg-transparent text-canvas-text text-xs outline-none w-36 placeholder:text-canvas-muted"
            />
          </div>
          <button
            onClick={() => setPaused(!paused)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs border transition-colors
              ${paused
                ? 'border-canvas-green text-canvas-green hover:bg-canvas-green/10'
                : 'border-canvas-border text-canvas-muted hover:border-canvas-amber hover:text-canvas-amber'
              }`}
          >
            {paused ? <><Play size={11}/> Resume</> : <><Pause size={11}/> Pause</>}
          </button>
          <button
            onClick={onClear}
            className="flex items-center gap-1 px-2.5 py-1 rounded text-xs border
              border-canvas-border text-canvas-muted hover:border-canvas-red hover:text-canvas-red transition-colors"
          >
            <Trash2 size={11}/> Clear
          </button>
        </div>
      </div>

      {/* Column headers */}
      <div className="grid gap-2 px-4 py-1.5 text-xs text-canvas-muted border-b border-canvas-border
        bg-canvas-dark/40 shrink-0"
        style={{ gridTemplateColumns: '100px 110px 140px minmax(160px, 1fr) minmax(200px, 1fr)' }}>
        <span>Timestamp</span>
        <span>ID</span>
        <span>Message</span>
        <span>Data</span>
        <span>Decoded Signals</span>
      </div>

      {/* Frames */}
      <div className="flex-1 overflow-auto can-data text-xs">
        {displayedFrames.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-canvas-muted gap-3">
            <div className="text-4xl">📡</div>
            <p>No frames yet</p>
            <p className="text-xs">Connect to a bus and send signals to see traffic here</p>
          </div>
        ) : (
          displayedFrames.map((frame, i) => (
            <div
              key={`${frame.timestamp}-${i}`}
              className={`frame-new grid gap-2 px-4 py-1.5 border-b border-canvas-border/30
                hover:bg-canvas-surface2 transition-colors items-center`}
              style={{ gridTemplateColumns: '100px 110px 140px minmax(160px, 1fr) minmax(200px, 1fr)' }}
            >
              <span className="text-canvas-muted">{frame.timestamp.toFixed?.(3) ?? frame.timestamp}</span>
              <span className="text-canvas-blue font-semibold">{frame.id_hex}<span className="block text-canvas-muted font-normal">{frame.direction ?? 'RX'}{frame.is_fd ? ' · FD' : ''}</span></span>
              <span className="text-canvas-text truncate">{frame.message_name ?? '—'}</span>
              <span className="text-canvas-amber tracking-widest break-all">{frame.data_hex}</span>
              <span className="text-canvas-muted truncate">
                {frame.decoded && Object.keys(frame.decoded).length > 0
                  ? Object.entries(frame.decoded)
                      .map(([k, v]) => `${k}=${typeof v === 'number' ? v.toFixed(2) : v}`)
                      .join(' · ')
                  : '—'}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
