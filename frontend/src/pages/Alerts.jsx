import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, useWsListener } from '../hooks/useAuth'
import { useNotifications } from '../hooks/useNotifications'
import { usePageContext } from '../hooks/usePageContext'
import { PageStateView } from '../components/ui/PageState'
import { ActivityDrawer } from '../features/activity/activityUi'
import { ChoiceGrid, SimpleBadge, SimpleKeyValue, SimpleSection } from '../features/security/simpleUi'
import { AlertsIcon, DlpIcon, PhishingIcon } from '../components/ui/OverviewIcons'

const RULE_TYPES = ['system', 'browser', 'idle', 'schedule', 'connectivity', 'app']
const CONDITIONS = {
  system: ['cpu_percent_gt', 'memory_percent_gt'],
  browser: ['domain_in_blacklist', 'domain_contains'],
  idle: ['idle_seconds_gt'],
  schedule: ['outside_hours'],
  connectivity: ['machine_offline'],
  app: ['app_blocked'],
}
const SEVERITIES = ['low', 'medium', 'high', 'critical']
const DLP_INCIDENT_STATES = ['new', 'investigating', 'contained', 'approved_business_use', 'false_positive', 'escalated', 'closed']
const PHISHING_INCIDENT_STATES = ['open', 'in_review', 'resolved', 'false_positive']
const DLP_DISPOSITIONS = [
  { value: '', label: 'No disposition yet' },
  { value: 'contained', label: 'Contained' },
  { value: 'approved_business_use', label: 'Approved business use' },
  { value: 'false_positive', label: 'False positive' },
  { value: 'escalated', label: 'Escalated' },
  { value: 'closed', label: 'Closed' },
]
const WORKSPACE_TABS = [
  { id: 'inbox', label: 'Analyst Inbox' },
  { id: 'rules', label: 'Alert Rules' },
]
const SOURCE_FILTERS = [
  { id: 'all', label: 'All alerts' },
  { id: 'generic', label: 'Generic alerts' },
  { id: 'dlp', label: 'DLP context' },
  { id: 'phishing', label: 'Phishing context' },
]
const SOURCE_META = {
  generic: {
    label: 'Generic alert',
    subtitle: 'Rule-driven workstation and activity alerts',
    badgeTone: 'info',
    reviewLabel: 'Open machine context',
    emptyCopy: 'Rule-driven alerts appear here when the tenant alert engine fires.',
  },
  dlp: {
    label: 'DLP incident',
    subtitle: 'Sensitive data movement and blocked transfer context',
    badgeTone: 'warning',
    reviewLabel: 'Open DLP response flow',
    emptyCopy: 'DLP incidents and linked alert summaries appear here when protection rules fire.',
  },
  phishing: {
    label: 'Phishing incident',
    subtitle: 'Suspicious destination and analyst response context',
    badgeTone: 'danger',
    reviewLabel: 'Open phishing response flow',
    emptyCopy: 'Phishing alerts and analyst guidance appear here when suspicious sites are detected.',
  },
}

const EMPTY_RULE = {
  name: '',
  description: '',
  rule_type: 'system',
  condition: 'cpu_percent_gt',
  threshold: '',
  machine_id: 'all',
  severity: 'medium',
  enabled: 1,
}

function normalizeText(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

function formatDateTime(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return String(value)
  }
}

function formatAgo(value) {
  if (!value) return '-'
  const ms = new Date(value).getTime()
  if (!Number.isFinite(ms)) return '-'
  const diff = Math.max(0, Date.now() - ms)
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return formatDateTime(value)
}

function severityTone(value) {
  if (value === 'critical' || value === 'high') return 'danger'
  if (value === 'medium' || value === 'warning') return 'warning'
  if (value === 'low' || value === 'info') return 'success'
  return 'default'
}

function policyActionLabel(item) {
  if (item?.action_taken === 'block_transfer' || item?.action_result === 'blocked' || item?.result === 'blocked') return 'Blocked automatically'
  if (item?.action_taken === 'warn_user' || item?.warning_shown) return 'Allowed with warning'
  return item?.acknowledged ? 'Reviewed' : 'Needs review'
}

function plainDlpActivity(item) {
  const destination = String(item?.destination_label || item?.destination || item?.destination_type || '').toLowerCase()
  if (destination.includes('usb')) return 'Copied to USB'
  if (destination.includes('cloud')) return 'Uploaded to cloud'
  if (destination.includes('print')) return 'Printed document'
  if (destination.includes('clipboard')) return 'Copied through clipboard'
  if (destination.includes('email')) return 'Attached to email'
  if (destination.includes('local')) return 'Moved outside protected folder'
  return 'Sensitive file activity'
}

function dlpSensitivityLabel(item) {
  if (item?.enterprise_label) return item.enterprise_label
  const findings = Array.isArray(item?.findings) ? item.findings : []
  return findings[0]?.type ? String(findings[0].type).replace(/_/g, ' ') : 'Sensitive data'
}

