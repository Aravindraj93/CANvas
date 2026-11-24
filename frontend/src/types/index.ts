export interface DbcSignal {
  name: string
  start_bit: number
  scale?: number
  choices?: { raw_value: number; value: number; label: string }[]
  default_warning?: string | null
  length: number
  min_value: number
  max_value: number
  unit: string
  initial_value?: number
  comment?: string
}

export interface DbcMessage {
  key: string
  dbc_id?: string | null
  dbc_filename?: string | null
  is_extended_id?: boolean
  name: string
  arbitration_id: number
  arbitration_id_hex: string
  length: number
  signals: DbcSignal[]
  is_fd?: boolean
  cycle_time?: number | null
  comment?: string
}

export interface BusStatus {
  connected: boolean
  bus_type: string
  channel?: string
  bitrate?: number
  fd?: boolean
  data_bitrate?: number | null
  bitrate_switch?: boolean
  serial?: string | null
  channel_info?: string | null
  last_tx_error?: string | null
  tx_count?: number
  error?: string
}

export interface CanFrame {
  id: number
  id_hex: string
  data_hex: string
  data_bytes?: number[]
  dlc?: number
  is_extended_id?: boolean
  is_fd?: boolean
  bitrate_switch?: boolean
  direction?: 'RX' | 'TX'
  decoded?: Record<string, number>
  timestamp: number
  message_name?: string | null
}

export interface TestStep {
  action: string
  message?: string
  signal?: string
  value?: number
  signals?: Record<string, number>
  ms?: number
  description?: string
  expected?: number
  baseline?: string
}

export interface TestConfig {
  name: string
  description?: string
  bus?: string
  steps: TestStep[]
}

export interface StepResult {
  step_index: number
  action: string
  description?: string
  status: 'PASS' | 'FAIL' | 'SKIP' | 'ERROR' | 'CANCELLED'
  message?: string
  duration_ms: number
}

export interface TestResult {
  id?: string
  name: string
  status: 'PASS' | 'FAIL' | 'ERROR' | 'CANCELLED' | 'INCOMPLETE'
  reason?: string
  errors?: number
  skipped?: number
  duration_ms: number
  total_steps: number
  passed: number
  failed: number
  steps: StepResult[]
  timestamp: string
}

export interface SavedDbc {
  id: string
  filename: string
  message_count: number
  active: boolean
  created_at: number
}

export interface Favorite {
  dbc_id: string
  message_name: string
  signal_name: string
}

export interface WorkspaceState {
  programs: { id: string; name: string; created_at: number }[]
  active_program_id: string
  files: SavedDbc[]
  messages: DbcMessage[]
  message_count: number
  favorites: Favorite[]
  notice?: string | null
  restore_error?: string | null
}

export interface MessageTraffic {
  state: 'disconnected' | 'tx_error' | 'receiving' | 'stale' | 'decode_error' | 'tx_echo' | 'tx_only' | 'not_seen'
  tx_count: number
  rx_count: number
  tx_echo_count: number
  error_count: number
  last_tx_error: string | null
  rx_age_ms: number | null
  tx_age_ms: number | null
  echo_age_ms: number | null
  stale_after_ms: number
  decoded: Record<string, number>
  decode_error: string | null
}

export interface TrafficState {
  messages: Record<string, MessageTraffic>
  cyclic_messages: string[]
  errors: Record<string, string>
}

export interface Verification {
  status: 'PASS' | 'FAIL'
  reason: string
  rx_age_ms: number | null
  comparisons: { signal: string; expected: number; actual: number | null; tolerance: number; match: boolean }[]
}
