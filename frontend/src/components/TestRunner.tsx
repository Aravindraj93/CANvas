import { useState } from 'react'
import { Play, CheckCircle, XCircle, Clock, AlertTriangle } from 'lucide-react'
import { api } from '../hooks/useApi'
import type { TestResult, StepResult } from '../types'

const SAMPLE_YAML = `name: "Fuel Warning Test"
description: "Verify fuel warning activates at low fuel"
bus: virtual
steps:
  - action: send_signal
    message: BodyControl
    signal: FuelLevel
    value: 80.0
    description: "Set fuel to 80%"
  - action: wait
    ms: 300
  - action: send_signal
    message: BodyControl
    signal: FuelLevel
    value: 5.0
    description: "Drop to critical 5%"
  - action: wait
    ms: 500
  - action: assert_signal
    message: BodyControl
    signal: WarningLamp
    expected: 1.0
    description: "WarningLamp should be active"
  - action: log
    message: "Test complete"`

function StepRow({ step }: { step: StepResult }) {
  const icon = step.status === 'PASS'
    ? <CheckCircle size={14} className="text-canvas-green shrink-0" />
    : step.status === 'FAIL'
    ? <XCircle size={14} className="text-canvas-red shrink-0" />
    : <AlertTriangle size={14} className="text-canvas-amber shrink-0" />

  return (
    <div className={`flex items-start gap-3 px-4 py-2.5 border-b border-canvas-border/40 text-sm
      ${step.status === 'FAIL' ? 'bg-red-900/10' : ''}`}>
      {icon}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="can-data text-canvas-blue text-xs">{step.action}</span>
          <span className="text-canvas-muted text-xs truncate">{step.description}</span>
        </div>
        {step.message && (
          <p className="text-canvas-muted text-xs mt-0.5 truncate">{step.message}</p>
        )}
      </div>
      <span className="text-canvas-muted text-xs can-data shrink-0">{step.duration_ms}ms</span>
    </div>
  )
}

interface TestRunnerProps {
  initialYaml?: string | null
}

export function TestRunner({ initialYaml }: TestRunnerProps) {
  const [yaml, setYaml] = useState(initialYaml ?? SAMPLE_YAML)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<TestResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)

  const runTest = async () => {
    setRunning(true)
    setCancelling(false)
    setResult(null)
    setError(null)
    try {
      const res = await api.runTest(yaml)
      setResult(res)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const cancelTest = async () => {
    setCancelling(true)
    try { await api.cancelTest() }
    catch (e: any) { setError(e.message); setCancelling(false) }
  }

  return (
    <div className="grid grid-cols-2 gap-4 h-full">
      {/* Left: YAML Editor */}
      <div className="flex flex-col bg-canvas-surface border border-canvas-border rounded overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-canvas-border bg-canvas-dark/60 shrink-0">
          <span className="text-sm font-medium text-canvas-text">Test Scenario (YAML)</span>
          <label className="flex items-center gap-1.5 text-xs text-canvas-blue cursor-pointer hover:text-canvas-green transition-colors">
            <input type="file" accept=".yaml,.yml" className="hidden" onChange={e => {
              const f = e.target.files?.[0]
              if (!f) return
              f.text().then(setYaml)
            }} />
            Load file
          </label>
        </div>
        <textarea
          value={yaml}
          onChange={e => setYaml(e.target.value)}
          className="flex-1 p-4 bg-canvas-dark text-canvas-text can-data text-xs
            resize-none outline-none focus:bg-canvas-surface2 transition-colors leading-relaxed"
          spellCheck={false}
        />
        <div className="px-4 py-3 border-t border-canvas-border shrink-0">
          <button
            onClick={runTest}
            disabled={running}
            className="w-full flex items-center justify-center gap-2 py-2.5 bg-canvas-green/15
              border border-canvas-green/40 text-canvas-green rounded font-medium text-sm
              hover:bg-canvas-green/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {running
              ? <><div className="w-4 h-4 border-2 border-canvas-green border-t-transparent rounded-full animate-spin" />Running…</>
              : <><Play size={14} />Run Test</>
            }
          </button>
          {running && <button onClick={cancelTest} disabled={cancelling}
            className="w-full mt-2 py-2 border border-canvas-amber text-canvas-amber rounded disabled:opacity-50">
            {cancelling ? 'Cancellation requested…' : 'Cancel test'}
          </button>}
        </div>
      </div>

      {/* Right: Results */}
      <div className="flex flex-col bg-canvas-surface border border-canvas-border rounded overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-canvas-border bg-canvas-dark/60 shrink-0">
          <span className="text-sm font-medium text-canvas-text">Results</span>
          {result && (
            <span className={`ml-auto text-xs font-bold px-2.5 py-0.5 rounded border
              ${result.status === 'PASS'
                ? 'text-canvas-green border-canvas-green/40 bg-canvas-green/10'
                : result.status === 'INCOMPLETE' || result.status === 'CANCELLED'
                ? 'text-canvas-amber border-canvas-amber/40 bg-canvas-amber/10'
                : 'text-canvas-red border-canvas-red/40 bg-canvas-red/10'
              }`}>
              {result.status}
            </span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto">
          {!result && !error && !running && (
            <div className="flex flex-col items-center justify-center h-full text-canvas-muted gap-3">
              <Play size={32} className="opacity-30" />
              <p className="text-sm">Run a test to see results</p>
            </div>
          )}

          {running && (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <div className="w-8 h-8 border-2 border-canvas-green border-t-transparent rounded-full animate-spin" />
              <p className="text-sm text-canvas-muted">Executing test scenario…</p>
            </div>
          )}

          {error && (
            <div className="p-4">
              <div className="bg-red-900/20 border border-canvas-red/30 rounded p-4 text-canvas-red text-sm">
                {error}
              </div>
            </div>
          )}

          {result && (
            <>
              {result.reason && <p className="p-4 text-sm text-canvas-amber">{result.reason}</p>}
              {/* Summary bar */}
              <div className="grid grid-cols-3 gap-4 p-4 border-b border-canvas-border">
                {[
                  { label: 'Passed', value: result.passed, color: 'canvas-green' },
                  { label: 'Failed', value: result.failed, color: result.failed > 0 ? 'canvas-red' : 'canvas-muted' },
                  { label: 'Duration', value: `${result.duration_ms}ms`, color: 'canvas-blue' },
                ].map(stat => (
                  <div key={stat.label} className="text-center bg-canvas-dark/60 rounded p-3">
                    <div className={`text-xl font-bold text-${stat.color}`}>{stat.value}</div>
                    <div className="text-xs text-canvas-muted mt-0.5">{stat.label}</div>
                  </div>
                ))}
              </div>

              {/* Step results */}
              <div className="divide-y divide-canvas-border/40">
                {result.steps.map(step => <StepRow key={step.step_index} step={step} />)}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
