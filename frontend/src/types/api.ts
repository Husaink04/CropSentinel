/**
 * Shared domain types for the CropSentinel frontend.
 *
 * This file is imported by new .tsx pages only — .jsx pages ignore it.
 * Keep shapes aligned with `backend/database.py` and the FastAPI response models.
 * When the backend changes a shape, update both places in the same PR.
 */

export type Role = 'admin' | 'manager' | 'viewer' | 'remote_operator'

export interface User {
  username:     string
  role:         Role
  display_name: string
  tenant_id:    number
}

export interface Machine {
  machine_id:        string
  hostname:          string
  os:                string
  online:            boolean
  last_seen:         string | null
  ip_address?:       string
  geo_country?:      string
  geo_country_code?: string
  geo_city?:         string
  geo_isp?:          string
}

export type AlertSeverity = 'low' | 'medium' | 'high' | 'critical'

export interface AlertRule {
  id:          number
  name:        string
  description: string
  rule_type:   string
  condition:   string
  threshold:   string | number
  machine_id:  string
  severity:    AlertSeverity
  enabled:     0 | 1
}

export interface AlertLog {
  id:           number
  rule_id:      number
  machine_id:   string
  hostname:     string
  message:      string
  severity:     AlertSeverity
  acknowledged: 0 | 1
  created_at:   string
}

export type WsStatus = 'connecting' | 'connected' | 'reconnecting' | 'disconnected'

/** Discriminated union of WebSocket message types emitted by the backend. */
export type WsMessage =
  | { type: 'online_machines'; machines: { machine_id: string }[] }
  | { type: 'machine_online';  machine_id: string; hostname?: string; online_count?: number }
  | { type: 'machine_offline'; machine_id: string; hostname?: string; online_count?: number }
  | { type: 'machine_unstable'; machine_id: string; hostname?: string }
  | { type: 'new_alert';       message?: string; severity?: AlertSeverity; machine_id?: string }
  | { type: 'file_update';     machine_id: string }
  | { type: 'network_update';  machine_id: string }
  | { type: 'dlp_update';      data: unknown }
  | { type: 'app_update';      machine_id: string; app_name?: string }
  | { type: 'browser_update';  machine_id: string; domain?: string }
  | { type: string; [key: string]: unknown }   // escape hatch for unknown types
