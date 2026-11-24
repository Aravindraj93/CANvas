import { useState } from 'react'
import { Sparkles, Copy, ArrowRight } from 'lucide-react'
import { api } from '../hooks/useApi'

const EXAMPLE_PROMPTS = [
  'Test fuel warning at 5%',
  'Simulate highway driving at 120 km/h',
  'Test door lock signal sequence',
  'Verify ADAS collision warning activates',
  'Test climate AC activation',
]

interface Props {
  onUseYaml: (yaml: string) => void
}

export function AiGenerator({ onUseYaml }: Props) {
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [yaml, setYaml] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const generate = async (text: string) => {
    setLoading(true)
    setYaml(null)
    setError(null)
    try {
      const res = await api.generateTest(text)
      setYaml(res.yaml)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="bg-canvas-surface border border-canvas-border rounded overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-canvas-border bg-canvas-dark/60">
          <Sparkles size={14} className="text-canvas-amber" />
          <span className="text-sm font-medium text-canvas-text">AI Test Generator</span>
          <span className="text-xs text-canvas-muted ml-auto">Powered by Gemini</span>
        </div>

        <div className="p-4 flex flex-col gap-3">
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            placeholder="Describe what you want to test in plain English…&#10;e.g. 'Test the fuel warning when fuel drops below 10%'"
            className="w-full h-24 bg-canvas-dark border border-canvas-border rounded p-3
              text-canvas-text text-sm resize-none outline-none focus:border-canvas-amber
              placeholder:text-canvas-muted transition-colors"
          />

          <div className="flex flex-wrap gap-2">
            {EXAMPLE_PROMPTS.map(p => (
              <button
                key={p}
                onClick={() => setPrompt(p)}
                className="text-xs px-2.5 py-1 rounded border border-canvas-border text-canvas-muted
                  hover:border-canvas-amber hover:text-canvas-amber transition-colors"
              >
                {p}
              </button>
            ))}
          </div>

          <button
            onClick={() => generate(prompt)}
            disabled={loading || !prompt.trim()}
            className="flex items-center justify-center gap-2 py-2 bg-canvas-amber/10 border
              border-canvas-amber/40 text-canvas-amber rounded text-sm font-medium
              hover:bg-canvas-amber/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading
              ? <><div className="w-4 h-4 border-2 border-canvas-amber border-t-transparent rounded-full animate-spin" />Generating…</>
              : <><Sparkles size={14}/>Generate Test</>
            }
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/20 border border-canvas-red/30 rounded p-3 text-canvas-red text-sm">
          {error}
        </div>
      )}

      {yaml && (
        <div className="bg-canvas-surface border border-canvas-border rounded overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-canvas-border bg-canvas-dark/60">
            <span className="text-sm text-canvas-text">Generated Test YAML</span>
            <div className="flex gap-2">
              <button
                onClick={() => navigator.clipboard.writeText(yaml)}
                className="flex items-center gap-1 text-xs text-canvas-muted hover:text-canvas-text transition-colors"
              >
                <Copy size={11}/> Copy
              </button>
              <button
                onClick={() => onUseYaml(yaml)}
                className="flex items-center gap-1 text-xs text-canvas-green hover:text-canvas-green/80 transition-colors"
              >
                <ArrowRight size={11}/> Use in Test Runner
              </button>
            </div>
          </div>
          <pre className="p-4 text-xs can-data text-canvas-text overflow-x-auto leading-relaxed
            max-h-64 overflow-y-auto">{yaml}</pre>
        </div>
      )}
    </div>
  )
}
