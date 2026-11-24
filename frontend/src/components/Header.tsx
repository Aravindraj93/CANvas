import { Github, Wifi, WifiOff } from 'lucide-react'
import type { BusStatus } from '../types'

type Tab = 'studio' | 'monitor' | 'tests' | 'help'

interface Props {
  activeTab: Tab
  onTabChange: (t: Tab) => void
  busStatus: BusStatus
  wsConnected: boolean
}

const TABS: { id: Tab; label: string }[] = [
  { id: 'studio', label: '📂 Signal Studio' },
  { id: 'monitor', label: '📡 Bus Monitor' },
  { id: 'tests', label: '🧪 Test Runner' },
  { id: 'help', label: '📖 Help' },
]

export function Header({ activeTab, onTabChange, busStatus, wsConnected }: Props) {
  return (
    <header className="bg-canvas-dark border-b border-canvas-border shrink-0">
      <div className="flex items-center gap-4 px-4 h-12">
        {/* Logo */}
        <div className="text-xl font-black tracking-tight select-none">
          <span className="text-canvas-green">CAN</span>
          <span className="text-canvas-text">vas</span>
          <span className="text-canvas-muted text-xs font-normal ml-2">v0.2.0</span>
        </div>

        {/* Tabs */}
        <nav className="flex gap-1 ml-2">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`px-3 py-1.5 rounded text-sm transition-colors
                ${activeTab === tab.id
                  ? 'bg-canvas-surface text-canvas-text border border-canvas-border'
                  : 'text-canvas-muted hover:text-canvas-text'
                }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Status + GitHub */}
        <div className="ml-auto flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs">
            {busStatus.connected
              ? <Wifi size={13} className="text-canvas-green"/>
              : <WifiOff size={13} className="text-canvas-muted"/>
            }
            <span className={busStatus.connected ? 'text-canvas-green' : 'text-canvas-muted'}>
              {busStatus.connected ? busStatus.bus_type : 'No bus'}
            </span>
          </div>

          <div className="w-px h-4 bg-canvas-border"/>

          <div className="flex items-center gap-1 text-xs text-canvas-muted">
            <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-canvas-green' : 'bg-canvas-red'}`}/>
            WS
          </div>

          <a
            href="https://github.com/your-username/canvas"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 text-xs text-canvas-muted hover:text-canvas-text
              border border-canvas-border hover:border-canvas-green rounded px-2.5 py-1 transition-colors"
          >
            <Github size={12}/> ⭐ Star
          </a>
        </div>
      </div>
    </header>
  )
}
