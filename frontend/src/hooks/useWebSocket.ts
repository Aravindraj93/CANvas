import { useEffect, useRef, useState, useCallback } from 'react'
import type { CanFrame } from '../types'

const WS_URL = import.meta.env.DEV ? 'ws://localhost:8765/ws/bus' : `ws://${window.location.host}/ws/bus`
const MAX_FRAMES = 500

export function useWebSocket() {
  const [frames, setFrames] = useState<CanFrame[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => setConnected(true)

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'keepalive' || data.type === 'pong' || data.type === 'status') return
          // It's a CAN frame
          if (data.id !== undefined) {
            setFrames(prev => {
              const next = [...prev, data as CanFrame]
              return next.length > MAX_FRAMES ? next.slice(-MAX_FRAMES) : next
            })
          }
        } catch {
          // ignore parse errors
        }
      }

      ws.onclose = () => {
        setConnected(false)
        reconnectRef.current = setTimeout(connect, 2500)
      }

      ws.onerror = () => ws.close()
    } catch {
      reconnectRef.current = setTimeout(connect, 2500)
    }
  }, [])

  useEffect(() => {
    connect()
    const ping = setInterval(() => wsRef.current?.readyState === WebSocket.OPEN && wsRef.current.send('ping'), 25000)
    return () => {
      clearInterval(ping)
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const clear = useCallback(() => setFrames([]), [])

  return { frames, connected, clear }
}
