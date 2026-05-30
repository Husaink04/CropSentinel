import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useApi, useWsListener } from '../hooks/useAuth'
import { PageStateView } from '../components/ui/PageState'
import { usePageContext } from '../hooks/usePageContext'
import { ActivityDrawer } from '../features/activity/activityUi'
import { ChoiceGrid, SimpleBadge, SimpleKeyValue, SimpleSection } from '../features/security/simpleUi'
import { AlertsIcon, DlpIcon, FileIcon, ReportsIcon, UsersIcon } from '../components/ui/OverviewIcons'

const WORKSPACE_TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'policies', label: 'Policies' },
  { id: 'alerts', label: 'Alerts' },
  { id: 'users', label: 'Users at Risk' },
]

const PROTECTION_LEVELS = [
  {
    value: 'monitor_only',
    label: 'Monitor only',
    description: 'Watch risky activity quietly and keep a record for review.',
  },
  {
    value: 'soft_block',
    label: 'Warn user',
    description: 'Show a warning and stop risky actions only when the policy says it should.',
  },
  {
    value: 'hard_block',
    label: 'Block automatically',
    description: 'Stop high-risk actions right away and ask reviewers to follow up.',
  },
]

const POLICY_TARGETS = [
  { id: 'personal_data', label: 'Personal data', desc: 'Names, IDs, addresses, and related private details.' },
  { id: 'financial_data', label: 'Financial data', desc: 'Payroll, invoices, card details, and account records.' },
  { id: 'customer_records', label: 'Customer records', desc: 'Client lists, account exports, and CRM-related files.' },
  { id: 'passwords_keys', label: 'Passwords and keys', desc: 'Credentials, tokens, private keys, and secrets.' },
  { id: 'sensitive_files', label: 'Sensitive files', desc: 'Protected folders or file types already marked as sensitive.' },
  { id: 'print_clipboard', label: 'Clipboard and print', desc: 'Copy, paste, and print actions that may leak data.' },
]

const POLICY_LOCATIONS = [
  { id: 'email', label: 'Email upload' },
  { id: 'cloud_uploads', label: 'Cloud upload' },
  { id: 'usb_devices', label: 'USB drive' },
  { id: 'local_move', label: 'Local file move' },
  { id: 'clipboard', label: 'Clipboard' },
  { id: 'print', label: 'Print' },
]

const POLICY_AUDIENCES = [
  { id: 'everyone', label: 'Everyone' },
  { id: 'selected_teams', label: 'Selected teams' },
  { id: 'selected_users', label: 'Selected users' },
  { id: 'selected_devices', label: 'Selected devices' },
]

const BASE_POLICY_TARGETS = ['sensitive_files', 'passwords_keys', 'personal_data', 'financial_data']
const INCIDENT_STATES = ['new', 'investigating', 'contained', 'approved_business_use', 'false_positive', 'escalated', 'closed']
const INCIDENT_DISPOSITIONS = [
  { value: '', label: 'No disposition yet' },
  { value: 'contained', label: 'Contained' },
  { value: 'approved_business_use', label: 'Approved business use' },
  { value: 'false_positive', label: 'False positive' },
  { value: 'escalated', label: 'Escalated' },
  { value: 'closed', label: 'Closed' },
]

const RISK_WEIGHT = { low: 1, medium: 2, high: 3, critical: 4 }
const RISK_LABELS = { 1: 'Low', 2: 'Medium', 3: 'High', 4: 'Critical' }
const RISK_STATUS = [
  { min: 10, label: 'Urgent', tone: 'danger' },
  { min: 6, label: 'High attention', tone: 'warning' },
  { min: 3, label: 'Needs review', tone: 'info' },
  { min: 0, label: 'Low attention', tone: 'success' },
]

function formatDateTime(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return String(value)
  }
}

function formatShortDate(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleDateString([], { month: 'short', day: 'numeric' })
  } catch {
    return String(value)
  }
}

function toDateInput(value) {
  if (!value) return ''
  try {
    return new Date(value).toISOString().slice(0, 10)
  } catch {
    return ''
  }
}

function safeArray(value) {
  return Array.isArray(value) ? value : []
}

