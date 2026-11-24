import { useState, useEffect, useCallback } from 'react'
import { Header } from './components/Header'
import { DbcLoader } from './components/DbcLoader'
import { SignalPanel } from './components/SignalPanel'
import { BusConnect } from './components/BusConnect'
import { BusMonitor } from './components/BusMonitor'
import { TestRunner } from './components/TestRunner'
import { AiGenerator } from './components/AiGenerator'
import { useWebSocket } from './hooks/useWebSocket'
import { api } from './hooks/useApi'
import type { DbcMessage, BusStatus, WorkspaceState, TrafficState } from './types'

type Tab = 'studio' | 'monitor' | 'tests' | 'help'

// Lazy load test yaml from URL to pass to test runner
let _pendingYaml: string | null = null

export default function App() {
  const [tab, setTab] = useState<Tab>('studio')
  const [workspace, setWorkspace] = useState<WorkspaceState>({ files: [], messages: [], message_count: 0, favorites: [], programs: [], active_program_id: 'default' })
  const messages = workspace.messages
  const [workspaceError, setWorkspaceError] = useState<string | null>(null)
  const [favoritesOnly, setFavoritesOnly] = useState(false)
  const [dbcFilter, setDbcFilter] = useState('all')
  const [favoriteBusy, setFavoriteBusy] = useState(false)
  const [activity, setActivity] = useState<TrafficState>({ messages: {}, cyclic_messages: [], errors: {} })
  const [activityError, setActivityError] = useState<string | null>(null)
  const isFavorite = (msg: DbcMessage, signal = '') => workspace.favorites.some(f => f.dbc_id === msg.dbc_id && f.message_name === msg.name && f.signal_name === signal)

  const [search, setSearch] = useState('')
  const [visibleCount, setVisibleCount] = useState(20)
  const filteredMessages = messages.filter(msg => {
    if (dbcFilter !== 'all' && msg.dbc_id !== dbcFilter) return false
    const selectedSignals = favoritesOnly && !isFavorite(msg)
      ? msg.signals.filter(sig => isFavorite(msg, sig.name)) : msg.signals
    if (favoritesOnly && !isFavorite(msg) && !selectedSignals.length) return false
    const term = search.toLowerCase()
    return msg.name.toLowerCase().includes(term) || msg.arbitration_id_hex.toLowerCase().includes(term) ||
      selectedSignals.some(sig => sig.name.toLowerCase().includes(term))
  })
  const statusKeys = JSON.stringify(tab === 'studio' ? filteredMessages.slice(0, visibleCount).map(msg => msg.key) : [])
  const refreshActivity = useCallback(async () => {
    try {
      const next = await api.messageStatus(JSON.parse(statusKeys))
      setActivity(next); setActivityError(null)
    } catch (e: any) {
      setActivity({ messages: {}, cyclic_messages: [], errors: {} })
      setActivityError(`Live message status unavailable: ${e.message}`)
    }
  }, [statusKeys])

  useEffect(() => {
    let active = true
    api.workspaceState().then(state => { if (active) setWorkspace(state) }).catch(e => { if (active) setWorkspaceError(e.message) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    refreshActivity()
    const timer = setInterval(refreshActivity, 1000)
    return () => clearInterval(timer)
  }, [refreshActivity])

  const toggleFavorite = async (msg: DbcMessage, signal = '') => {
    if (!msg.dbc_id || favoriteBusy) return
    setFavoriteBusy(true); setWorkspaceError(null)
    try {
      const result = await api.setFavorite(msg.dbc_id, msg.name, signal || null, !isFavorite(msg, signal))
      setWorkspace(current => ({ ...current, favorites: result.favorites }))
    } catch (e: any) { setWorkspaceError(e.message) }
    finally { setFavoriteBusy(false) }
  }
  const [busStatus, setBusStatus] = useState<BusStatus>({ connected: false, bus_type: 'virtual' })
  const [testYaml, setTestYaml] = useState<string | null>(null)
  const { frames, connected: wsConnected, clear: clearFrames } = useWebSocket()

  // Poll bus status
  useEffect(() => {
    const poll = () => api.busStatus().then(setBusStatus).catch(() => {})
    poll()
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [])

  const handleUseYaml = (yaml: string) => {
    setTestYaml(yaml)
    setTab('tests')
  }

  return (
    <div className="h-screen flex flex-col bg-canvas-dark overflow-hidden">
      <Header
        activeTab={tab}
        onTabChange={setTab}
        busStatus={busStatus}
        wsConnected={wsConnected}
      />

      <main className="flex-1 overflow-hidden p-4">
        {/* Signal Studio */}
        {tab === 'studio' && (
          <div className="h-full flex flex-col gap-4 overflow-hidden">
            <DbcLoader workspace={workspace} onChanged={next => { setWorkspace(next); setWorkspaceError(null); setDbcFilter('all'); setSearch(''); setVisibleCount(20); refreshActivity() }} />
            {workspaceError && <p role="alert" className="text-xs text-canvas-red">{workspaceError}</p>}
            {activityError && <p role="alert" className="text-xs text-canvas-amber">{activityError}</p>}
            <BusConnect status={busStatus} onStatusChange={setBusStatus} />

            {messages.length > 0 ? (
              <div className="flex-1 min-h-0 flex flex-col gap-3">
                <p className="text-xs text-canvas-muted">RX status shows observed bus traffic. A send or TX echo does not confirm that the HMI accepted a value.</p>
                <div className="flex flex-wrap items-center gap-3 shrink-0">
                  <button aria-pressed={favoritesOnly} onClick={() => { setFavoritesOnly(v => !v); setVisibleCount(20) }} className={`px-3 py-2 rounded border text-sm ${favoritesOnly ? 'border-canvas-amber text-canvas-amber' : 'border-canvas-border text-canvas-muted'}`}>
                    {favoritesOnly ? '★ Favorites' : '☆ Favorites'}
                  </button>
                  <select aria-label="Filter DBC" value={dbcFilter} onChange={e => { setDbcFilter(e.target.value); setVisibleCount(20) }} className="max-w-52 bg-canvas-surface border border-canvas-border rounded px-2 py-2 text-sm text-canvas-text">
                    <option value="all">All active DBCs</option>
                    {workspace.files.filter(f => f.active).map(f => <option key={f.id} value={f.id}>{f.filename} · {f.id.slice(0, 7)}</option>)}
                  </select>
                  <input
                    type="search"
                    aria-label="Search CAN messages, IDs, or signals"
                    placeholder="Search message name, CAN ID, or signal..."
                    value={search}
                    onChange={e => { setSearch(e.target.value); setVisibleCount(20) }}
                    className="flex-1 bg-canvas-surface border border-canvas-border rounded px-3 py-2 text-canvas-text text-sm focus:outline-none focus:border-canvas-green"
                  />
                  <span className="text-xs text-canvas-muted whitespace-nowrap">
                    Showing {Math.min(visibleCount, filteredMessages.length)} of {filteredMessages.length}
                  </span>
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto">
                  <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 items-start">
                    {filteredMessages.slice(0, visibleCount).map(msg => (
                      <SignalPanel key={`${workspace.active_program_id}:${msg.key}`} message={msg}
                        messageFavorite={isFavorite(msg)} signalFavorites={msg.signals.filter(sig => isFavorite(msg, sig.name)).map(sig => sig.name)}
                        favoritesOnly={favoritesOnly} favoriteBusy={favoriteBusy} onToggleFavorite={signal => toggleFavorite(msg, signal)}
                        traffic={activity.messages[msg.key]} cyclic={activity.cyclic_messages.includes(msg.key)} cyclicError={activity.errors[msg.key]}
                        onActivityChanged={refreshActivity} />
                    ))}
                  </div>
                  {filteredMessages.length === 0 && (
                    <p className="text-center text-canvas-muted py-12">No matching active messages or favorites. Enable the DBC in Saved DBCs to access its favorites.</p>
                  )}
                  {visibleCount < filteredMessages.length && (
                    <button
                      onClick={() => setVisibleCount(count => count + 20)}
                      className="block mx-auto my-6 rounded border border-canvas-green/50 px-5 py-2 text-canvas-green text-sm hover:bg-canvas-green/10"
                    >
                      Load 20 more messages
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center text-canvas-muted">
                <div className="text-center">
                  <div className="text-5xl mb-4">🚗</div>
                  <p className="text-lg font-medium mb-2 text-canvas-text">Add or activate a saved DBC to start</p>
                  <p className="text-sm">Your saved files and favorites remain available after restarts.</p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Bus Monitor */}
        {tab === 'monitor' && (
          <div className="h-full">
            <BusMonitor frames={frames} connected={wsConnected} onClear={clearFrames} />
          </div>
        )}

        {/* Test Runner */}
        {tab === 'tests' && (
          <div className="h-full flex flex-col gap-4 overflow-hidden">
            <div className="shrink-0">
              <AiGenerator onUseYaml={handleUseYaml} />
            </div>
            <div className="flex-1 overflow-hidden">
              <TestRunner initialYaml={testYaml} />
            </div>
          </div>
        )}

        {/* Help */}
        {tab === 'help' && (
          <div className="max-w-2xl mx-auto py-8">
            <h1 className="text-2xl font-bold text-canvas-text mb-2">
              <span className="text-canvas-green">CAN</span>vas Quick Start
            </h1>
            <p className="text-canvas-muted mb-8">
              Free, open-source replacement for Vector CANoe/CANalyzer
            </p>

            {[
              {
                step: '1', title: 'Load your DBC file',
                desc: 'Go to Signal Studio and drag & drop your .dbc database file. All signals appear as interactive controls instantly.',
              },
              {
                step: '2', title: 'Connect to CAN bus',
                desc: 'Choose Intrepid ValueCAN / neoVI for your bench and match its channel, bitrates and CAN FD settings. Virtual runs a simulation.',
              },
              {
                step: '3', title: 'Send signals',
                desc: 'Use the sliders to set physical values (km/h, %, RPM) and click Send. CANvas handles the DBC encoding automatically.',
              },
              {
                step: '4', title: 'Run automated tests',
                desc: 'Write test scenarios in YAML or use AI to generate them. Run from the Test Runner or CI/CD pipeline.',
              },
              {
                step: '5', title: 'Monitor bus traffic',
                desc: 'Watch live CAN frames with decoded signal values in the Bus Monitor tab.',
              },
            ].map(item => (
              <div key={item.step} className="flex gap-4 mb-6">
                <div className="w-8 h-8 rounded-full bg-canvas-green/15 border border-canvas-green/30
                  flex items-center justify-center text-canvas-green font-bold text-sm shrink-0">
                  {item.step}
                </div>
                <div>
                  <h3 className="font-semibold text-canvas-text mb-1">{item.title}</h3>
                  <p className="text-canvas-muted text-sm">{item.desc}</p>
                </div>
              </div>
            ))}

            <div className="mt-8 p-4 bg-canvas-surface border border-canvas-border rounded">
              <p className="text-sm text-canvas-muted">
                <span className="text-canvas-green font-mono">canvas test tests.yaml</span>
                {' '}— Run tests from CI/CD pipeline
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
