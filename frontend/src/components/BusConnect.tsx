import { useEffect, useState } from 'react'
import { Wifi, WifiOff, Loader2 } from 'lucide-react'
import { api } from '../hooks/useApi'
import type { BusStatus } from '../types'

interface Props {
  status: BusStatus
  onStatusChange: (s: BusStatus) => void
}

const BUS_TYPES = [
  { value: 'neovi', label: 'Intrepid ValueCAN / neoVI', needsChannel: true, placeholder: 'HSCAN (CAN1)' },
  { value: 'virtual', label: 'Virtual (simulation)', needsChannel: false },
  { value: 'socketcan', label: 'SocketCAN (Linux)', needsChannel: true, placeholder: 'can0' },
  { value: 'pcan', label: 'PEAK PCAN-USB', needsChannel: true, placeholder: 'PCAN_USBBUS1' },
  { value: 'kvaser', label: 'Kvaser', needsChannel: true, placeholder: '0' },
  { value: 'serial', label: 'Serial', needsChannel: true, placeholder: 'COM3 or /dev/ttyUSB0' },
]
const inputClass = 'bg-canvas-dark border border-canvas-border rounded px-2.5 py-1.5 text-sm text-canvas-text outline-none focus:border-canvas-green'

export function BusConnect({ status, onStatusChange }: Props) {
  const [busType, setBusType] = useState('neovi')
  const [channel, setChannel] = useState('')
  const [bitrate, setBitrate] = useState('500000')
  const [fd, setFd] = useState(false)
  const [dataBitrate, setDataBitrate] = useState('2000000')
  const [brs, setBrs] = useState(false)
  const [serial, setSerial] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!status.connected) return
    setBusType(status.bus_type)
    setChannel(status.channel ?? '')
    setBitrate(String(status.bitrate ?? 500000))
    setFd(status.fd ?? false)
    setDataBitrate(String(status.data_bitrate ?? 2000000))
    setBrs(status.bitrate_switch ?? false)
    setSerial(status.serial ?? '')
  }, [status.connected, status.bus_type, status.channel, status.bitrate, status.fd, status.data_bitrate, status.bitrate_switch, status.serial])

  const selected = BUS_TYPES.find(b => b.value === busType) ?? BUS_TYPES[0]
  const supportsFd = ['neovi', 'virtual', 'socketcan'].includes(busType)
  const simulation = status.connected && status.bus_type === 'virtual'

  const connect = async () => {
    setLoading(true)
    setError(null)
    try {
      const s = await api.busConnect(busType, selected.needsChannel ? channel.trim() || undefined : undefined, Number(bitrate), {
        fd, data_bitrate: fd ? Number(dataBitrate) : undefined,
        bitrate_switch: fd && brs, serial: busType === 'neovi' ? serial.trim() || undefined : undefined,
      })
      onStatusChange(s)
    } catch (e: any) {
      setError(e.message)
      const current = await api.busStatus().catch(() => null)
      if (current) onStatusChange(current)
    } finally {
      setLoading(false)
    }
  }

  const disconnect = async () => {
    setLoading(true)
    setError(null)
    try {
      await api.busDisconnect()
      onStatusChange({ connected: false, bus_type: busType })
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-canvas-surface border border-canvas-border rounded p-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className={`flex items-center gap-2 text-sm font-medium ${simulation ? 'text-canvas-amber' : status.connected ? 'text-canvas-green' : 'text-canvas-muted'}`}>
          {status.connected ? <Wifi size={16} /> : <WifiOff size={16} />}
          <span>{status.connected
            ? `${simulation ? 'Simulation' : 'Connected'}: ${status.bus_type}${status.channel ? ` (${status.channel})` : ''}${status.fd ? ' · CAN FD' : ''}`
            : 'Not connected'}</span>
        </div>
        {status.connected && (
          <button onClick={disconnect} disabled={loading} className="ml-auto flex items-center gap-1.5 px-3 py-1.5 border border-canvas-border text-canvas-muted rounded text-sm hover:text-canvas-red disabled:opacity-50">
            <WifiOff size={13} /> Disconnect
          </button>
        )}
      </div>

      {!status.connected && (
        <fieldset disabled={loading} className="flex items-end gap-3 flex-wrap mt-3 disabled:opacity-50">
          <label className="text-xs text-canvas-muted flex flex-col gap-1">Interface
            <select value={busType} onChange={e => { setBusType(e.target.value); setChannel(''); setFd(false); setBrs(false); setError(null) }} className={inputClass}>
              {BUS_TYPES.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
            </select>
          </label>
          {selected.needsChannel && (
            <label className="text-xs text-canvas-muted flex flex-col gap-1">Channel
              <input value={channel} onChange={e => setChannel(e.target.value)} placeholder={selected.placeholder} className={`${inputClass} w-40`} />
            </label>
          )}
          <label className="text-xs text-canvas-muted flex flex-col gap-1">Nominal bitrate (bit/s)
            <input type="number" min="1" value={bitrate} onChange={e => setBitrate(e.target.value)} className={`${inputClass} w-36`} />
          </label>
          {busType === 'neovi' && (
            <label className="text-xs text-canvas-muted flex flex-col gap-1">Device serial (optional)
              <input value={serial} onChange={e => setSerial(e.target.value)} placeholder="First available device" className={`${inputClass} w-44`} />
            </label>
          )}
          {supportsFd && (
            <label className="flex items-center gap-2 text-sm text-canvas-text py-1.5">
              <input type="checkbox" checked={fd} onChange={e => { setFd(e.target.checked); if (!e.target.checked) setBrs(false) }} /> CAN FD
            </label>
          )}
          {supportsFd && fd && <>
            <label className="text-xs text-canvas-muted flex flex-col gap-1">FD data bitrate (bit/s)
              <input type="number" min="1" value={dataBitrate} onChange={e => setDataBitrate(e.target.value)} className={`${inputClass} w-36`} />
            </label>
            <label className="flex items-center gap-2 text-sm text-canvas-text py-1.5">
              <input type="checkbox" checked={brs} onChange={e => setBrs(e.target.checked)} /> Bitrate switching (BRS)
            </label>
          </>}
          <button onClick={connect} disabled={loading || Number(bitrate) <= 0 || (fd && Number(dataBitrate) <= 0)} className="flex items-center gap-1.5 px-3 py-1.5 bg-canvas-green/15 border border-canvas-green/40 text-canvas-green rounded text-sm disabled:opacity-50">
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Wifi size={13} />} Connect
          </button>
        </fieldset>
      )}
      {simulation && <p className="mt-2 text-canvas-amber text-xs">Simulation only — frames stay inside CANvas. Disconnect and select Intrepid ValueCAN / neoVI to use your bench.</p>}
      {!status.connected && busType === 'neovi' && <p className="mt-2 text-canvas-muted text-xs">Use the ICS network name: HSCAN for CAN1. Verify CAN2's network name in Intrepid settings. Match both bitrates and BRS to the bench.</p>}
      {status.connected && !simulation && <p className="mt-2 text-canvas-muted text-xs">{status.channel_info} · {status.bitrate} bit/s{status.fd ? ` · data ${status.data_bitrate} bit/s · BRS ${status.bitrate_switch ? 'on' : 'off'}` : ''} · {status.tx_count ?? 0} sends accepted</p>}
      {(error || status.last_tx_error) && <p role="alert" className="mt-2 text-canvas-red text-xs">{error || status.last_tx_error}</p>}
    </div>
  )
}