function safeObject(value) {
  if (!value) return {}
  if (typeof value === 'object' && !Array.isArray(value)) return value
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function metadataValue(item, key, fallback = '') {
  if (item?.[key] !== undefined && item?.[key] !== null && item?.[key] !== '') return item[key]
  const metadata = safeObject(item?.metadata)
  if (metadata[key] !== undefined && metadata[key] !== null && metadata[key] !== '') return metadata[key]
  return fallback
}

function machineLookup(machines, machineId) {
  return machines.find((item) => item.machine_id === machineId) || null
}

function resolveUserLabel(item, machines) {
  const machine = machineLookup(machines, item.machine_id)
  return item.actor_username || item.username || item.user_name || machine?.username || machine?.hostname || item.machine_name || item.hostname || 'Unknown user'
}

function resolveMachineLabel(item, machines) {
  const machine = machineLookup(machines, item.machine_id)
  return item.machine_name || item.hostname || machine?.hostname || item.machine_id || '-'
}

function riskTone(level) {
  return level === 'critical' || level === 'high' ? 'danger' : level === 'medium' ? 'warning' : 'success'
}

function policyActionLabel(item) {
  const actionTaken = String(metadataValue(item, 'action_taken', item.action_taken || '')).toLowerCase()
  const actionResult = String(metadataValue(item, 'action_result', item.result || '')).toLowerCase()
  const exceptionApplied = metadataValue(item, 'exception_applied', item.exception_applied || null)
  const hasException = Boolean(
    actionResult === 'exception_applied'
    || (exceptionApplied && (typeof exceptionApplied !== 'object' || Object.keys(exceptionApplied).length))
  )
  if (hasException) return 'Allowed by exception'
  if (actionResult === 'blocked' || actionTaken === 'block_transfer') return 'Blocked automatically'
  if (actionResult === 'warning_shown' || actionTaken === 'warn_user' || item.warning_shown) return 'Allowed with warning'
  if (actionResult === 'observed' || actionTaken === 'monitor') return 'Logged for review'
  if (actionResult === 'block_failed') return 'Block attempted'
  return 'Needs review'
}

function policyActionTone(label) {
  if (label === 'Blocked automatically' || label === 'Block attempted') return 'danger'
  if (label === 'Allowed with warning') return 'warning'
  if (label === 'Allowed by exception' || label === 'Logged for review') return 'success'
  return 'warning'
}

function plainActivityLabel(item) {
  const destination = String(item.destination_label || item.destination || item.destination_type || '').toLowerCase()
  if (destination.includes('usb')) return 'Copied to USB'
  if (destination.includes('cloud')) return 'Uploaded to cloud'
  if (destination.includes('print')) return 'Printed document'
  if (destination.includes('clipboard')) return 'Copied through clipboard'
  if (destination.includes('email')) return 'Attached to email'
  if (destination.includes('local')) return 'Moved outside protected folder'
  return 'Sensitive file activity'
}

function sensitivityType(item) {
  if (item.enterprise_label) return item.enterprise_label
  const findings = safeArray(item.findings)
  return findings[0]?.type ? String(findings[0].type).replace(/_/g, ' ') : 'Sensitive data'
}

function baselineStatusFromInventory(statusPayload) {
  const totals = statusPayload?.totals || {}
  const totalFiles = Number(totals.total_files || 0)
  const inspectedFiles = Number(totals.inspected_files || 0)
  if (!totalFiles && !inspectedFiles) return { label: 'Not started', progress: 0, tone: 'default' }
  if (inspectedFiles < totalFiles) return { label: 'Scanning', progress: totalFiles ? Math.round((inspectedFiles / totalFiles) * 100) : 35, tone: 'info' }
  const pending = safeArray(statusPayload?.sync_status).reduce((sum, row) => sum + Number(row.pending_upload_count || 0), 0)
  if (pending > 0) return { label: 'Review needed', progress: 100, tone: 'warning' }
  return { label: 'Complete', progress: 100, tone: 'success' }
}

function kpiCard(label, value, sub, tone = 'var(--brand)') {
  return { label, value, sub, tone }
}

function DetailValue({ label, children }) {
  return (
    <div style={{ display: 'grid', gap: 4 }}>
      <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em' }}>{label}</span>
      <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>{children}</div>
    </div>
  )
}

export default function DLPEvents() {
  const { get, post, put } = useApi()
  const { setPageContext, clearPageContext } = usePageContext()

  const [workspaceTab, setWorkspaceTab] = useState('overview')
  const [timelineRange, setTimelineRange] = useState('7d')
  const [selectedAlert, setSelectedAlert] = useState(null)
  const [incidentDetail, setIncidentDetail] = useState(null)
  const [incidentLoading, setIncidentLoading] = useState(false)
  const [incidentSaving, setIncidentSaving] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyResults, setHistoryResults] = useState([])
  const [selectedUser, setSelectedUser] = useState(null)
  const [selectedUserDetail, setSelectedUserDetail] = useState(null)
  const [userRiskLoading, setUserRiskLoading] = useState(false)
  const [userDetailLoading, setUserDetailLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [partialError, setPartialError] = useState('')
  const [policy, setPolicy] = useState(null)
  const [policies, setPolicies] = useState([])
  const [exceptions, setExceptions] = useState([])
  const [incidents, setIncidents] = useState([])
  const [events, setEvents] = useState([])
  const [machines, setMachines] = useState([])
  const [stats, setStats] = useState(null)
  const [riskProfiles, setRiskProfiles] = useState([])
  const [inventoryByMachine, setInventoryByMachine] = useState({})
  const [saving, setSaving] = useState(false)
  const [busyAction, setBusyAction] = useState('')
  const [toast, setToast] = useState(null)

  const [selectedLevel, setSelectedLevel] = useState('soft_block')
  const [selectedTargets, setSelectedTargets] = useState(BASE_POLICY_TARGETS)
  const [wizardStep, setWizardStep] = useState(1)
  const [selectedLocations, setSelectedLocations] = useState(['usb_devices', 'cloud_uploads'])
  const [selectedAudience, setSelectedAudience] = useState('everyone')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [policyName, setPolicyName] = useState('Sensitive Data Protection')
  const [policyDescription, setPolicyDescription] = useState('')

  const [alertFilters, setAlertFilters] = useState({
    severity: '',
    status: '',
    user: '',
    policy: '',
    date: '',
  })
  const [detailForm, setDetailForm] = useState({
    state: 'new',
    severity: 'medium',
    assignee: '',
    disposition: '',
    resolution_reason: '',
    note: '',
  })
  const [historyFilters, setHistoryFilters] = useState({
    actor_username: '',
    machine_id: '',
    file_hash: '',
    content_fingerprint: '',
    destination_type: '',
    disposition: '',
    date_from: '',
    date_to: '',
  })
  const [userRiskFilters, setUserRiskFilters] = useState({
    window_days: '90',
    min_risk_level: '',
    trend: '',
    machine_id: '',
    destination_type: '',
  })

  const notify = useCallback((msg, type = 'green') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3200)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    setPartialError('')
    try {
      const [policyRes, policiesRes, exceptionsRes, incidentsRes, eventsRes, statsRes, machinesRes, riskRes] = await Promise.allSettled([
        get('/api/dlp/policy/effective'),
        get('/api/dlp/policies'),
        get('/api/dlp/exceptions'),
        get('/api/dlp/incidents?limit=80'),
        get('/api/dlp/events?limit=250'),
        get('/api/dlp/stats'),
        get('/api/machines'),
        get('/api/dlp/risk/users?window_days=90&limit=50'),
      ])

      const failures = []
      let successCount = 0
      let machineRows = []
      let incidentRows = []
      let eventRows = []

      if (policyRes.status === 'fulfilled') {
        successCount += 1
        setPolicy(policyRes.value || {})
        setSelectedLevel(policyRes.value?.rollout_mode || 'soft_block')
        const targets = policyRes.value?.config?.simple_targets?.length ? policyRes.value.config.simple_targets : BASE_POLICY_TARGETS
        setSelectedTargets(targets)
        setPolicyName(policyRes.value?.name || 'Sensitive Data Protection')
        setPolicyDescription(policyRes.value?.description || '')
      } else {
        failures.push('policy')
      }

      if (policiesRes.status === 'fulfilled') {
        successCount += 1
        const rows = policiesRes.value?.policies || []
        setPolicies(rows)
      } else {
        setPolicies([])
        failures.push('policy list')
      }

      if (exceptionsRes.status === 'fulfilled') {
        successCount += 1
        setExceptions(exceptionsRes.value?.exceptions || [])
      } else {
        setExceptions([])
        failures.push('exceptions')
      }

      if (incidentsRes.status === 'fulfilled') {
        successCount += 1
        incidentRows = incidentsRes.value?.items || []
        setIncidents(incidentRows)
      } else {
        setIncidents([])
        failures.push('incidents')
      }

      if (eventsRes.status === 'fulfilled') {
        successCount += 1
        eventRows = eventsRes.value?.events || []
        setEvents(eventRows)
      } else {
        setEvents([])
        failures.push('events')
      }

      if (statsRes.status === 'fulfilled') {
        setStats(statsRes.value || null)
      } else {
        setStats(null)
        failures.push('stats')
      }

      if (machinesRes.status === 'fulfilled') {
        machineRows = machinesRes.value || []
        setMachines(machineRows)
      } else {
        setMachines([])
        failures.push('machines')
      }

      if (riskRes.status === 'fulfilled') {
        setRiskProfiles(riskRes.value?.items || [])
      } else {
        setRiskProfiles([])
        failures.push('user risk')
      }

      const machineIds = Array.from(new Set([
        ...incidentRows.map((item) => item.machine_id).filter(Boolean),
        ...eventRows.map((item) => item.machine_id).filter(Boolean),
      ])).slice(0, 12)

      if (machineIds.length) {
        const inventoryResults = await Promise.allSettled(
          machineIds.map((machineId) => get(`/api/dlp/file-inventory/status/${machineId}`)),
        )
        const nextInventory = {}
        inventoryResults.forEach((result, index) => {
          if (result.status === 'fulfilled') nextInventory[machineIds[index]] = result.value
        })
        setInventoryByMachine(nextInventory)
      } else {
        setInventoryByMachine({})
      }

      if (!successCount) throw new Error('Failed to load DLP')
      if (failures.length) setPartialError(`Some DLP data could not load: ${failures.join(', ')}`)
    } catch (err) {
      setError(err?.message || 'Failed to load DLP')
    } finally {
      setLoading(false)
    }
  }, [get])

  useEffect(() => { load() }, [load])

  const loadUserRiskProfiles = useCallback(async (filters = userRiskFilters) => {
    setUserRiskLoading(true)
    try {
      const params = new URLSearchParams({ limit: '50' })
      Object.entries(filters || {}).forEach(([key, value]) => {
        if (value) params.set(key, value)
      })
      const response = await get(`/api/dlp/risk/users?${params.toString()}`)
      setRiskProfiles(response?.items || [])
    } catch (err) {
      notify(err?.message || 'Unable to load user risk profiles', 'red')
    } finally {
      setUserRiskLoading(false)
    }
  }, [get, notify, userRiskFilters])

  const loadUserRiskDetail = useCallback(async (item, filters = userRiskFilters) => {
    const actor = item?.actor_username || item?.userLabel
    if (!actor) return
    setSelectedUser(item)
    setSelectedUserDetail(null)
    setUserDetailLoading(true)
    try {
      const params = new URLSearchParams()
      Object.entries(filters || {}).forEach(([key, value]) => {
        if (value) params.set(key, value)
      })
      const detail = await get(`/api/dlp/risk/users/${encodeURIComponent(actor)}${params.toString() ? `?${params.toString()}` : ''}`)
      setSelectedUserDetail(detail)
    } catch (err) {
      notify(err?.message || 'Unable to load this user risk profile', 'red')
    } finally {
      setUserDetailLoading(false)
    }
  }, [get, notify, userRiskFilters])

  useEffect(() => {
    setPageContext('Tenant Scope', 'DLP Protection')
    return () => clearPageContext()
  }, [setPageContext, clearPageContext])

  useWsListener(useCallback((msg) => {
    if (msg.type === 'dlp_update' && msg.data) {
      setEvents((prev) => [msg.data, ...prev].slice(0, 250))
    }
    if (msg.type === 'dlp_incident_update' && msg.data) {
      setIncidents((prev) => [msg.data, ...prev.filter((item) => item.id !== msg.data.id)].slice(0, 80))
      setIncidentDetail((prev) => (prev?.id === msg.data.id ? msg.data : prev))
    }
  }, []))

  const pageState = loading ? 'loading' : error ? 'error' : partialError ? 'partial' : 'ready'
  const effectiveLevel = useMemo(() => PROTECTION_LEVELS.find((item) => item.value === selectedLevel)?.label || 'Warn user', [selectedLevel])

  const enrichedEvents = useMemo(() => events.map((item) => ({
    ...item,
    metadata: safeObject(item.metadata),
    userLabel: resolveUserLabel(item, machines),
    machineLabel: resolveMachineLabel(item, machines),
    activityLabel: plainActivityLabel(item),
    sensitivityLabel: sensitivityType(item),
    policyAction: policyActionLabel(item),
    riskKey: String(item.risk_level || item.risk || 'low').toLowerCase(),
    statusLabel: item.acknowledged ? 'Reviewed' : policyActionLabel(item),
  })), [events, machines])

  const enrichedIncidents = useMemo(() => incidents.map((item) => ({
    ...item,
    metadata: safeObject(item.metadata),
    file_path: metadataValue(item, 'file_path', item.file_path || ''),
    file_name: metadataValue(item, 'file_name', item.file_name || ''),
    destination_type: metadataValue(item, 'destination_type', item.destination_type || ''),
    destination_label: metadataValue(item, 'destination_label', item.destination_label || ''),
    actor_username: metadataValue(item, 'actor_username', item.actor_username || ''),
    enterprise_label: metadataValue(item, 'enterprise_label', item.enterprise_label || ''),
    userLabel: resolveUserLabel(item, machines),
    machineLabel: resolveMachineLabel(item, machines),
    riskKey: String(item.severity || item.risk_level || 'medium').toLowerCase(),
    policyAction: policyActionLabel(item),
    titleText: item.title || item.summary || `${plainActivityLabel(item)} blocked by policy`,
    summaryText: item.summary || `${plainActivityLabel(item)} involving ${sensitivityType(item)}.`,
    statusText: ['closed', 'approved_business_use', 'false_positive', 'contained'].includes(String(item.state || '').toLowerCase())
      ? humanizeIncidentState(item.state)
      : policyActionLabel(item),
  })), [incidents, machines])

  const now = Date.now()
  const rangeMs = timelineRange === 'today' ? 24 * 60 * 60 * 1000 : timelineRange === '30d' ? 30 * 24 * 60 * 60 * 1000 : 7 * 24 * 60 * 60 * 1000
  const filteredTimelineEvents = useMemo(() => enrichedEvents
    .filter((item) => {
      if (!item.timestamp) return false
      const time = new Date(item.timestamp).getTime()
      return now - time <= rangeMs
    })
    .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)), [enrichedEvents, now, rangeMs])

  const timelineData = useMemo(() => {
    const groups = new Map()
    filteredTimelineEvents.forEach((item) => {
      const date = new Date(item.timestamp)
      const bucket = timelineRange === 'today'
        ? `${date.getHours().toString().padStart(2, '0')}:00`
        : `${date.getMonth() + 1}/${date.getDate()}`
      const current = groups.get(bucket) || { time: bucket, riskValue: 0, label: 'Low', count: 0, sample: '' }
      const riskValue = Math.max(current.riskValue, RISK_WEIGHT[item.riskKey] || 1)
      current.riskValue = riskValue
      current.label = RISK_LABELS[riskValue]
      current.count += 1
      if (!current.sample) current.sample = `${item.activityLabel} ${item.policyAction.toLowerCase()}`
      groups.set(bucket, current)
    })
    return Array.from(groups.values())
  }, [filteredTimelineEvents, timelineRange])

  const enrichedRiskProfiles = useMemo(() => riskProfiles.map((item) => {
    const machineLabel = resolveMachineLabel({ machine_id: item.latest_machine_id }, machines)
    const baseline = baselineStatusFromInventory(item.latest_machine_id ? inventoryByMachine[item.latest_machine_id] : null)
    return {
      ...item,
      key: item.actor_username,
      userLabel: item.actor_username || '-',
      machineLabel,
      baseline,
      riskLabel: humanizeIncidentState(item.risk_level || 'low'),
      riskTone: item.risk_tone || riskTone(item.risk_level || 'low'),
      lastAction: item.recent_activity_summary || 'Recent sensitive activity',
      latestItem: {
        machine_id: item.latest_machine_id,
        destination_type: item.latest_destination_type,
        policyAction: item.blocked_event_count > 0 ? 'Blocked automatically' : item.warning_event_count > 0 ? 'Allowed with warning' : 'Monitored',
      },
    }
  }), [inventoryByMachine, machines, riskProfiles])

  const currentUserRisk = useMemo(() => {
    if (!selectedUser && !selectedUserDetail) return null
    const actor = selectedUserDetail?.actor_username || selectedUser?.actor_username || selectedUser?.userLabel
    const fallback = enrichedRiskProfiles.find((item) => item.actor_username === actor || item.userLabel === actor) || selectedUser || null
    if (!selectedUserDetail) return fallback
    const machineLabel = resolveMachineLabel({ machine_id: selectedUserDetail.latest_machine_id }, machines)
    const baseline = baselineStatusFromInventory(
      selectedUserDetail.latest_machine_id ? inventoryByMachine[selectedUserDetail.latest_machine_id] : null,
    )
    return {
      ...fallback,
      ...selectedUserDetail,
      userLabel: selectedUserDetail.actor_username || fallback?.userLabel || '-',
      machineLabel,
      baseline,
      riskLabel: humanizeIncidentState(selectedUserDetail.risk_level || fallback?.risk_level || 'low'),
      riskTone: selectedUserDetail.risk_tone || fallback?.riskTone || riskTone(selectedUserDetail.risk_level || fallback?.risk_level || 'low'),
      lastAction: selectedUserDetail.recent_activity_summary || fallback?.lastAction || 'Recent sensitive activity',
    }
  }, [enrichedRiskProfiles, inventoryByMachine, machines, selectedUser, selectedUserDetail])

  const kpis = useMemo(() => {
    const highRisk = enrichedEvents.filter((item) => (RISK_WEIGHT[item.riskKey] || 1) >= 3).length
    const violations = enrichedIncidents.length || Number(stats?.open_incidents || 0)
    const safeCount = Math.max(0, enrichedEvents.length - highRisk)
    const topUsersCount = enrichedRiskProfiles.filter((item) => item.risk_level !== 'low').length
    return [
      kpiCard('High-risk activity', highRisk, 'Blocked or flagged in the selected time window', 'var(--red)'),
      kpiCard('Policy violations', violations, 'Events that broke the current protection policy', 'var(--amber)'),
      kpiCard('Safe activity', safeCount, 'Sensitive work that completed without a risky outcome', 'var(--green)'),
      kpiCard('Users at risk', topUsersCount, 'People with repeated risky or blocked actions', 'var(--brand)'),
    ]
  }, [enrichedEvents, enrichedIncidents, enrichedRiskProfiles, stats])

  const baselineRows = useMemo(() => enrichedRiskProfiles.slice(0, 5).map((item) => ({
    userLabel: item.userLabel,
    machineLabel: item.machineLabel,
    baseline: item.baseline,
  })), [enrichedRiskProfiles])

  const previewLogRows = useMemo(() => enrichedEvents.slice(0, 8), [enrichedEvents])

  const filteredAlerts = useMemo(() => enrichedIncidents.filter((item) => {
    if (alertFilters.severity && item.riskKey !== alertFilters.severity) return false
    if (alertFilters.status && item.statusText !== alertFilters.status) return false
    if (alertFilters.user && item.userLabel !== alertFilters.user) return false
    if (alertFilters.policy && (item.policy_name || 'Current policy') !== alertFilters.policy) return false
    if (alertFilters.date) {
      const day = item.created_at || item.updated_at || item.last_seen
      if (!day || !String(day).startsWith(alertFilters.date)) return false
    }
    return true
  }), [enrichedIncidents, alertFilters])

  const userOptions = useMemo(() => Array.from(new Set(enrichedIncidents.map((item) => item.userLabel))).sort(), [enrichedIncidents])
  const policyOptions = useMemo(() => Array.from(new Set(enrichedIncidents.map((item) => item.policy_name || 'Current policy'))), [enrichedIncidents])

  const wizardSummary = useMemo(() => {
    const targetLabels = POLICY_TARGETS.filter((item) => selectedTargets.includes(item.id)).map((item) => item.label.toLowerCase())
    const locationLabels = POLICY_LOCATIONS.filter((item) => selectedLocations.includes(item.id)).map((item) => item.label.toLowerCase())
    const audienceLabel = POLICY_AUDIENCES.find((item) => item.id === selectedAudience)?.label.toLowerCase() || 'everyone'
    const outcomeLabel = PROTECTION_LEVELS.find((item) => item.value === selectedLevel)?.label.toLowerCase() || 'warn user'
    return `${outcomeLabel} if ${targetLabels.join(', ') || 'sensitive data'} is shared through ${locationLabels.join(', ') || 'selected channels'} for ${audienceLabel}.`
  }, [selectedTargets, selectedLocations, selectedAudience, selectedLevel])

  const savePolicy = async (status = 'draft') => {
    setSaving(true)
    try {
      const payload = {
        name: policyName || 'Sensitive Data Protection',
        description: policyDescription || wizardSummary,
        scope: 'tenant_override',
        mode: 'detect_then_block',
        status,
        priority: 100,
        rollout_mode: selectedLevel,
        is_baseline: false,
        is_mandatory: false,
        config: {
          simple_mode: selectedLevel,
          simple_targets: selectedTargets,
          simple_locations: selectedLocations,
          simple_audience: selectedAudience,
          simple_summary: wizardSummary,
        },
      }
      const tenantPolicy = policies.find((item) => item.scope === 'tenant_override')
      if (tenantPolicy?.id) await put(`/api/dlp/policies/${tenantPolicy.id}`, payload)
      else await post('/api/dlp/policies', payload)
      notify(status === 'published' ? 'Policy turned on' : 'Policy saved as draft')
      await load()
      setWorkspaceTab('overview')
    } catch (err) {
      notify(err?.message || 'Unable to save policy', 'red')
    } finally {
      setSaving(false)
    }
  }

  const acknowledgeEvent = async (eventId) => {
    if (!eventId) return notify('This alert does not have a linked event yet.', 'red')
    setBusyAction(eventId)
    try {
      await put(`/api/dlp/events/${eventId}/acknowledge`)
      setEvents((prev) => prev.map((item) => (item.id === eventId ? { ...item, acknowledged: true } : item)))
      notify('Marked as safe for review.')
    } catch (err) {
      notify(err?.message || 'Unable to update this alert', 'red')
    } finally {
      setBusyAction('')
    }
  }

  const buildExceptionPayload = (item, temporary = false) => {
    const metadata = safeObject(item?.metadata)
    const classifierHits = safeArray(metadata.classifier_hits || item?.classifier_hits)
    const filePath = metadata.file_path || item?.file_path || ''
    const machineId = metadata.machine_id || item?.machine_id || ''
    const actorUsername = metadata.actor_username || item?.actor_username || ''
    const destinationType = metadata.destination_type || item?.destination_type || item?.destination || ''
    const classifierName = classifierHits[0]?.name || ''
    const expiresAt = temporary ? new Date(Date.now() + 4 * 60 * 60 * 1000).toISOString() : null
    return {
      scope_type: filePath ? 'path' : actorUsername ? 'user' : 'machine',
      scope_value: filePath ? '' : actorUsername || machineId,
      classifier_name: classifierName,
      destination_type: destinationType,
      path_pattern: filePath,
      reason: temporary
        ? `Temporary business allowance created from incident ${item?.id || 'review'}`
        : `Approved DLP exception created from incident ${item?.id || 'review'}`,
      expires_at: expiresAt,
      status: 'active',
      metadata: {
        source_incident_id: item?.id || null,
        source_event_id: item?.event_id || item?.source_event_id || item?.related_event_id || null,
      },
    }
  }

  const createExceptionFromAlert = async (item, temporary = false) => {
    if (!item) return
    setBusyAction(`exception-${item.id || item.event_id || 'alert'}`)
    try {
      await post('/api/dlp/exceptions', buildExceptionPayload(item, temporary))
      notify(temporary ? 'Temporary allow-once exception created.' : 'Exception added to this policy path.')
      await load()
    } catch (err) {
      notify(err?.message || 'Unable to create this exception', 'red')
    } finally {
      setBusyAction('')
    }
  }

  const loadHistoricalIncidents = async (filters, currentIncidentId = null) => {
    setHistoryLoading(true)
    try {
      const params = new URLSearchParams({ limit: '12' })
      Object.entries(filters || {}).forEach(([key, value]) => {
        if (value) params.set(key, value)
      })
      const response = await get(`/api/dlp/incidents?${params.toString()}`)
      const rows = response?.items || []
      setHistoryResults(currentIncidentId ? rows.filter((item) => item.id !== currentIncidentId) : rows)
    } catch (err) {
      notify(err?.message || 'Unable to load historical incidents', 'red')
    } finally {
      setHistoryLoading(false)
    }
  }

  const openIncidentAlert = async (item) => {
    if (!item?.id) return
    setSelectedAlert(item)
    setIncidentLoading(true)
    setIncidentDetail(item)
    try {
      const detail = await get(`/api/dlp/incidents/${item.id}`)
      setIncidentDetail(detail)
      const nextFilters = {
        actor_username: detail?.history_filters_applied?.actor_username || detail?.actor_username || '',
        machine_id: detail?.history_filters_applied?.machine_id || detail?.machine_id || '',
        file_hash: detail?.history_filters_applied?.file_hash || detail?.file_hash || '',
        content_fingerprint: detail?.history_filters_applied?.content_fingerprint || detail?.content_fingerprint || '',
        destination_type: detail?.history_filters_applied?.destination_type || detail?.destination_type || '',
        disposition: '',
        date_from: toDateInput(detail?.history_summary?.first_seen),
        date_to: toDateInput(detail?.history_summary?.last_seen),
      }
      setHistoryFilters(nextFilters)
      setHistoryResults(detail?.historical_incidents || [])
      setDetailForm({
        state: detail?.state || 'new',
        severity: detail?.severity || item.riskKey || 'medium',
        assignee: detail?.assignee || '',
        disposition: detail?.metadata?.disposition || '',
        resolution_reason: detail?.metadata?.resolution_reason || '',
        note: '',
      })
    } catch (err) {
      notify(err?.message || 'Unable to load incident details', 'red')
    } finally {
      setIncidentLoading(false)
    }
  }

  const closeIncidentDrawer = () => {
    setSelectedAlert(null)
    setIncidentDetail(null)
    setIncidentLoading(false)
    setIncidentSaving(false)
    setHistoryLoading(false)
    setHistoryResults([])
    setDetailForm({
      state: 'new',
      severity: 'medium',
      assignee: '',
      disposition: '',
      resolution_reason: '',
      note: '',
    })
    setHistoryFilters({
      actor_username: '',
      machine_id: '',
      file_hash: '',
      content_fingerprint: '',
      destination_type: '',
      disposition: '',
      date_from: '',
      date_to: '',
    })
  }

  const saveIncidentReview = async () => {
    const incidentId = selectedAlert?.id || incidentDetail?.id
    if (!incidentId) return
    setIncidentSaving(true)
    try {
      const updated = await put(`/api/dlp/incidents/${incidentId}`, detailForm)
      setIncidentDetail(updated)
      setHistoryResults(updated?.historical_incidents || historyResults)
      setSelectedAlert((prev) => (prev ? { ...prev, ...updated } : updated))
      setIncidents((prev) => [updated, ...prev.filter((row) => row.id !== updated.id)].slice(0, 80))
      setDetailForm((prev) => ({ ...prev, note: '' }))
      notify('Incident review saved.')
    } catch (err) {
      notify(err?.message || 'Unable to save incident review', 'red')
    } finally {
      setIncidentSaving(false)
    }
  }

  const unsupportedAction = (label) => {
    notify(`${label} will be available when DLP exception actions are connected.`, 'amber')
  }

  const clearAlertFilters = () => {
    setAlertFilters({ severity: '', status: '', user: '', policy: '', date: '' })
  }

  const closeUserRiskDrawer = () => {
    setSelectedUser(null)
    setSelectedUserDetail(null)
    setUserDetailLoading(false)
  }

  return (
    <div className="fade-in analytics-shell">
      <div className="page-header machine-calm-header analytics-hero control-hero">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <DlpIcon size={24} />
          </div>
          <div>
            <div className="page-title">Data Protection</div>
            <div className="page-subtitle">See risky file activity, blocked actions, and who may need attention.</div>
          </div>
        </div>
        <div className="control-actions">
          <button className="btn btn-outline machine-calm-btn btn-sm" onClick={load}>Refresh</button>
          <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setWorkspaceTab('alerts')}>Review alerts</button>
          <button className="btn btn-primary btn-sm" onClick={() => setWorkspaceTab('policies')}>Create policy</button>
        </div>
      </div>

      <div className="tab-group analytics-tabs" style={{ marginBottom: 18, alignSelf: 'flex-start' }}>
        {WORKSPACE_TABS.map((tab) => (
          <button key={tab.id} className={`tab-btn ${workspaceTab === tab.id ? 'active' : ''}`} onClick={() => setWorkspaceTab(tab.id)}>
            {tab.label}
          </button>
        ))}
      </div>

      <PageStateView
        state={pageState}
        title={error ? 'Unable to load DLP' : partialError ? 'DLP loaded with some missing sections' : 'No DLP activity yet'}
        message={error || partialError || 'This tenant has no recent DLP events or incidents.'}
        onRetry={load}
      >
        {workspaceTab === 'overview' && (
          <div className="control-grid">
            <div className="grid-4">
              {kpis.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  className="stat-card machine-calm-card machine-calm-stat control-stat"
                  style={{ textAlign: 'left', cursor: 'pointer' }}
                  onClick={() => setWorkspaceTab(item.label === 'Users at risk' ? 'users' : item.label === 'Policy violations' ? 'alerts' : 'overview')}
                >
                  <div className="stat-label">{item.label}</div>
                  <div className="stat-value" style={{ color: item.tone }}>{item.value}</div>
                  <div className="stat-sub">{item.sub}</div>
                </button>
              ))}
            </div>

            <div className="grid-2">
              <SimpleSection
                title="Risk timeline"
                subtitle="Higher points mean more serious activity during that time period."
                action={(
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {[
                      { id: 'today', label: 'Today' },
                      { id: '7d', label: '7 days' },
                      { id: '30d', label: '30 days' },
                    ].map((range) => (
                      <button
                        key={range.id}
                        className={`btn btn-sm ${timelineRange === range.id ? 'btn-primary' : 'btn-outline machine-calm-btn'}`}
                        onClick={() => setTimelineRange(range.id)}
                      >
                        {range.label}
                      </button>
                    ))}
                  </div>
                )}
              >
                {timelineData.length ? (
                  <>
                    <ResponsiveContainer width="100%" height={280}>
                      <AreaChart data={timelineData}>
                        <defs>
                          <linearGradient id="dlpRiskFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#ef4444" stopOpacity={0.36} />
                            <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.08} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" vertical={false} />
                        <XAxis dataKey="time" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                        <YAxis
                          domain={[1, 4]}
                          ticks={[1, 2, 3, 4]}
                          tickFormatter={(value) => RISK_LABELS[value]}
                          tick={{ fontSize: 10 }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <Tooltip
                          content={({ active, payload, label }) => {
                            if (!active || !payload?.length) return null
                            const item = payload[0]?.payload
                            return (
                              <div className="chart-tooltip">
                                <div className="chart-tooltip-label">{label}</div>
                                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-1)' }}>{item.label} risk</div>
                                <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text-2)' }}>{item.sample || 'High-risk file copy blocked during this period.'}</div>
                              </div>
                            )
                          }}
                        />
                        <Area dataKey="riskValue" stroke="#ef4444" fill="url(#dlpRiskFill)" strokeWidth={2} />
                      </AreaChart>
                    </ResponsiveContainer>
                    <div className="settings-note">
                      The line rises when the system sees more serious activity. Low means routine watch items. High and critical mean reviewers should check what happened.
                    </div>
                  </>
                ) : (
                  <div className="empty-state">
                    <div className="empty-state-icon"><ReportsIcon size={28} /></div>
                    <div className="empty-state-title">No timeline activity yet</div>
                    <div className="empty-state-sub">Timeline points appear here when sensitive activity is detected.</div>
                  </div>
                )}
              </SimpleSection>

              <SimpleSection title="Users at risk" subtitle="People who may need the fastest follow-up">
                <div style={{ display: 'grid', gap: 10 }}>
                  {enrichedRiskProfiles.slice(0, 5).map((item) => (
                    <div key={item.key} className="control-chip" style={{ justifyContent: 'space-between', width: '100%', borderRadius: 16, padding: '12px 14px' }}>
                      <div style={{ display: 'grid', gap: 3 }}>
                        <strong style={{ color: 'var(--text-1)' }}>{item.userLabel}</strong>
                        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{item.lastAction}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <SimpleBadge tone={item.riskTone}>{item.riskLabel}</SimpleBadge>
                        <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => { setWorkspaceTab('users'); void loadUserRiskDetail(item) }}>View details</button>
                      </div>
                    </div>
                  ))}
                  {!enrichedRiskProfiles.length && <div style={{ color: 'var(--text-3)' }}>No user risk patterns yet.</div>}
                </div>
              </SimpleSection>
            </div>

            <div className="grid-2">
              <SimpleSection title="Baseline scanning progress" subtitle="Baseline scanning learns normal activity so unusual behavior stands out.">
                <div style={{ display: 'grid', gap: 12 }}>
                  {baselineRows.map((row) => (
                    <div key={`${row.userLabel}-${row.machineLabel}`} style={{ display: 'grid', gap: 6 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 12 }}>
                        <div>
                          <strong style={{ color: 'var(--text-1)' }}>{row.userLabel}</strong>
                          <div style={{ color: 'var(--text-3)' }}>{row.machineLabel}</div>
                        </div>
                        <SimpleBadge tone={row.baseline.tone}>{row.baseline.label}</SimpleBadge>
                      </div>
                      <div style={{ height: 8, borderRadius: 999, background: 'var(--border-0)', overflow: 'hidden' }}>
                        <div style={{ width: `${row.baseline.progress}%`, height: '100%', background: 'var(--brand)', borderRadius: 999 }} />
                      </div>
                    </div>
                  ))}
                  {!baselineRows.length && <div style={{ color: 'var(--text-3)' }}>No baseline progress data is available yet.</div>}
                </div>
              </SimpleSection>

              <SimpleSection title="Alerts needing action" subtitle="Highest-priority open items appear first.">
                <div style={{ display: 'grid', gap: 12 }}>
                  {filteredAlerts.slice(0, 4).map((item) => (
                    <div key={item.id} className="card machine-calm-card control-card" style={{ padding: 14 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                        <strong style={{ color: 'var(--text-1)' }}>{item.titleText}</strong>
                        <SimpleBadge tone={riskTone(item.riskKey)}>{item.policyAction}</SimpleBadge>
                      </div>
                      <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-2)' }}>{item.summaryText}</div>
                      <div style={{ marginTop: 10, display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', fontSize: 11, color: 'var(--text-3)' }}>
                        <span>{item.userLabel}</span>
                        <span>{item.machineLabel}</span>
                        <span>{formatDateTime(item.last_seen || item.updated_at || item.created_at)}</span>
                      </div>
                      <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => { setWorkspaceTab('alerts'); void openIncidentAlert(item) }}>Review alert</button>
                        <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setWorkspaceTab('policies')}>Open policy</button>
                      </div>
                    </div>
                  ))}
                  {!filteredAlerts.length && <div style={{ color: 'var(--text-3)' }}>No open alerts right now.</div>}
                </div>
              </SimpleSection>
            </div>

            <SimpleSection title="Sensitive activity log" subtitle="Recent sensitive data actions, shown in plain language.">
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>User</th>
                      <th>Action</th>
                      <th>Data type</th>
                      <th>Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {previewLogRows.map((item) => (
                      <tr key={item.id}>
                        <td>{formatDateTime(item.timestamp)}</td>
                        <td>{item.userLabel}</td>
                        <td>{item.activityLabel}</td>
                        <td>{item.sensitivityLabel}</td>
                        <td><SimpleBadge tone={item.policyAction === 'Blocked automatically' ? 'danger' : item.policyAction === 'Allowed with warning' ? 'warning' : 'success'}>{item.policyAction}</SimpleBadge></td>
                      </tr>
                    ))}
                    {!previewLogRows.length && (
                      <tr>
                        <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-3)' }}>No sensitive activity yet</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div style={{ marginTop: 12 }}>
                <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setWorkspaceTab('alerts')}>Open full log</button>
              </div>
            </SimpleSection>
          </div>
        )}

        {workspaceTab === 'policies' && (
          <div className="control-grid">
            <div className="grid-4">
              <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                <div className="stat-label">Active policies</div>
                <div className="stat-value" style={{ color: 'var(--brand)' }}>{policies.filter((item) => item.status === 'published').length}</div>
                <div className="stat-sub">Policies currently turned on</div>
              </div>
              <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                <div className="stat-label">Blocked actions</div>
                <div className="stat-value" style={{ color: 'var(--red)' }}>{enrichedEvents.filter((item) => item.policyAction === 'Blocked automatically').length}</div>
                <div className="stat-sub">Events stopped by policy</div>
              </div>
              <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                <div className="stat-label">Exceptions</div>
                <div className="stat-value" style={{ color: 'var(--amber)' }}>{exceptions.length}</div>
                <div className="stat-sub">{exceptions.length ? 'Active business allowances in place' : 'No tenant exceptions created yet'}</div>
              </div>
              <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                <div className="stat-label">Draft policies</div>
                <div className="stat-value" style={{ color: 'var(--green)' }}>{policies.filter((item) => item.status !== 'published').length}</div>
                <div className="stat-sub">Saved but not fully turned on</div>
              </div>
            </div>

            <SimpleSection title="Create a policy" subtitle={`Step ${wizardStep} of 4. Use plain-language choices first, then open advanced mode only if you need it.`}>
              <div style={{ display: 'grid', gap: 18 }}>
                <div className="tab-group analytics-tabs" style={{ alignSelf: 'flex-start' }}>
                  {[1, 2, 3, 4].map((step) => (
                    <button key={step} className={`tab-btn ${wizardStep === step ? 'active' : ''}`} onClick={() => setWizardStep(step)}>
                      Step {step}
                    </button>
                  ))}
                </div>

                {wizardStep === 1 && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
                    {POLICY_TARGETS.map((target) => {
                      const active = selectedTargets.includes(target.id)
                      return (
                        <button
                          key={target.id}
                          type="button"
                          className="card machine-calm-card control-card"
                          style={{ padding: 16, textAlign: 'left', border: active ? '1px solid var(--brand)' : '1px solid var(--border-0)', background: active ? 'rgba(59,130,246,.06)' : 'var(--surface-1)' }}
                          onClick={() => setSelectedTargets((prev) => prev.includes(target.id) ? prev.filter((item) => item !== target.id) : [...prev, target.id])}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
                            <strong>{target.label}</strong>
                            {active && <SimpleBadge tone="info">Selected</SimpleBadge>}
                          </div>
                          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-3)', lineHeight: 1.6 }}>{target.desc}</div>
                        </button>
                      )
                    })}
                  </div>
                )}

                {wizardStep === 2 && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
                    {POLICY_LOCATIONS.map((item) => {
                      const active = selectedLocations.includes(item.id)
                      return (
                        <button
                          key={item.id}
                          type="button"
                          className="card machine-calm-card control-card"
                          style={{ padding: 16, textAlign: 'left', border: active ? '1px solid var(--brand)' : '1px solid var(--border-0)', background: active ? 'rgba(59,130,246,.06)' : 'var(--surface-1)' }}
                          onClick={() => setSelectedLocations((prev) => prev.includes(item.id) ? prev.filter((value) => value !== item.id) : [...prev, item.id])}
                        >
                          <strong>{item.label}</strong>
                          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-3)' }}>Use this when sensitive information may leave a protected place.</div>
                        </button>
                      )
                    })}
                  </div>
                )}

                {wizardStep === 3 && (
                  <ChoiceGrid value={selectedLevel} onChange={setSelectedLevel} options={PROTECTION_LEVELS} />
                )}

                {wizardStep === 4 && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
                    {POLICY_AUDIENCES.map((item) => {
                      const active = selectedAudience === item.id
                      return (
                        <button
                          key={item.id}
                          type="button"
                          className="card machine-calm-card control-card"
                          style={{ padding: 16, textAlign: 'left', border: active ? '1px solid var(--brand)' : '1px solid var(--border-0)', background: active ? 'rgba(59,130,246,.06)' : 'var(--surface-1)' }}
                          onClick={() => setSelectedAudience(item.id)}
                        >
                          <strong>{item.label}</strong>
                          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-3)' }}>Start broad if you want simple coverage, then narrow it later if needed.</div>
                        </button>
                      )
                    })}
                  </div>
                )}

                <div className="analytics-note">
                  <strong>Review summary:</strong> {wizardSummary}
                </div>

                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  {wizardStep > 1 && <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setWizardStep((step) => Math.max(1, step - 1))}>Back</button>}
                  {wizardStep < 4 && <button className="btn btn-primary btn-sm" onClick={() => setWizardStep((step) => Math.min(4, step + 1))}>Next step</button>}
                  <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setAdvancedOpen((open) => !open)}>{advancedOpen ? 'Hide advanced mode' : 'Open advanced mode'}</button>
                </div>

                {advancedOpen && (
                  <div className="card machine-calm-card control-card" style={{ padding: 16 }}>
                    <div style={{ display: 'grid', gap: 14 }}>
                      <div className="form-group">
                        <label className="form-label">Policy name</label>
                        <input className="input-field machine-calm-search control-field" value={policyName} onChange={(e) => setPolicyName(e.target.value)} />
                      </div>
                      <div className="form-group">
                        <label className="form-label">Description</label>
                        <textarea className="input-field machine-calm-search" rows={3} value={policyDescription} onChange={(e) => setPolicyDescription(e.target.value)} />
                      </div>
                      <SimpleKeyValue
                        items={[
                          { label: 'Targets', value: selectedTargets.join(', ') || 'None selected' },
                          { label: 'Channels', value: selectedLocations.join(', ') || 'None selected' },
                          { label: 'Audience', value: selectedAudience },
                          { label: 'Outcome', value: selectedLevel },
                        ]}
                      />
                    </div>
                  </div>
                )}

                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  <button className="btn btn-outline machine-calm-btn" onClick={() => savePolicy('draft')} disabled={saving}>{saving ? 'Saving...' : 'Save draft'}</button>
                  <button className="btn btn-primary" onClick={() => savePolicy('published')} disabled={saving}>{saving ? 'Saving...' : 'Turn on policy'}</button>
                </div>
              </div>
            </SimpleSection>

            <SimpleSection title="Current policies" subtitle="Simple policy summaries come first. Advanced data stays out of the way.">
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Policy</th>
                      <th>Protected data</th>
                      <th>Enforcement</th>
                      <th>Last updated</th>
                      <th>Owner</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {policies.map((item) => {
                      const tone = item.status === 'published' ? 'success' : 'warning'
                      const targetSummary = safeArray(item.config?.simple_targets).length
                        ? safeArray(item.config.simple_targets).map((target) => POLICY_TARGETS.find((row) => row.id === target)?.label || target).join(', ')
                        : 'Protected by current baseline'
                      return (
                        <tr key={item.id}>
                          <td>
                            <div style={{ fontWeight: 700 }}>{item.name || 'DLP policy'}</div>
                            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{item.description || 'No description yet'}</div>
                          </td>
                          <td>{targetSummary}</td>
                          <td><SimpleBadge tone={tone}>{humanizeAction(item.rollout_mode || selectedLevel)}</SimpleBadge></td>
                          <td>{formatDateTime(item.updated_at || item.created_at)}</td>
                          <td>{item.created_by || item.owner || 'Admin'}</td>
                          <td>
                            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                              <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => { setPolicyName(item.name || 'Sensitive Data Protection'); setPolicyDescription(item.description || ''); setSelectedLevel(item.rollout_mode || 'soft_block'); setSelectedTargets(safeArray(item.config?.simple_targets).length ? item.config.simple_targets : BASE_POLICY_TARGETS); setWorkspaceTab('policies'); setWizardStep(1) }}>{item.status === 'published' ? 'Pause / edit' : 'Edit'}</button>
                              <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => unsupportedAction('Duplicate policy')}>Duplicate</button>
                              <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setWorkspaceTab('overview')}>View results</button>
                              <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => unsupportedAction('Delete policy')}>Delete</button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                    {!policies.length && (
                      <tr>
                        <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-3)' }}>No policies have been created yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </SimpleSection>
          </div>
        )}

        {workspaceTab === 'alerts' && (
          <div className="control-grid">
            <div className="filter-bar analytics-filter-panel machine-calm-card control-filter">
              <select className="input-field machine-calm-search control-field" value={alertFilters.severity} onChange={(e) => setAlertFilters((prev) => ({ ...prev, severity: e.target.value }))}>
                <option value="">All severity</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
              <select className="input-field machine-calm-search control-field" value={alertFilters.status} onChange={(e) => setAlertFilters((prev) => ({ ...prev, status: e.target.value }))}>
                <option value="">All status</option>
                <option value="Needs review">Needs review</option>
                <option value="Looks safe">Looks safe</option>
              </select>
              <select className="input-field machine-calm-search control-field" value={alertFilters.user} onChange={(e) => setAlertFilters((prev) => ({ ...prev, user: e.target.value }))}>
                <option value="">All users</option>
                {userOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <select className="input-field machine-calm-search control-field" value={alertFilters.policy} onChange={(e) => setAlertFilters((prev) => ({ ...prev, policy: e.target.value }))}>
                <option value="">All policies</option>
                {policyOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <input type="date" className="input-field machine-calm-search control-field" value={alertFilters.date} onChange={(e) => setAlertFilters((prev) => ({ ...prev, date: e.target.value }))} />
              {(alertFilters.severity || alertFilters.status || alertFilters.user || alertFilters.policy || alertFilters.date) && (
                <button className="btn btn-outline machine-calm-btn btn-sm" onClick={clearAlertFilters}>Clear filters</button>
              )}
            </div>

            <div style={{ display: 'grid', gap: 12 }}>
              {filteredAlerts.map((item) => (
                <div key={item.id} className="card machine-calm-card control-card" style={{ padding: 16 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <SimpleBadge tone={riskTone(item.riskKey)}>{item.riskKey || 'medium'}</SimpleBadge>
                        <strong style={{ color: 'var(--text-1)' }}>{item.titleText}</strong>
                      </div>
                      <div style={{ marginTop: 6, color: 'var(--text-2)', fontSize: 13 }}>{item.summaryText}</div>
                    </div>
                    <SimpleBadge tone={policyActionTone(item.policyAction)}>{item.policyAction}</SimpleBadge>
                  </div>

                  <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, fontSize: 12 }}>
                    <DetailValue label="User">{item.userLabel}</DetailValue>
                    <DetailValue label="Device">{item.machineLabel}</DetailValue>
                    <DetailValue label="Policy">{item.policy_name || 'Current policy'}</DetailValue>
                    <DetailValue label="Time">{formatDateTime(item.last_seen || item.updated_at || item.created_at)}</DetailValue>
                  </div>

                  <div style={{ marginTop: 14, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <button className="btn btn-primary btn-sm" onClick={() => unsupportedAction('Keep blocked')}>Keep blocked</button>
                    <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => createExceptionFromAlert(item, true)} disabled={busyAction === `exception-${item.id || item.event_id || 'alert'}`}>Allow once</button>
                    <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => acknowledgeEvent(item.event_id || item.source_event_id || item.related_event_id)}>Mark safe</button>
                    <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => unsupportedAction('Escalate')}>Escalate</button>
                    <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => void openIncidentAlert(item)}>View details</button>
                    <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => createExceptionFromAlert(item, false)} disabled={busyAction === `exception-${item.id || item.event_id || 'alert'}`}>Add exception</button>
                  </div>
                </div>
              ))}

              {!filteredAlerts.length && (
                <div className="empty-state">
                  <div className="empty-state-icon"><AlertsIcon size={28} /></div>
                  <div className="empty-state-title">No alerts match these filters</div>
                  <div className="empty-state-sub">Try removing a filter or come back when new DLP alerts arrive.</div>
                </div>
              )}
            </div>

            <SimpleSection title="Sensitive activity log" subtitle="Human-readable actions first. Technical details stay inside the details view.">
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>User</th>
                      <th>Action</th>
                      <th>Data type</th>
                      <th>Source</th>
                      <th>Destination</th>
                      <th>Result</th>
                      <th>Policy</th>
                    </tr>
                  </thead>
                  <tbody>
                    {enrichedEvents.map((item) => (
                      <tr key={item.id}>
                        <td>{formatDateTime(item.timestamp)}</td>
                        <td>{item.userLabel}</td>
                        <td>{item.activityLabel}</td>
                        <td>{item.sensitivityLabel}</td>
                        <td>{item.file_path || item.source_path || '-'}</td>
                        <td>{item.destination_label || item.destination || '-'}</td>
                        <td>{item.policyAction}</td>
                        <td>{item.policy_name || 'Current policy'}</td>
                      </tr>
                    ))}
                    {!enrichedEvents.length && (
                      <tr>
                        <td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-3)' }}>No sensitive activity has been recorded yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </SimpleSection>
          </div>
        )}

        {workspaceTab === 'users' && (
          <div className="control-grid">
            <div className="filter-bar analytics-filter-panel machine-calm-card control-filter">
              <select className="input-field machine-calm-search control-field" value={userRiskFilters.window_days} onChange={(e) => setUserRiskFilters((prev) => ({ ...prev, window_days: e.target.value }))}>
                <option value="7">Last 7 days</option>
                <option value="30">Last 30 days</option>
                <option value="90">Last 90 days</option>
              </select>
              <select className="input-field machine-calm-search control-field" value={userRiskFilters.min_risk_level} onChange={(e) => setUserRiskFilters((prev) => ({ ...prev, min_risk_level: e.target.value }))}>
                <option value="">All risk levels</option>
                <option value="watch">Watch</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
              <select className="input-field machine-calm-search control-field" value={userRiskFilters.trend} onChange={(e) => setUserRiskFilters((prev) => ({ ...prev, trend: e.target.value }))}>
                <option value="">All trends</option>
                <option value="rising">Rising</option>
                <option value="stable">Stable</option>
                <option value="cooling">Cooling</option>
              </select>
              <input className="input-field machine-calm-search control-field" value={userRiskFilters.machine_id} onChange={(e) => setUserRiskFilters((prev) => ({ ...prev, machine_id: e.target.value }))} placeholder="Machine id" />
              <input className="input-field machine-calm-search control-field" value={userRiskFilters.destination_type} onChange={(e) => setUserRiskFilters((prev) => ({ ...prev, destination_type: e.target.value }))} placeholder="Destination type" />
              <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => void loadUserRiskProfiles(userRiskFilters)} disabled={userRiskLoading}>
                {userRiskLoading ? 'Loading...' : 'Apply filters'}
              </button>
              {(userRiskFilters.window_days !== '90' || userRiskFilters.min_risk_level || userRiskFilters.trend || userRiskFilters.machine_id || userRiskFilters.destination_type) && (
                <button
                  className="btn btn-outline machine-calm-btn btn-sm"
                  onClick={() => {
                    const nextFilters = { window_days: '90', min_risk_level: '', trend: '', machine_id: '', destination_type: '' }
                    setUserRiskFilters(nextFilters)
                    void loadUserRiskProfiles(nextFilters)
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>

            <SimpleSection title="Top users at risk" subtitle="A people-first view of repeated risky or blocked actions.">
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>User</th>
                      <th>Current risk</th>
                      <th>Trend</th>
                      <th>Baseline progress</th>
                      <th>High-risk events</th>
                      <th>Last risky action</th>
                      <th>Status</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {enrichedRiskProfiles.map((item) => (
                      <tr key={item.key}>
                        <td>
                          <div style={{ fontWeight: 700 }}>{item.userLabel}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{item.machineLabel}</div>
                        </td>
                        <td><SimpleBadge tone={item.riskTone}>{item.riskLabel}</SimpleBadge></td>
                        <td>{item.trend}</td>
                        <td>
                          <div style={{ display: 'grid', gap: 6, minWidth: 160 }}>
                            <div style={{ height: 8, borderRadius: 999, background: 'var(--border-0)', overflow: 'hidden' }}>
                              <div style={{ width: `${item.baseline.progress}%`, height: '100%', background: 'var(--brand)', borderRadius: 999 }} />
                            </div>
                            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{item.baseline.label}</span>
                          </div>
                        </td>
                        <td>{item.high_risk_event_count}</td>
                        <td>{item.lastAction}</td>
                        <td>{item.latestItem?.policyAction || 'Needs review'}</td>
                        <td>
                          <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => void loadUserRiskDetail(item)}>View details</button>
                        </td>
                      </tr>
                    ))}
                    {!enrichedRiskProfiles.length && (
                      <tr>
                        <td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-3)' }}>No user risk signals are available yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </SimpleSection>
          </div>
        )}
      </PageStateView>

      <ActivityDrawer
        open={Boolean(selectedAlert)}
        title={incidentDetail?.title || selectedAlert?.titleText || 'Alert details'}
        subtitle={selectedAlert ? `${selectedAlert.userLabel} on ${selectedAlert.machineLabel}` : ''}
        badges={selectedAlert ? [
          { label: incidentDetail?.policy_name || selectedAlert.policy_name || 'Current policy' },
          { label: humanizeIncidentState(incidentDetail?.state || selectedAlert.state || 'new') },
          { label: selectedAlert.riskKey || incidentDetail?.severity || 'medium' },
        ] : []}
        onClose={closeIncidentDrawer}
        footer={selectedAlert ? (
          <>
            <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => createExceptionFromAlert(selectedAlert, true)} disabled={busyAction === `exception-${selectedAlert.id || selectedAlert.event_id || 'alert'}`}>Allow once</button>
            <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => acknowledgeEvent(selectedAlert.event_id || selectedAlert.source_event_id || selectedAlert.related_event_id)} disabled={busyAction === (selectedAlert.event_id || selectedAlert.source_event_id || selectedAlert.related_event_id)}>
              {busyAction === (selectedAlert.event_id || selectedAlert.source_event_id || selectedAlert.related_event_id) ? 'Updating...' : 'Mark safe'}
            </button>
            <button className="btn btn-primary btn-sm" onClick={saveIncidentReview} disabled={incidentSaving}>
              {incidentSaving ? 'Saving...' : 'Save review'}
            </button>
          </>
        ) : null}
      >
        {selectedAlert && (
          <div style={{ display: 'grid', gap: 18 }}>
            {incidentLoading ? (
              <div className="control-empty">Loading incident details...</div>
            ) : (
              <>
                <SimpleSection title="Incident overview" subtitle="The full case context for this sensitive activity.">
                  <SimpleKeyValue
                    items={[
                      { label: 'Summary', value: incidentDetail?.summary || selectedAlert.summaryText },
                      { label: 'Policy', value: incidentDetail?.policy_name || selectedAlert.policy_name || 'Current policy' },
                      { label: 'User', value: incidentDetail?.actor_username || selectedAlert.userLabel || '-' },
                      { label: 'Machine', value: incidentDetail?.machine_id || selectedAlert.machineLabel || '-' },
                      { label: 'Channel', value: incidentDetail?.channel || selectedAlert.destination_type || 'file' },
                      { label: 'Destination', value: incidentDetail?.destination_label || incidentDetail?.destination_type || selectedAlert.destination_label || selectedAlert.destination_type || '-' },
                      { label: 'First seen', value: formatDateTime(incidentDetail?.first_seen || selectedAlert.created_at) },
                      { label: 'Last seen', value: formatDateTime(incidentDetail?.last_seen || selectedAlert.last_seen || selectedAlert.updated_at || selectedAlert.created_at) },
                    ]}
                  />
                </SimpleSection>

                <SimpleSection title="History summary" subtitle="Past related cases over the default 90-day investigation window.">
                  <div className="grid-4">
                    <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                      <div className="stat-label">Repeat incidents</div>
                      <div className="stat-value" style={{ color: 'var(--amber)' }}>{incidentDetail?.history_summary?.repeat_incident_count || 0}</div>
                      <div className="stat-sub">Older related cases</div>
                    </div>
                    <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                      <div className="stat-label">Same user</div>
                      <div className="stat-value" style={{ color: 'var(--brand)' }}>{incidentDetail?.history_summary?.same_user || 0}</div>
                      <div className="stat-sub">Past incidents tied to this user</div>
                    </div>
                    <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                      <div className="stat-label">Same file identity</div>
                      <div className="stat-value" style={{ color: 'var(--red)' }}>{incidentDetail?.history_summary?.same_file_identity || 0}</div>
                      <div className="stat-sub">Matched by hash or content fingerprint</div>
                    </div>
                    <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                      <div className="stat-label">Last analyst outcome</div>
                      <div className="stat-value" style={{ color: 'var(--green)', fontSize: 18 }}>{humanizeIncidentState(incidentDetail?.history_summary?.last_analyst_outcome || 'none recorded')}</div>
                      <div className="stat-sub">Most recent saved disposition</div>
                    </div>
                  </div>
                </SimpleSection>

                <SimpleSection title="Response" subtitle="Document the analyst decision without leaving the DLP workspace.">
                  <div className="phishing-form-grid">
                    <label className="phishing-field">
                      <span>State</span>
                      <select className="input-field control-field" value={detailForm.state} onChange={(e) => setDetailForm((prev) => ({ ...prev, state: e.target.value }))}>
                        {INCIDENT_STATES.map((option) => <option key={option} value={option}>{humanizeIncidentState(option)}</option>)}
                      </select>
                    </label>
                    <label className="phishing-field">
                      <span>Severity</span>
                      <select className="input-field control-field" value={detailForm.severity} onChange={(e) => setDetailForm((prev) => ({ ...prev, severity: e.target.value }))}>
                        {['low', 'medium', 'high', 'critical'].map((option) => <option key={option} value={option}>{humanizeIncidentState(option)}</option>)}
                      </select>
                    </label>
                    <label className="phishing-field">
                      <span>Assignee</span>
                      <input className="input-field control-field" value={detailForm.assignee} onChange={(e) => setDetailForm((prev) => ({ ...prev, assignee: e.target.value }))} placeholder="SOC analyst" />
                    </label>
                    <label className="phishing-field">
                      <span>Disposition</span>
                      <select className="input-field control-field" value={detailForm.disposition} onChange={(e) => setDetailForm((prev) => ({ ...prev, disposition: e.target.value }))}>
                        {INCIDENT_DISPOSITIONS.map((option) => <option key={option.value || 'none'} value={option.value}>{option.label}</option>)}
                      </select>
                    </label>
                    <label className="phishing-field phishing-field-wide">
                      <span>Resolution reason</span>
                      <input className="input-field control-field" value={detailForm.resolution_reason} onChange={(e) => setDetailForm((prev) => ({ ...prev, resolution_reason: e.target.value }))} placeholder="Why this was contained, approved, false positive, or escalated." />
                    </label>
                    <label className="phishing-field phishing-field-wide">
                      <span>Analyst note</span>
                      <textarea className="input-field control-field phishing-textarea" value={detailForm.note} onChange={(e) => setDetailForm((prev) => ({ ...prev, note: e.target.value }))} placeholder="Capture the decision, user intent, or next follow-up." />
                    </label>
                  </div>
                </SimpleSection>

                <SimpleSection title="Evidence" subtitle="Why the incident was raised and what the endpoint observed.">
                  <div style={{ display: 'grid', gap: 12 }}>
                    {(incidentDetail?.evidence_summary || []).map((group) => (
                      <div key={group.kind} className="card machine-calm-card control-card" style={{ padding: 14 }}>
                        <div style={{ fontWeight: 700, color: 'var(--text-1)', marginBottom: 8 }}>{group.title}</div>
                        <div className="phishing-timeline">
                          {(group.items || []).map((entry, index) => (
                            <div key={`${group.kind}-${index}`} className="phishing-timeline-item">
                              <div className="phishing-timeline-title">{entry.name || entry.file_name || entry.category || entry.label || entry.type || group.kind}</div>
                              <div className="phishing-timeline-copy">
                                {entry.preview || entry.value || entry.destination_label || entry.action_result || entry.classification || entry.category || '-'}
                              </div>
                              <div className="phishing-timeline-sub">{entry.timestamp ? formatDateTime(entry.timestamp) : entry.created_at ? formatDateTime(entry.created_at) : ''}</div>
                            </div>
                          ))}
                          {!group.items?.length && <div className="phishing-empty-copy">No stored entries.</div>}
                        </div>
                      </div>
                    ))}
                    {!incidentDetail?.evidence_summary?.length && <div className="phishing-empty-copy">No evidence summary was stored for this incident.</div>}
                  </div>
                </SimpleSection>

                <SimpleSection title="Retention summary" subtitle="How long the linked evidence and history are expected to remain available.">
                  <SimpleKeyValue
                    items={[
                      { label: 'History window', value: `${incidentDetail?.retention_summary?.window_days || 90} days` },
                      { label: 'Storage backend', value: incidentDetail?.retention_summary?.storage_backend || '-' },
                      { label: 'Evidence protection', value: incidentDetail?.retention_summary?.encryption_status || '-' },
                      { label: 'Linked artifacts', value: String(incidentDetail?.retention_summary?.linked_artifact_count || 0) },
                      { label: 'Active artifacts', value: String(incidentDetail?.retention_summary?.active_artifact_count || 0) },
                      { label: 'Expiring soon', value: String(incidentDetail?.retention_summary?.expiring_soon_count || 0) },
                      { label: 'Expired', value: String(incidentDetail?.retention_summary?.expired_artifact_count || 0) },
                      { label: 'Next expiry', value: formatDateTime(incidentDetail?.retention_summary?.next_expiry_at) },
                    ]}
                  />
                </SimpleSection>

                <div className="grid-2">
                  <SimpleSection title="Timeline" subtitle="The sequence of system and analyst actions for this case.">
                    <div className="phishing-timeline">
                      {(incidentDetail?.timeline || []).map((entry) => (
                        <div key={entry.id || `${entry.action}-${entry.created_at}`} className="phishing-timeline-item">
                          <div className="phishing-timeline-title">{humanizeIncidentState(entry.action || 'timeline')}</div>
                          <div className="phishing-timeline-copy">{entry.payload?.resolution_reason || entry.payload?.disposition || entry.payload?.action_result || entry.payload?.destination_type || '-'}</div>
                          <div className="phishing-timeline-sub">{entry.actor_type || 'system'} · {entry.actor || 'system'} · {formatDateTime(entry.created_at)}</div>
                        </div>
                      ))}
                      {!incidentDetail?.timeline?.length && <div className="phishing-empty-copy">No timeline yet.</div>}
                    </div>
                  </SimpleSection>

                  <SimpleSection title="Notes" subtitle="Analyst notes stay attached to the incident for later review.">
                    <div className="phishing-timeline">
                      {(incidentDetail?.notes || []).map((entry) => (
                        <div key={entry.id || `${entry.author}-${entry.created_at}`} className="phishing-timeline-item">
                          <div className="phishing-timeline-title">{entry.author || 'analyst'}</div>
                          <div className="phishing-timeline-copy">{entry.note || '-'}</div>
                          <div className="phishing-timeline-sub">{formatDateTime(entry.created_at)}</div>
                        </div>
                      ))}
                      {!incidentDetail?.notes?.length && <div className="phishing-empty-copy">No analyst notes yet.</div>}
                    </div>
                  </SimpleSection>
                </div>

                <div className="grid-2">
                  <SimpleSection title="Related activity" subtitle="Other endpoint activity linked to the same file, user, or destination.">
                    <div className="phishing-timeline">
                      {(incidentDetail?.related_activity || []).map((entry) => (
                        <div key={entry.id || `${entry.channel}-${entry.timestamp}`} className="phishing-timeline-item">
                          <div className="phishing-timeline-title">{entry.file_name || 'Sensitive content'} · {entry.destination_type || entry.channel}</div>
                          <div className="phishing-timeline-copy">{entry.action_result || 'observed'}{entry.destination_label ? ` · ${entry.destination_label}` : ''}</div>
                          <div className="phishing-timeline-sub">{formatDateTime(entry.timestamp)}</div>
                        </div>
                      ))}
                      {!incidentDetail?.related_activity?.length && <div className="phishing-empty-copy">No related activity beyond this incident yet.</div>}
                    </div>
                  </SimpleSection>

                  <SimpleSection title="Recommended next steps" subtitle="Plain-language follow-up guidance for the analyst.">
                    <div className="phishing-timeline">
                      {(incidentDetail?.recommended_actions || []).map((entry, index) => (
                        <div key={`next-${index}`} className="phishing-timeline-item">
                          <div className="phishing-timeline-title">Next step {index + 1}</div>
                          <div className="phishing-timeline-copy">{entry}</div>
                        </div>
                      ))}
                      {!incidentDetail?.recommended_actions?.length && <div className="phishing-empty-copy">No recommended actions were generated.</div>}
                    </div>
                  </SimpleSection>
                </div>

                <SimpleSection title="Historical investigations" subtitle="Pivot into older related cases without leaving the DLP page.">
                  <div style={{ display: 'grid', gap: 14 }}>
                    <div className="phishing-form-grid">
                      <label className="phishing-field">
                        <span>User</span>
                        <input className="input-field control-field" value={historyFilters.actor_username} onChange={(e) => setHistoryFilters((prev) => ({ ...prev, actor_username: e.target.value }))} placeholder="Same user" />
                      </label>
                      <label className="phishing-field">
                        <span>Machine</span>
                        <input className="input-field control-field" value={historyFilters.machine_id} onChange={(e) => setHistoryFilters((prev) => ({ ...prev, machine_id: e.target.value }))} placeholder="Machine id" />
                      </label>
                      <label className="phishing-field">
                        <span>Destination</span>
                        <input className="input-field control-field" value={historyFilters.destination_type} onChange={(e) => setHistoryFilters((prev) => ({ ...prev, destination_type: e.target.value }))} placeholder="usb, print, email" />
                      </label>
                      <label className="phishing-field">
                        <span>Disposition</span>
                        <input className="input-field control-field" value={historyFilters.disposition} onChange={(e) => setHistoryFilters((prev) => ({ ...prev, disposition: e.target.value }))} placeholder="contained, false_positive" />
                      </label>
                      <label className="phishing-field phishing-field-wide">
                        <span>File hash</span>
                        <input className="input-field control-field" value={historyFilters.file_hash} onChange={(e) => setHistoryFilters((prev) => ({ ...prev, file_hash: e.target.value }))} placeholder="Exact file hash pivot" />
                      </label>
                      <label className="phishing-field phishing-field-wide">
                        <span>Content fingerprint</span>
                        <input className="input-field control-field" value={historyFilters.content_fingerprint} onChange={(e) => setHistoryFilters((prev) => ({ ...prev, content_fingerprint: e.target.value }))} placeholder="Exact content fingerprint pivot" />
                      </label>
                      <label className="phishing-field">
                        <span>From</span>
                        <input type="date" className="input-field control-field" value={historyFilters.date_from} onChange={(e) => setHistoryFilters((prev) => ({ ...prev, date_from: e.target.value }))} />
                      </label>
                      <label className="phishing-field">
                        <span>To</span>
                        <input type="date" className="input-field control-field" value={historyFilters.date_to} onChange={(e) => setHistoryFilters((prev) => ({ ...prev, date_to: e.target.value }))} />
                      </label>
                    </div>

                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => loadHistoricalIncidents(historyFilters, incidentDetail?.id || selectedAlert?.id)} disabled={historyLoading}>
                        {historyLoading ? 'Loading...' : 'Apply history filters'}
                      </button>
                      {incidentDetail?.previous_similar_incident && (
                        <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => void openIncidentAlert(incidentDetail.previous_similar_incident)}>
                          Open previous similar incident
                        </button>
                      )}
                    </div>

                    <div className="phishing-timeline">
                      {historyResults.map((entry) => (
                        <div key={entry.id} className="phishing-timeline-item">
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                            <div className="phishing-timeline-title">{entry.title || entry.summary || `DLP incident ${entry.id}`}</div>
                            <SimpleBadge tone={riskTone(String(entry.severity || 'medium').toLowerCase())}>{entry.severity || 'medium'}</SimpleBadge>
                          </div>
                          <div className="phishing-timeline-copy">
                            {(entry.relation_reasons || []).map((reason) => reason.replaceAll('_', ' ')).join(', ') || 'related incident'}
                            {entry.metadata?.disposition ? ` · ${entry.metadata.disposition.replaceAll('_', ' ')}` : ''}
                          </div>
                          <div className="phishing-timeline-sub">{formatDateTime(entry.last_seen || entry.updated_at || entry.created_at)}</div>
                          <div style={{ marginTop: 8 }}>
                            <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => void openIncidentAlert(entry)}>Open incident</button>
                          </div>
                        </div>
                      ))}
                      {!historyResults.length && <div className="phishing-empty-copy">No related historical incidents matched the current filters.</div>}
                    </div>
                  </div>
                </SimpleSection>
              </>
            )}
          </div>
        )}
      </ActivityDrawer>

      <ActivityDrawer
        open={Boolean(selectedUser || selectedUserDetail)}
        title={currentUserRisk?.userLabel || 'User details'}
        subtitle={currentUserRisk ? `${currentUserRisk.riskLabel} risk profile` : ''}
        badges={currentUserRisk ? [
          { label: currentUserRisk.riskLabel },
          { label: currentUserRisk.baseline?.label || 'No baseline' },
          { label: humanizeTrend(currentUserRisk.trend) },
        ] : []}
        onClose={closeUserRiskDrawer}
        footer={currentUserRisk ? (
          <>
            <button
              className="btn btn-outline machine-calm-btn btn-sm"
              onClick={() => {
                setAlertFilters((prev) => ({ ...prev, user: currentUserRisk.userLabel || '' }))
                setWorkspaceTab('alerts')
                closeUserRiskDrawer()
              }}
            >
              Review alerts
            </button>
            <button
              className="btn btn-outline machine-calm-btn btn-sm"
              onClick={() => {
                if (currentUserRisk.recent_incidents?.[0]?.id) {
                  closeUserRiskDrawer()
                  void openIncidentAlert(currentUserRisk.recent_incidents[0])
                } else {
                  notify('No incident drill-in is available for this user yet.', 'amber')
                }
              }}
            >
              Open latest incident
            </button>
            <button
              className="btn btn-outline machine-calm-btn btn-sm"
              onClick={() => {
                setWorkspaceTab('policies')
                closeUserRiskDrawer()
              }}
            >
              Adjust policy coverage
            </button>
          </>
        ) : null}
      >
        {(selectedUser || selectedUserDetail) && (
          <div style={{ display: 'grid', gap: 18 }}>
            {userDetailLoading && !currentUserRisk?.risk_score ? (
              <div className="control-empty">Loading user risk details...</div>
            ) : (
              <>
                <div className="grid-4">
                  <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                    <div className="stat-label">Risk score</div>
                    <div className="stat-value" style={{ color: 'var(--red)' }}>{currentUserRisk?.risk_score || 0}</div>
                    <div className="stat-sub">{currentUserRisk?.riskLabel || 'Low'}</div>
                  </div>
                  <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                    <div className="stat-label">Blocked actions</div>
                    <div className="stat-value" style={{ color: 'var(--amber)' }}>{currentUserRisk?.blocked_event_count || 0}</div>
                    <div className="stat-sub">Highest-confidence risky attempts</div>
                  </div>
                  <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                    <div className="stat-label">Repeat incidents</div>
                    <div className="stat-value" style={{ color: 'var(--brand)', fontSize: 26 }}>{currentUserRisk?.repeat_incident_count || 0}</div>
                    <div className="stat-sub">Investigations tied to this user</div>
                  </div>
                  <div className="stat-card machine-calm-card machine-calm-stat control-stat">
                    <div className="stat-label">Trend</div>
                    <div className="stat-value" style={{ color: 'var(--green)', fontSize: 22 }}>{humanizeTrend(currentUserRisk?.trend)}</div>
                    <div className="stat-sub">Based on recent DLP behavior</div>
                  </div>
                </div>

                <SimpleSection title="Risk overview" subtitle="Why this user is ranked here right now.">
                  <SimpleKeyValue
                    items={[
                      { label: 'Recent sensitive action', value: currentUserRisk?.lastAction || '-' },
                      { label: 'Latest machine', value: currentUserRisk?.machineLabel || '-' },
                      { label: 'Latest destination', value: currentUserRisk?.latest_destination_type || '-' },
                      { label: 'Latest high-risk activity', value: formatDateTime(currentUserRisk?.latest_high_risk_timestamp || currentUserRisk?.latest_activity_at) },
                      { label: 'Warnings shown', value: String(currentUserRisk?.warning_event_count || 0) },
                      { label: 'After-hours events', value: String(currentUserRisk?.after_hours_event_count || 0) },
                      { label: 'Machines involved', value: String(currentUserRisk?.related_machine_count || currentUserRisk?.linked_machine_count || 0) },
                      { label: 'New risky destinations', value: String(currentUserRisk?.new_destination_count || 0) },
                    ]}
                  />
                </SimpleSection>

                <div className="grid-2">
                  <SimpleSection title="Top reasons" subtitle="Every score contribution stays explainable.">
                    <div className="phishing-timeline">
                      {(currentUserRisk?.reason_history || []).map((entry) => (
                        <div key={entry.code} className="phishing-timeline-item">
                          <div className="phishing-timeline-title">{entry.label}</div>
                          <div className="phishing-timeline-copy">{entry.count} signal{entry.count === 1 ? '' : 's'} contributing {entry.points} point{entry.points === 1 ? '' : 's'}.</div>
                        </div>
                      ))}
                      {!currentUserRisk?.reason_history?.length && <div className="phishing-empty-copy">No ranked reason history is available yet.</div>}
                    </div>
                  </SimpleSection>

                  <SimpleSection title="Recommended next steps" subtitle="Focused follow-up guidance for the analyst.">
                    <div className="phishing-timeline">
                      {(currentUserRisk?.recommended_actions || []).map((entry, index) => (
                        <div key={`user-risk-next-${index}`} className="phishing-timeline-item">
                          <div className="phishing-timeline-title">Next step {index + 1}</div>
                          <div className="phishing-timeline-copy">{entry}</div>
                        </div>
                      ))}
                      {!currentUserRisk?.recommended_actions?.length && <div className="phishing-empty-copy">No recommended actions were generated.</div>}
                    </div>
                  </SimpleSection>
                </div>

                <div className="grid-2">
                  <SimpleSection title="Recent incidents" subtitle="This user’s latest investigations inside the selected window.">
                    <div className="phishing-timeline">
                      {(currentUserRisk?.recent_incidents || []).map((entry) => (
                        <div key={entry.id || `${entry.title}-${entry.last_seen}`} className="phishing-timeline-item">
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                          <div className="phishing-timeline-title">{entry.title || `DLP incident ${entry.id}`}</div>
                          <SimpleBadge tone={riskTone(String(entry.severity || 'medium').toLowerCase())}>{entry.severity || 'medium'}</SimpleBadge>
                        </div>
                          <div className="phishing-timeline-copy">{entry.summary || 'Sensitive activity under investigation.'}</div>
                          <div className="phishing-timeline-sub">{entry.disposition ? `${humanizeIncidentState(entry.disposition)} · ` : ''}{formatDateTime(entry.last_seen)}</div>
                          <div style={{ marginTop: 8 }}>
                            <button
                              className="btn btn-outline machine-calm-btn btn-sm"
                              onClick={() => {
                                closeUserRiskDrawer()
                                void openIncidentAlert(entry)
                              }}
                            >
                              Open incident
                            </button>
                          </div>
                        </div>
                      ))}
                      {!currentUserRisk?.recent_incidents?.length && <div className="phishing-empty-copy">No recent DLP incidents are linked to this user.</div>}
                    </div>
                  </SimpleSection>

                  <SimpleSection title="Recent events" subtitle="Latest endpoint actions contributing to this user’s score.">
                    <div className="phishing-timeline">
                      {(currentUserRisk?.recent_events || []).map((entry) => (
                        <div key={entry.id || `${entry.file_name}-${entry.timestamp}`} className="phishing-timeline-item">
                          <div className="phishing-timeline-title">{entry.file_name || 'Sensitive content'} · {entry.destination_type || entry.channel}</div>
                          <div className="phishing-timeline-copy">{entry.action_result || 'observed'}{entry.destination_label ? ` · ${entry.destination_label}` : ''}</div>
                          <div className="phishing-timeline-sub">{formatDateTime(entry.timestamp)}</div>
                        </div>
                      ))}
                      {!currentUserRisk?.recent_events?.length && <div className="phishing-empty-copy">No recent user-risk events are available.</div>}
                    </div>
                  </SimpleSection>
                </div>

                <SimpleSection title="Related files and machines" subtitle="Useful pivots when risk is spreading across repeated attempts.">
                  <SimpleKeyValue
                    items={[
                      {
                        label: 'Related files',
                        value: currentUserRisk?.related_files?.map((entry) => {
                          if (typeof entry === 'string') return entry
                          return entry.file_name || entry.file_hash || entry.content_fingerprint
                        }).filter(Boolean).join(', ') || 'No repeated file identity yet',
                      },
                      { label: 'Recent machines', value: currentUserRisk?.recent_machine_ids?.join(', ') || currentUserRisk?.machineLabel || '-' },
                      { label: 'Reason summary', value: currentUserRisk?.reason_summary || 'No summarized reason available yet.' },
                      { label: 'Baseline status', value: `${currentUserRisk?.baseline?.label || 'Not started'}${currentUserRisk?.baseline ? ` (${currentUserRisk.baseline.progress}%)` : ''}` },
                    ]}
                  />
                </SimpleSection>
              </>
            )}
          </div>
        )}
      </ActivityDrawer>

      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: 24,
            right: 24,
            zIndex: 9999,
            background: 'var(--surface-3)',
            border: `1px solid ${toast.type === 'red' ? 'rgba(239,68,68,.3)' : toast.type === 'amber' ? 'rgba(245,158,11,.3)' : 'rgba(16,185,129,.3)'}`,
            color: toast.type === 'red' ? 'var(--red)' : toast.type === 'amber' ? 'var(--amber)' : 'var(--green)',
            padding: '12px 18px',
            borderRadius: 'var(--r-md)',
            fontSize: 13,
            fontWeight: 600,
            boxShadow: 'var(--shadow-lg)',
          }}
        >
          {toast.msg}
        </div>
      )}
    </div>
  )
}

function humanizeAction(value) {
  if (value === 'monitor_only') return 'Monitor only'
  if (value === 'hard_block') return 'Block automatically'
  return 'Warn user'
}

function humanizeIncidentState(value) {
  const state = String(value || 'new').replaceAll('_', ' ')
  return state.charAt(0).toUpperCase() + state.slice(1)
}

function humanizeTrend(value) {
  const trend = String(value || 'stable').replaceAll('_', ' ')
  return trend.charAt(0).toUpperCase() + trend.slice(1)
}