function parseStructuredDetails(value) {
  if (typeof value !== 'string') return null
  const text = value.trim()
  if (!text || (!text.startsWith('{') && !text.startsWith('['))) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

function overlapScore(a, b) {
  const left = normalizeText(a)
  const right = normalizeText(b)
  if (!left || !right) return 0
  let score = 0
  if (left === right) score += 5
  if (left.includes(right) || right.includes(left)) score += 3
  const tokensLeft = new Set(left.split(' ').filter((item) => item.length > 4))
  const tokensRight = new Set(right.split(' ').filter((item) => item.length > 4))
  let overlap = 0
  tokensLeft.forEach((item) => {
    if (tokensRight.has(item)) overlap += 1
  })
  score += Math.min(overlap, 3)
  return score
}

function scoreTimeDistance(left, right) {
  const a = new Date(left || '').getTime()
  const b = new Date(right || '').getTime()
  if (!Number.isFinite(a) || !Number.isFinite(b)) return 0
  const diff = Math.abs(a - b)
  if (diff <= 5 * 60 * 1000) return 4
  if (diff <= 30 * 60 * 1000) return 3
  if (diff <= 2 * 60 * 60 * 1000) return 2
  if (diff <= 24 * 60 * 60 * 1000) return 1
  return 0
}

function detectAlertSource(log) {
  const summary = `${log?.rule_name || ''} ${log?.message || ''} ${log?.details || ''}`
  const normalized = normalizeText(summary)
  if (normalized.includes('phishing')) return 'phishing'
  if (normalized.includes('sensitive') || normalized.includes('dlp') || normalized.includes('policy') || normalized.includes('blocked')) return 'dlp'
  return 'generic'
}

function bestDlpMatch(log, incidents, events) {
  const source = detectAlertSource(log)
  if (source !== 'dlp') return null
  const relatedEvents = events.filter((item) => !log.machine_id || item.machine_id === log.machine_id)
  const bestEvent = relatedEvents.reduce((best, item) => {
    const score =
      overlapScore(`${log.message} ${log.details}`, `${item.file_name || ''} ${item.file_path || ''} ${item.destination_label || ''}`) +
      scoreTimeDistance(log.triggered_at, item.timestamp)
    if (score > best.score) return { item, score }
    return best
  }, { item: null, score: 0 })
  const bestIncident = incidents.reduce((best, item) => {
    if (log.machine_id && item.machine_id && log.machine_id !== item.machine_id) return best
    const score =
      overlapScore(`${log.message} ${log.details}`, `${item.title || ''} ${item.summary || ''}`) +
      scoreTimeDistance(log.triggered_at, item.last_seen || item.updated_at || item.created_at)
    if (score > best.score) return { item, score }
    return best
  }, { item: null, score: 0 })
  const incident = bestIncident.score >= 3 ? bestIncident.item : null
  const event = bestEvent.score >= 3 ? bestEvent.item : null
  if (!incident && !event) return null
  return { incident, event }
}

function bestPhishingMatch(log, incidents) {
  const source = detectAlertSource(log)
  if (source !== 'phishing') return null
  const best = incidents.reduce((current, item) => {
    if (log.machine_id && item.machine_id && log.machine_id !== item.machine_id) return current
    const score =
      overlapScore(`${log.message} ${log.details}`, `${item.title || ''} ${item.summary || ''} ${item.domain || ''} ${item.url || ''}`) +
      scoreTimeDistance(log.triggered_at, item.last_seen || item.updated_at || item.created_at) +
      (log.details && item.domain && normalizeText(log.details).includes(normalizeText(item.domain)) ? 4 : 0)
    if (score > current.score) return { item, score }
    return current
  }, { item: null, score: 0 })
  return best.score >= 3 ? best.item : null
}

function StatCard({ icon, label, value, sub, tone = 'var(--brand)' }) {
  return (
    <div className="stat-card machine-calm-card machine-calm-stat control-stat alerts-stat-card">
      <div className="alerts-stat-head">
        <span className="alerts-stat-icon" style={{ color: tone }}>{icon}</span>
        <span className="stat-label">{label}</span>
      </div>
      <div className="stat-value" style={{ color: tone }}>{value}</div>
      <div className="stat-sub">{sub}</div>
    </div>
  )
}

function DetailValue({ label, children }) {
  return (
    <div style={{ display: 'grid', gap: 4 }}>
      <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em' }}>{label}</span>
      <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>{children}</div>
    </div>
  )
}

export default function Alerts() {
  const navigate = useNavigate()
  const { get, post, put, patch, del } = useApi()
  const { push } = useNotifications()
  const { setPageContext, clearPageContext } = usePageContext()

  const [logs, setLogs] = useState([])
  const [rules, setRules] = useState([])
  const [stats, setStats] = useState({})
  const [dlpIncidents, setDlpIncidents] = useState([])
  const [dlpEvents, setDlpEvents] = useState([])
  const [phishingIncidents, setPhishingIncidents] = useState([])
  const [workspaceTab, setWorkspaceTab] = useState('inbox')
  const [filter, setFilter] = useState({ source: 'all', severity: '', unreadOnly: false, search: '' })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [partialError, setPartialError] = useState('')

  const [selectedAlert, setSelectedAlert] = useState(null)
  const [selectedDetail, setSelectedDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailSaving, setDetailSaving] = useState(false)
  const [detailForm, setDetailForm] = useState({ state: 'new', severity: 'medium', assignee: '', disposition: '', resolution_reason: '', note: '' })
  const [busyAction, setBusyAction] = useState('')

  const [editing, setEditing] = useState(null)
  const [editId, setEditId] = useState(null)
  const [savingRule, setSavingRule] = useState(false)

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError('')
    setPartialError('')
    try {
      const results = await Promise.allSettled([
        get('/api/alerts/logs?limit=200'),
        get('/api/alerts/rules'),
        get('/api/alerts/stats'),
        get('/api/dlp/incidents?limit=80'),
        get('/api/dlp/events?limit=200'),
        get('/api/phishing/incidents?limit=80'),
      ])

      const failures = []
      let successCount = 0

      const readValue = (index) => results[index]

      const logsRes = readValue(0)
      if (logsRes.status === 'fulfilled') {
        successCount += 1
        setLogs(Array.isArray(logsRes.value) ? logsRes.value : (logsRes.value?.alerts || logsRes.value?.logs || []))
      } else {
        setLogs([])
        failures.push('alerts')
      }

      const rulesRes = readValue(1)
      if (rulesRes.status === 'fulfilled') {
        successCount += 1
        setRules(Array.isArray(rulesRes.value) ? rulesRes.value : [])
      } else {
        setRules([])
        failures.push('rules')
      }

      const statsRes = readValue(2)
      if (statsRes.status === 'fulfilled') {
        successCount += 1
        setStats(statsRes.value || {})
      } else {
        setStats({})
        failures.push('stats')
      }

      const dlpIncidentsRes = readValue(3)
      if (dlpIncidentsRes.status === 'fulfilled') {
        successCount += 1
        setDlpIncidents(dlpIncidentsRes.value?.items || dlpIncidentsRes.value?.incidents || [])
      } else {
        setDlpIncidents([])
        failures.push('DLP incidents')
      }

      const dlpEventsRes = readValue(4)
      if (dlpEventsRes.status === 'fulfilled') {
        successCount += 1
        setDlpEvents(dlpEventsRes.value?.events || dlpEventsRes.value?.items || [])
      } else {
        setDlpEvents([])
        failures.push('DLP events')
      }

      const phishingIncidentsRes = readValue(5)
      if (phishingIncidentsRes.status === 'fulfilled') {
        successCount += 1
        setPhishingIncidents(phishingIncidentsRes.value?.items || phishingIncidentsRes.value?.incidents || [])
      } else {
        setPhishingIncidents([])
        failures.push('phishing incidents')
      }

      if (!successCount) throw new Error('Failed to load alerts workspace')
      if (failures.length) setPartialError(`Some inbox context could not load: ${failures.join(', ')}`)
    } catch (err) {
      setError(err?.message || 'Failed to load alerts workspace')
    } finally {
      setLoading(false)
    }
  }, [get])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  useEffect(() => {
    setPageContext('Tenant Scope', 'Alerts')
    return () => clearPageContext()
  }, [setPageContext, clearPageContext])

  useWsListener(useCallback((msg) => {
    if (['new_alert', 'dlp_update', 'dlp_incident_update', 'phishing_incident_update', 'phishing_update'].includes(msg.type)) {
      loadAll()
    }
  }, [loadAll]))

  const inboxItems = useMemo(() => logs.map((log) => {
    const structuredDetails = parseStructuredDetails(log.details)
    const source = detectAlertSource(log)
    const dlpMatch = bestDlpMatch(log, dlpIncidents, dlpEvents)
    const phishingMatch = bestPhishingMatch(log, phishingIncidents)
    const incident = source === 'phishing' ? phishingMatch : dlpMatch?.incident || null
    const dlpEvent = dlpMatch?.event || null
    const title = source === 'phishing'
      ? (incident?.title || log.message)
      : source === 'dlp'
        ? (incident?.title || log.message)
        : log.message
    const summary = source === 'phishing'
      ? (incident?.summary || log.details || 'Review the suspicious browsing activity.')
      : source === 'dlp'
        ? (incident?.summary || log.details || dlpEvent?.file_path || 'Review the sensitive activity details.')
        : (typeof structuredDetails === 'object' ? JSON.stringify(structuredDetails) : log.details || 'Review the alert details.')

    return {
      ...log,
      source,
      sourceMeta: SOURCE_META[source] || SOURCE_META.generic,
      title,
      summary,
      incident,
      dlpEvent,
      eventId: source === 'dlp' ? (dlpEvent?.id || dlpEvent?.event_id || dlpEvent?.source_event_id || null) : null,
      responseStatus: source === 'phishing'
        ? (incident?.state || (log.acknowledged ? 'reviewed' : 'open'))
        : source === 'dlp'
          ? (incident?.state || (dlpEvent?.acknowledged ? 'reviewed' : 'open'))
          : (log.acknowledged ? 'reviewed' : 'open'),
      occurredAt: log.triggered_at || incident?.last_seen || incident?.updated_at || incident?.created_at,
      machineLabel: log.hostname || log.machine_id || incident?.machine_name || incident?.hostname || '-',
      userLabel: incident?.actor_username || incident?.username || dlpEvent?.actor_username || '-',
      detailPayload: structuredDetails,
    }
  }), [dlpEvents, dlpIncidents, logs, phishingIncidents])

  const filteredInbox = useMemo(() => inboxItems.filter((item) => {
    if (filter.source !== 'all' && item.source !== filter.source) return false
    if (filter.severity && String(item.severity || '').toLowerCase() !== filter.severity) return false
    if (filter.unreadOnly && item.acknowledged) return false
    if (filter.search) {
      const haystack = normalizeText(`${item.title} ${item.summary} ${item.machineLabel} ${item.userLabel} ${item.rule_name}`)
      if (!haystack.includes(normalizeText(filter.search))) return false
    }
    return true
  }), [filter, inboxItems])

  const pageState = loading ? 'loading' : error ? 'error' : partialError ? 'partial' : 'ready'
  const unreadCount = logs.filter((item) => !item.acknowledged).length
  const openDlp = dlpIncidents.filter((item) => (item.state || 'open') !== 'resolved').length
  const openPhishing = phishingIncidents.filter((item) => (item.state || 'open') !== 'resolved').length
  const activeRules = rules.filter((item) => item.enabled).length

  const openAlert = useCallback(async (item) => {
      setSelectedAlert(item)
      setSelectedDetail(item.incident || item.dlpEvent || null)
      setDetailForm({
        state: item.incident?.state || 'new',
        severity: item.incident?.severity || item.severity || 'medium',
        assignee: item.incident?.assignee || '',
        disposition: item.incident?.metadata?.disposition || '',
        resolution_reason: item.incident?.metadata?.resolution_reason || '',
        note: '',
      })

    if (item.source === 'dlp' && item.incident?.id) {
      setDetailLoading(true)
      try {
        const detail = await get(`/api/dlp/incidents/${item.incident.id}`)
        setSelectedDetail(detail)
          setDetailForm({
            state: detail?.state || 'new',
            severity: detail?.severity || item.severity || 'medium',
            assignee: detail?.assignee || '',
            disposition: detail?.metadata?.disposition || '',
            resolution_reason: detail?.metadata?.resolution_reason || '',
            note: '',
          })
      } catch {
        setSelectedDetail(item.incident)
      } finally {
        setDetailLoading(false)
      }
    } else if (item.source === 'phishing' && item.incident?.id) {
      setDetailLoading(true)
      try {
        const detail = await get(`/api/phishing/incidents/${item.incident.id}`)
        setSelectedDetail(detail)
        setDetailForm({
          state: detail?.state || 'open',
          severity: detail?.severity || item.severity || 'medium',
          assignee: detail?.assignee || '',
          note: '',
        })
      } catch {
        setSelectedDetail(item.incident)
      } finally {
        setDetailLoading(false)
      }
    } else {
      setDetailLoading(false)
    }
  }, [get])

  const closeDrawer = useCallback(() => {
    setSelectedAlert(null)
      setSelectedDetail(null)
      setDetailLoading(false)
      setDetailSaving(false)
      setBusyAction('')
      setDetailForm({ state: 'new', severity: 'medium', assignee: '', disposition: '', resolution_reason: '', note: '' })
    }, [])

  const acknowledgeAlert = useCallback(async (logId, successTitle = 'Alert acknowledged') => {
    if (!logId) return
    setBusyAction(`alert-${logId}`)
    try {
      await post(`/api/alerts/logs/${logId}/acknowledge`, {})
      push({ type: 'success', title: successTitle })
      await loadAll()
      setSelectedAlert((prev) => (prev?.id === logId ? { ...prev, acknowledged: true } : prev))
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setBusyAction('')
    }
  }, [loadAll, post, push])

  const acknowledgeAll = useCallback(async () => {
    setBusyAction('ack-all')
    try {
      await post('/api/alerts/logs/acknowledge-all', {})
      push({ type: 'success', title: 'All alerts acknowledged' })
      await loadAll()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setBusyAction('')
    }
  }, [loadAll, post, push])

  const acknowledgeDlpEvent = useCallback(async (eventId) => {
    if (!eventId) return
    setBusyAction(`dlp-${eventId}`)
    try {
      await put(`/api/dlp/events/${eventId}/acknowledge`)
      push({ type: 'success', title: 'DLP event marked safe' })
      await loadAll()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setBusyAction('')
    }
  }, [loadAll, push, put])

  const saveIncidentReview = useCallback(async () => {
    if (!selectedAlert?.incident?.id) return
    setDetailSaving(true)
    try {
        const payload = {
          state: detailForm.state,
          severity: detailForm.severity,
          assignee: detailForm.assignee,
          disposition: detailForm.disposition,
          resolution_reason: detailForm.resolution_reason,
          note: detailForm.note,
        }
      if (selectedAlert.source === 'dlp') {
        const detail = await put(`/api/dlp/incidents/${selectedAlert.incident.id}`, payload)
        setSelectedDetail(detail)
      } else if (selectedAlert.source === 'phishing') {
        const detail = await put(`/api/phishing/incidents/${selectedAlert.incident.id}`, payload)
        setSelectedDetail(detail)
      }
      push({ type: 'success', title: 'Incident review saved' })
      setDetailForm((prev) => ({ ...prev, note: '' }))
      await loadAll()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setDetailSaving(false)
    }
  }, [detailForm, loadAll, push, put, selectedAlert])

  const purgeAcknowledged = useCallback(async () => {
    setBusyAction('purge')
    try {
      await del('/api/alerts/logs/acknowledged/purge')
      push({ type: 'success', title: 'Acknowledged alerts purged' })
      await loadAll()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setBusyAction('')
    }
  }, [del, loadAll, push])

  const deleteLog = useCallback(async (id) => {
    setBusyAction(`delete-${id}`)
    try {
      await del(`/api/alerts/logs/${id}`)
      push({ type: 'success', title: 'Alert deleted' })
      if (selectedAlert?.id === id) closeDrawer()
      await loadAll()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setBusyAction('')
    }
  }, [closeDrawer, del, loadAll, push, selectedAlert])

  const toggleRule = async (rule) => {
    try {
      await patch(`/api/alerts/rules/${rule.id}/toggle?enabled=${!rule.enabled}`)
      await loadAll()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    }
  }

  const deleteRule = async (rule) => {
    if (!window.confirm(`Delete rule "${rule.name}"?`)) return
    try {
      await del(`/api/alerts/rules/${rule.id}`)
      push({ type: 'success', title: 'Rule deleted' })
      await loadAll()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    }
  }

  const openCreate = () => {
    setEditId(null)
    setEditing({ ...EMPTY_RULE })
  }

  const openEdit = (rule) => {
    setEditId(rule.id)
    setEditing({
      name: rule.name || '',
      description: rule.description || '',
      rule_type: rule.rule_type || 'system',
      condition: rule.condition || '',
      threshold: rule.threshold || '',
      machine_id: rule.machine_id || 'all',
      severity: rule.severity || 'medium',
      enabled: rule.enabled ? 1 : 0,
    })
  }

  const saveRule = async () => {
    if (!editing?.name?.trim()) {
      push({ type: 'error', title: 'Rule name is required' })
      return
    }
    setSavingRule(true)
    try {
      if (editId) {
        await put(`/api/alerts/rules/${editId}`, editing)
        push({ type: 'success', title: 'Rule updated' })
      } else {
        await post('/api/alerts/rules', editing)
        push({ type: 'success', title: 'Rule created' })
      }
      setEditing(null)
      setEditId(null)
      await loadAll()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setSavingRule(false)
    }
  }

  const jumpToResponseFlow = useCallback((item) => {
    if (!item) return
    if (item.source === 'dlp') {
      navigate('/dlp')
      return
    }
    if (item.source === 'phishing') {
      navigate('/phishing')
      return
    }
    if (item.machine_id) {
      navigate(`/machines/${item.machine_id}`)
    }
  }, [navigate])

  const conditionsForType = CONDITIONS[editing?.rule_type] || []

  return (
    <div className="fade-in control-shell">
      <div className="page-header machine-calm-header analytics-hero control-hero">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <AlertsIcon size={24} />
          </div>
          <div>
            <div className="page-title">Alerts Workspace</div>
            <div className="page-subtitle">A merged analyst inbox for generic rules, DLP incidents, and phishing response context.</div>
          </div>
        </div>
        <div className="control-actions">
          <button className="btn btn-outline machine-calm-btn btn-sm" onClick={loadAll}>Refresh</button>
          {unreadCount > 0 && (
            <button className="btn btn-primary btn-sm" onClick={acknowledgeAll} disabled={busyAction === 'ack-all'}>
              {busyAction === 'ack-all' ? 'Updating...' : 'Acknowledge all'}
            </button>
          )}
          <button className="btn btn-outline machine-calm-btn btn-sm" onClick={purgeAcknowledged} disabled={busyAction === 'purge'}>
            {busyAction === 'purge' ? 'Purging...' : 'Purge read'}
          </button>
        </div>
      </div>

      <PageStateView
        state={pageState}
        title={error ? 'Unable to load alerts workspace' : 'Alerts loaded with missing context'}
        message={error || partialError || 'Some alert context could not be loaded.'}
        onRetry={loadAll}
      >
        <div className="stats-grid phishing-stats-grid">
          <StatCard icon={<AlertsIcon size={18} />} label="Unread alerts" value={unreadCount} sub="Generic and incident-linked queue items" tone="var(--red)" />
          <StatCard icon={<DlpIcon size={18} />} label="Open DLP incidents" value={openDlp} sub="Sensitive activity that still needs analyst review" tone="var(--amber)" />
          <StatCard icon={<PhishingIcon size={18} />} label="Open phishing incidents" value={openPhishing} sub="Suspicious destinations still waiting for follow-up" tone="var(--machine-calm-1)" />
          <StatCard icon={<AlertsIcon size={18} />} label="Active alert rules" value={activeRules} sub="Rules still feeding this queue" tone="var(--brand)" />
        </div>

        <div className="control-banner">
          Analysts can clear the generic queue here, mark linked DLP events safe, capture phishing review notes, and then jump into the deeper DLP or phishing workspaces only when the full response flow is needed.
        </div>

        <div className="tab-group analytics-tabs" style={{ alignSelf: 'flex-start', display: 'flex' }}>
          {WORKSPACE_TABS.map((tab) => (
            <button key={tab.id} className={`tab-btn${workspaceTab === tab.id ? ' active' : ''}`} onClick={() => setWorkspaceTab(tab.id)}>
              {tab.label}
            </button>
          ))}
        </div>

        {workspaceTab === 'inbox' && (
          <div className="control-grid">
            <div className="filter-bar analytics-filter-panel machine-calm-card control-filter">
              <select className="input-field machine-calm-search control-field" value={filter.source} onChange={(e) => setFilter((prev) => ({ ...prev, source: e.target.value }))}>
                {SOURCE_FILTERS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
              <select className="input-field machine-calm-search control-field" value={filter.severity} onChange={(e) => setFilter((prev) => ({ ...prev, severity: e.target.value }))}>
                <option value="">All severity</option>
                {SEVERITIES.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <input
                className="input-field machine-calm-search control-field"
                placeholder="Search title, machine, user, or rule"
                value={filter.search}
                onChange={(e) => setFilter((prev) => ({ ...prev, search: e.target.value }))}
              />
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-2)' }}>
                <input type="checkbox" checked={filter.unreadOnly} onChange={(e) => setFilter((prev) => ({ ...prev, unreadOnly: e.target.checked }))} />
                Unread only
              </label>
              <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-3)' }}>{filteredInbox.length} queue items</span>
            </div>

            <div className="grid-2 alerts-inbox-layout">
              <SimpleSection
                title="Queue"
                subtitle="Alert cards stay human-readable first, then reveal the linked DLP or phishing context when available."
              >
                <div className="alerts-inbox-list">
                  {filteredInbox.map((item) => (
                    <button key={item.id} type="button" className={`alerts-inbox-card${selectedAlert?.id === item.id ? ' alerts-inbox-card-active' : ''}`} onClick={() => openAlert(item)}>
                      <div className="alerts-inbox-card-head">
                        <div>
                          <div className="alerts-inbox-card-meta">
                            <SimpleBadge tone={severityTone(item.severity)}>{item.severity || 'medium'}</SimpleBadge>
                            <SimpleBadge tone={item.sourceMeta.badgeTone}>{item.sourceMeta.label}</SimpleBadge>
                            {!item.acknowledged && <SimpleBadge tone="warning">Unread</SimpleBadge>}
                          </div>
                          <div className="alerts-inbox-title">{item.title}</div>
                          <div className="alerts-inbox-sub">{item.summary}</div>
                        </div>
                        <div className="alerts-inbox-time">{formatAgo(item.occurredAt)}</div>
                      </div>

                      <div className="alerts-inbox-foot">
                        <span><strong>Machine:</strong> {item.machineLabel}</span>
                        <span><strong>User:</strong> {item.userLabel}</span>
                        <span><strong>Status:</strong> {item.responseStatus}</span>
                      </div>
                    </button>
                  ))}

                  {!filteredInbox.length && (
                    <div className="control-empty">
                      {(SOURCE_META[filter.source] || SOURCE_META.generic).emptyCopy}
                    </div>
                  )}
                </div>
              </SimpleSection>

              <SimpleSection
                title={selectedAlert ? selectedAlert.title : 'Inbox preview'}
                subtitle={selectedAlert ? selectedAlert.sourceMeta.subtitle : 'Pick an alert to review the context, actions, and linked response flow.'}
                action={selectedAlert ? (
                  <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => jumpToResponseFlow(selectedAlert)}>
                    {selectedAlert.sourceMeta.reviewLabel}
                  </button>
                ) : null}
              >
                {selectedAlert ? (
                  <div className="alerts-preview-grid">
                    <SimpleKeyValue
                      items={[
                        { label: 'Triggered', value: formatDateTime(selectedAlert.occurredAt) },
                        { label: 'Machine', value: selectedAlert.machineLabel },
                        { label: 'Rule', value: selectedAlert.rule_name || selectedAlert.sourceMeta.label },
                        { label: 'Queue status', value: selectedAlert.acknowledged ? 'Acknowledged' : 'Unread' },
                      ]}
                    />

                    <DetailValue label="Analyst summary">{selectedAlert.summary}</DetailValue>

                    {selectedAlert.source === 'dlp' && (
                      <div className="phishing-detail-grid">
                        <DetailValue label="Activity">{plainDlpActivity(selectedAlert.dlpEvent || selectedAlert.incident)}</DetailValue>
                        <DetailValue label="Sensitive data">{dlpSensitivityLabel(selectedAlert.dlpEvent || selectedAlert.incident)}</DetailValue>
                        <DetailValue label="Policy action">{policyActionLabel(selectedAlert.dlpEvent || selectedAlert.incident)}</DetailValue>
                      </div>
                    )}

                    {selectedAlert.source === 'phishing' && (
                      <div className="phishing-detail-grid">
                        <DetailValue label="Domain">{selectedAlert.incident?.domain || '-'}</DetailValue>
                        <DetailValue label="URL">{selectedAlert.incident?.url || '-'}</DetailValue>
                        <DetailValue label="Response state">{selectedAlert.incident?.state || 'open'}</DetailValue>
                      </div>
                    )}

                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {!selectedAlert.acknowledged && (
                        <button className="btn btn-primary btn-sm" onClick={() => acknowledgeAlert(selectedAlert.id)} disabled={busyAction === `alert-${selectedAlert.id}`}>
                          {busyAction === `alert-${selectedAlert.id}` ? 'Updating...' : 'Acknowledge alert'}
                        </button>
                      )}
                      {selectedAlert.source === 'dlp' && selectedAlert.eventId && (
                        <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => acknowledgeDlpEvent(selectedAlert.eventId)} disabled={busyAction === `dlp-${selectedAlert.eventId}`}>
                          {busyAction === `dlp-${selectedAlert.eventId}` ? 'Updating...' : 'Mark DLP event safe'}
                        </button>
                      )}
                      <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => openAlert(selectedAlert)}>Open review drawer</button>
                      <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => jumpToResponseFlow(selectedAlert)}>{selectedAlert.sourceMeta.reviewLabel}</button>
                      {selectedAlert.machine_id && (
                        <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => navigate(`/machines/${selectedAlert.machine_id}`)}>
                          Open machine
                        </button>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="control-empty">
                    Choose an inbox item to see its summary, related incident context, and direct response actions.
                  </div>
                )}
              </SimpleSection>
            </div>
          </div>
        )}

        {workspaceTab === 'rules' && (
          <div className="control-grid">
            <SimpleSection
              title="Alert rules"
              subtitle="Keep rule authoring inside the same calm control-shell style, but separate it from the analyst inbox."
              action={<button className="btn btn-primary btn-sm" onClick={openCreate}>New rule</button>}
            >
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table machine-calm-table">
                  <thead>
                    <tr>
                      <th>Rule</th>
                      <th>Type</th>
                      <th>Condition</th>
                      <th>Threshold</th>
                      <th>Severity</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rules.map((rule) => (
                      <tr key={rule.id}>
                        <td>
                          <div style={{ fontWeight: 700 }}>{rule.name}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{rule.description || 'No description'}</div>
                        </td>
                        <td><SimpleBadge tone="default">{rule.rule_type}</SimpleBadge></td>
                        <td className="mono" style={{ fontSize: 11 }}>{rule.condition}</td>
                        <td className="mono" style={{ fontSize: 11 }}>{rule.threshold || '-'}</td>
                        <td><SimpleBadge tone={severityTone(rule.severity)}>{rule.severity}</SimpleBadge></td>
                        <td>
                          <button type="button" className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => toggleRule(rule)}>
                            {rule.enabled ? 'Active' : 'Paused'}
                          </button>
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                            <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => openEdit(rule)}>Edit</button>
                            <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => deleteRule(rule)}>Delete</button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {!rules.length && (
                      <tr>
                        <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-3)' }}>No alert rules configured yet.</td>
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
        title={selectedAlert?.title || 'Alert review'}
        subtitle={selectedAlert ? `${selectedAlert.sourceMeta.label} on ${selectedAlert.machineLabel}` : ''}
        badges={selectedAlert ? [
          { label: selectedAlert.severity || 'medium' },
          { label: selectedAlert.acknowledged ? 'Acknowledged' : 'Unread' },
          { label: selectedAlert.sourceMeta.label },
        ] : []}
        onClose={closeDrawer}
        footer={selectedAlert ? (
          <>
            {!selectedAlert.acknowledged && (
              <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => acknowledgeAlert(selectedAlert.id)} disabled={busyAction === `alert-${selectedAlert.id}`}>
                {busyAction === `alert-${selectedAlert.id}` ? 'Updating...' : 'Acknowledge alert'}
              </button>
            )}
            {selectedAlert.source === 'dlp' && selectedAlert.eventId && (
              <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => acknowledgeDlpEvent(selectedAlert.eventId)} disabled={busyAction === `dlp-${selectedAlert.eventId}`}>
                {busyAction === `dlp-${selectedAlert.eventId}` ? 'Updating...' : 'Mark DLP event safe'}
              </button>
            )}
            {(selectedAlert.source === 'dlp' || selectedAlert.source === 'phishing') && selectedAlert.incident?.id && (
              <button className="btn btn-primary btn-sm" onClick={saveIncidentReview} disabled={detailSaving}>
                {detailSaving ? 'Saving...' : 'Save review'}
              </button>
            )}
          </>
        ) : null}
      >
        {selectedAlert && (
          <div className="alerts-drawer-grid">
            <SimpleSection title="Alert context" subtitle="What the generic alert log knows about this event right now.">
              <SimpleKeyValue
                items={[
                  { label: 'Rule', value: selectedAlert.rule_name || selectedAlert.sourceMeta.label },
                  { label: 'Machine', value: selectedAlert.machineLabel },
                  { label: 'User', value: selectedAlert.userLabel },
                  { label: 'Triggered', value: formatDateTime(selectedAlert.occurredAt) },
                  { label: 'Details', value: typeof selectedAlert.detailPayload === 'object' ? JSON.stringify(selectedAlert.detailPayload) : (selectedAlert.details || '-') },
                ]}
              />
            </SimpleSection>

            {selectedAlert.source === 'generic' && (
              <SimpleSection title="Next step" subtitle="Generic alerts keep the response lightweight.">
                <div className="phishing-guide-steps">
                  <div>1. Acknowledge the queue item once you understand the condition that fired.</div>
                  <div>2. Open the machine if you need broader activity context.</div>
                  <div>3. Adjust the source rule only when the pattern is noisy or thresholds are wrong.</div>
                </div>
              </SimpleSection>
            )}

              {(selectedAlert.source === 'dlp' || selectedAlert.source === 'phishing') && (
                <SimpleSection title="Linked incident" subtitle={detailLoading ? 'Loading incident details...' : 'Use the linked incident data to review and document the response without leaving this page.'}>
                  {detailLoading ? (
                    <div className="control-empty">Loading incident detail...</div>
                  ) : (
                  <div className="alerts-drawer-grid">
                    <SimpleKeyValue
                      items={[
                        { label: 'Incident ID', value: String(selectedAlert.incident?.id || selectedDetail?.id || '-') },
                        { label: 'State', value: selectedDetail?.state || selectedAlert.incident?.state || 'open' },
                        { label: 'Severity', value: selectedDetail?.severity || selectedAlert.incident?.severity || selectedAlert.severity || 'medium' },
                        { label: 'Assignee', value: selectedDetail?.assignee || selectedAlert.incident?.assignee || '-' },
                      ]}
                    />

                    <DetailValue label="Incident summary">{selectedDetail?.summary || selectedAlert.summary}</DetailValue>

                      {selectedAlert.source === 'dlp' && (
                        <>
                          <DetailValue label="Sensitive action">{plainDlpActivity(selectedAlert.dlpEvent || selectedDetail)}</DetailValue>
                          <DetailValue label="Data involved">{dlpSensitivityLabel(selectedAlert.dlpEvent || selectedDetail)}</DetailValue>
                          <DetailValue label="Policy result">{policyActionLabel(selectedAlert.dlpEvent || selectedDetail)}</DetailValue>
                          <DetailValue label="Recommended next steps">{(selectedDetail?.recommended_actions || []).join(' ') || 'Review the newest endpoint activity and document the analyst decision.'}</DetailValue>
                        </>
                      )}

                    {selectedAlert.source === 'phishing' && (
                      <>
                        <DetailValue label="Domain">{selectedDetail?.domain || selectedAlert.incident?.domain || '-'}</DetailValue>
                        <DetailValue label="URL">{selectedDetail?.url || selectedAlert.incident?.url || '-'}</DetailValue>
                        <DetailValue label="Warning shown">{selectedDetail?.warning_shown ? 'Yes' : 'No'}</DetailValue>
                      </>
                    )}
                  </div>
                )}
                </SimpleSection>
              )}

              {selectedAlert.source === 'dlp' && selectedAlert.incident?.id && !detailLoading && (
                <SimpleSection title="DLP evidence" subtitle="Stored evidence, related activity, notes, and timeline from the linked DLP incident.">
                  <div className="alerts-drawer-grid">
                    <DetailValue label="Evidence summary">
                      {(selectedDetail?.evidence_summary || []).map((group) => `${group.title}: ${(group.items || []).length}`).join(' · ') || 'No evidence summary stored'}
                    </DetailValue>
                    <DetailValue label="Related activity">
                      {(selectedDetail?.related_activity || []).slice(0, 3).map((entry) => `${entry.file_name || 'Sensitive content'} ${entry.action_result || 'observed'} via ${entry.destination_type || entry.channel}`).join(' · ') || 'No linked related activity'}
                    </DetailValue>
                    <DetailValue label="Timeline">
                      {(selectedDetail?.timeline || []).slice(0, 3).map((entry) => `${entry.action} at ${formatDateTime(entry.created_at)}`).join(' · ') || 'No timeline yet'}
                    </DetailValue>
                    <DetailValue label="Analyst notes">
                      {(selectedDetail?.notes || []).slice(-2).map((entry) => entry.note || '-').join(' · ') || 'No analyst notes yet'}
                    </DetailValue>
                  </div>
                </SimpleSection>
              )}

              {(selectedAlert.source === 'dlp' || selectedAlert.source === 'phishing') && selectedAlert.incident?.id && (
                <SimpleSection title="Review action" subtitle="Update the incident status, severity, assignee, and analyst note from the inbox.">
                  <div className="phishing-form-grid">
                    <label className="phishing-field">
                    <span>State</span>
                    <select className="input-field control-field" value={detailForm.state} onChange={(e) => setDetailForm((prev) => ({ ...prev, state: e.target.value }))}>
                      {(selectedAlert.source === 'dlp' ? DLP_INCIDENT_STATES : PHISHING_INCIDENT_STATES).map((item) => (
                        <option key={item} value={item}>{item}</option>
                      ))}
                    </select>
                  </label>
                  <label className="phishing-field">
                    <span>Severity</span>
                    <select className="input-field control-field" value={detailForm.severity} onChange={(e) => setDetailForm((prev) => ({ ...prev, severity: e.target.value }))}>
                      {SEVERITIES.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                    <label className="phishing-field phishing-field-wide">
                      <span>Assignee</span>
                      <input className="input-field control-field" value={detailForm.assignee} onChange={(e) => setDetailForm((prev) => ({ ...prev, assignee: e.target.value }))} placeholder="SOC analyst" />
                    </label>
                    {selectedAlert.source === 'dlp' && (
                      <>
                        <label className="phishing-field">
                          <span>Disposition</span>
                          <select className="input-field control-field" value={detailForm.disposition} onChange={(e) => setDetailForm((prev) => ({ ...prev, disposition: e.target.value }))}>
                            {DLP_DISPOSITIONS.map((item) => <option key={item.value || 'none'} value={item.value}>{item.label}</option>)}
                          </select>
                        </label>
                        <label className="phishing-field phishing-field-wide">
                          <span>Resolution reason</span>
                          <input className="input-field control-field" value={detailForm.resolution_reason} onChange={(e) => setDetailForm((prev) => ({ ...prev, resolution_reason: e.target.value }))} placeholder="Why this case was contained, approved, false positive, or escalated." />
                        </label>
                      </>
                    )}
                    <label className="phishing-field phishing-field-wide">
                      <span>Analyst note</span>
                      <textarea className="input-field control-field phishing-textarea" value={detailForm.note} onChange={(e) => setDetailForm((prev) => ({ ...prev, note: e.target.value }))} placeholder="Document why this is safe, risky, escalated, or false positive." />
                    </label>
                  </div>
              </SimpleSection>
            )}

            <SimpleSection title="Jump to response flow" subtitle="Open the deeper workspace only when you need the full policy or evidence tooling.">
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => jumpToResponseFlow(selectedAlert)}>
                  {selectedAlert.sourceMeta.reviewLabel}
                </button>
                {selectedAlert.machine_id && (
                  <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => navigate(`/machines/${selectedAlert.machine_id}`)}>
                    Open machine detail
                  </button>
                )}
                <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => deleteLog(selectedAlert.id)} disabled={busyAction === `delete-${selectedAlert.id}`}>
                  {busyAction === `delete-${selectedAlert.id}` ? 'Deleting...' : 'Delete alert log'}
                </button>
              </div>
            </SimpleSection>
          </div>
        )}
      </ActivityDrawer>

      {editing && (
        <div className="activity-drawer-overlay" onClick={() => { setEditing(null); setEditId(null) }}>
          <div className="activity-drawer phishing-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="activity-drawer-header">
              <div>
                <div className="activity-drawer-title">{editId ? 'Edit alert rule' : 'Create alert rule'}</div>
                <div className="activity-drawer-subtitle">Keep the queue meaningful by tuning thresholds, machine scope, and severity.</div>
              </div>
              <button className="btn btn-outline btn-sm" onClick={() => { setEditing(null); setEditId(null) }}>Close</button>
            </div>

            <div className="activity-drawer-body">
              <div className="phishing-form-grid">
                <label className="phishing-field phishing-field-wide">
                  <span>Name</span>
                  <input className="input-field control-field" value={editing.name} onChange={(e) => setEditing((prev) => ({ ...prev, name: e.target.value }))} placeholder="High CPU usage" />
                </label>
                <label className="phishing-field phishing-field-wide">
                  <span>Description</span>
                  <input className="input-field control-field" value={editing.description} onChange={(e) => setEditing((prev) => ({ ...prev, description: e.target.value }))} placeholder="Optional explanation for analysts" />
                </label>
              </div>

              <SimpleSection title="Rule type" subtitle="Select the alert family first so the condition list stays relevant.">
                <ChoiceGrid
                  value={editing.rule_type}
                  onChange={(value) => setEditing((prev) => ({ ...prev, rule_type: value, condition: (CONDITIONS[value] || [''])[0] || '' }))}
                  options={RULE_TYPES.map((item) => ({
                    value: item,
                    label: item,
                    description: `Use ${item} conditions for this alert.`,
                  }))}
                />
              </SimpleSection>

              <div className="phishing-form-grid">
                <label className="phishing-field">
                  <span>Condition</span>
                  <select className="input-field control-field" value={editing.condition} onChange={(e) => setEditing((prev) => ({ ...prev, condition: e.target.value }))}>
                    {conditionsForType.map((item) => <option key={item} value={item}>{item}</option>)}
                    {!conditionsForType.includes(editing.condition) && editing.condition && <option value={editing.condition}>{editing.condition}</option>}
                  </select>
                </label>
                <label className="phishing-field">
                  <span>Severity</span>
                  <select className="input-field control-field" value={editing.severity} onChange={(e) => setEditing((prev) => ({ ...prev, severity: e.target.value }))}>
                    {SEVERITIES.map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </label>
                <label className="phishing-field">
                  <span>Threshold</span>
                  <input className="input-field control-field" value={editing.threshold} onChange={(e) => setEditing((prev) => ({ ...prev, threshold: e.target.value }))} placeholder="85 or 09:00-19:00" />
                </label>
                <label className="phishing-field">
                  <span>Machine scope</span>
                  <input className="input-field control-field" value={editing.machine_id} onChange={(e) => setEditing((prev) => ({ ...prev, machine_id: e.target.value || 'all' }))} placeholder="all" />
                </label>
                <label className="phishing-field">
                  <span>Status</span>
                  <select className="input-field control-field" value={editing.enabled} onChange={(e) => setEditing((prev) => ({ ...prev, enabled: Number(e.target.value) }))}>
                    <option value={1}>Active</option>
                    <option value={0}>Paused</option>
                  </select>
                </label>
              </div>
            </div>

            <div className="activity-drawer-footer">
              <button className="btn btn-outline btn-sm" onClick={() => { setEditing(null); setEditId(null) }}>Cancel</button>
              <button className="btn btn-primary btn-sm" onClick={saveRule} disabled={savingRule}>
                {savingRule ? 'Saving...' : editId ? 'Update rule' : 'Create rule'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
