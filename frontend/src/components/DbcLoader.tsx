import { useRef, useState } from 'react'
import { Upload, Database, Trash2, Loader2 } from 'lucide-react'
import { api } from '../hooks/useApi'
import type { WorkspaceState } from '../types'

interface Props {
  workspace: WorkspaceState
  onChanged: (state: WorkspaceState) => void
}

export function DbcLoader({ workspace, onChanged }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [programName, setProgramName] = useState('')
  const [open, setOpen] = useState(true)

  const run = async (action: () => Promise<WorkspaceState>) => {
    setBusy(true); setError(null); setNotice(null)
    try {
      const next = await action()
      onChanged(next)
      setNotice(next.notice ?? null)
    } catch (e: any) { setError(e.message) }
    finally { setBusy(false) }
  }
  const upload = (files: File[]) => {
    if (!busy && files.length) run(() => api.uploadDbcs(files))
  }
  const toggle = (id: string, active: boolean) => {
    const ids = workspace.files.filter(f => f.active && f.id !== id).map(f => f.id)
    if (active) ids.push(id)
    run(() => api.activateDbcs(ids))
  }

  return (
    <section className={`shrink-0 rounded border p-3 bg-canvas-surface ${dragging ? 'border-canvas-green' : 'border-canvas-border'}`}
      onDragOver={e => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={e => { e.preventDefault(); setDragging(false); upload(Array.from(e.dataTransfer.files)) }}>
      <div className="flex items-center flex-wrap gap-2 mb-3 text-sm">
        <label className="text-canvas-muted">Program
          <select aria-label="Program" value={workspace.active_program_id} disabled={busy} onChange={e => run(() => api.selectProgram(e.target.value))} className="ml-2 rounded border border-canvas-border bg-canvas-dark text-canvas-text px-2 py-1">
            {workspace.programs.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <input aria-label="New program name" placeholder="New program / app name" maxLength={80} value={programName} onChange={e => setProgramName(e.target.value)} disabled={busy} className="rounded border border-canvas-border bg-canvas-dark px-2 py-1 text-canvas-text" />
        <button disabled={busy || !programName.trim()} onClick={() => run(async () => { const next = await api.createProgram(programName); setProgramName(''); return next })} className="text-canvas-green border border-canvas-green/40 rounded px-2 py-1 disabled:opacity-50">Create program</button>
        <span className="text-xs text-canvas-muted">Favorites and active DBCs belong to this program</span>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Database size={17} className="text-canvas-green" />
        <button onClick={() => setOpen(v => !v)} className="text-sm font-semibold text-canvas-text" aria-expanded={open}>
          Saved DBCs · {workspace.files.length} saved · {workspace.files.filter(f => f.active).length} active
        </button>
        <span className="text-xs text-canvas-muted">Restored automatically on startup</span>
        <button disabled={busy} onClick={() => input.current?.click()} className="ml-auto flex items-center gap-2 rounded border border-canvas-green/40 bg-canvas-green/10 px-3 py-1.5 text-sm text-canvas-green disabled:opacity-50">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} Add DBC files
        </button>
        <input ref={input} aria-label="Add DBC files" type="file" accept=".dbc" multiple className="hidden" disabled={busy}
          onChange={e => { upload(Array.from(e.target.files ?? [])); e.target.value = '' }} />
      </div>
      {open && <div className="mt-2 max-h-36 overflow-auto">
        {workspace.files.length ? workspace.files.map(file => (
          <div key={file.id} className="flex items-center gap-3 py-1.5 border-t border-canvas-border/50 text-xs">
            <label className="flex items-center gap-2 min-w-0 flex-1 text-canvas-text">
              <input type="checkbox" checked={file.active} disabled={busy} onChange={e => toggle(file.id, e.target.checked)} aria-label={`Activate ${file.filename}`} />
              <span className="truncate" title={file.filename}>{file.filename}</span>
              <span className="text-canvas-muted">{file.id.slice(0, 7)}</span>
            </label>
            <span className="text-canvas-muted whitespace-nowrap">{file.message_count} messages</span>
            <span className={file.active ? 'text-canvas-green' : 'text-canvas-muted'}>{file.active ? 'Active' : 'Stored'}</span>
            <button aria-label={`Delete ${file.filename}`} disabled={busy} className="text-canvas-muted hover:text-canvas-red p-1"
              onClick={() => { if (window.confirm(`Remove ${file.filename} and its favorites from CANvas?`)) run(() => api.deleteDbc(file.id)) }}><Trash2 size={13} /></button>
          </div>
        )) : <p className="py-2 text-xs text-canvas-muted">Drop one or more DBC files here, or click Add DBC files. You only need to upload them once.</p>}
      </div>}
      {(error || workspace.restore_error) && <p role="alert" className="mt-2 text-xs text-canvas-red">{error || workspace.restore_error}</p>}
      {notice && <p role="status" className="mt-2 text-xs text-canvas-amber">{notice}</p>}
    </section>
  )
}
