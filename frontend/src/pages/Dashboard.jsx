import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, useAuth, useWsListener } from '../hooks/useAuth'
import {
  BarChart, Bar, PieChart, Pie, Cell, LineChart, Line,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts'
import {
  MachinesIcon,
  OnlineIcon,
  OfflineIcon,
  TodayIcon,
  AppIcon,
  DomainIcon,
  TimeIcon,
  VisitsIcon,
  AverageHoursIcon,
  ChartBarIcon,
  ChartPieIcon,
  ChartLineIcon,
  AlertsIcon,
  DlpIcon,
  PhishingIcon,
  InputIcon,
  FileIcon,
  NetworkIcon,
} from '../components/ui/OverviewIcons'

const PALETTE = ['#5c8a92', '#7aa39b', '#c3aa87', '#8b95b5', '#6b8bb6', '#8ba79a', '#b8a0be', '#89a97f']
const DASHBOARD_WIDGET_PREF_VERSION = 'v3'
const GLOBAL_DEFAULT_WIDGET_IDS = [
  'total_machines',
  'online_now',
  'offline_now',
  'active_today',
  'top_application',
  'top_domain',
  'productive_time',
  'productive_visits',
  'avg_daily_hours',
  'overview_app_usage',
  'overview_domain_mix',
  'overview_trend',
]
const MACHINE_DEFAULT_WIDGET_IDS = [
  'active_time',
  'browser_visits',
  'productivity_score',
  'top_application',
  'top_domain',
  'peak_hour',
  'machine_app_usage',
  'machine_browser_mix',
  'machine_trend',
]
const WIDGET_MIN_SELECTION = 3

const secsToHM = s => {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h ? `${h}h ${m}m` : `${m}m`
}

const TTip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip machine-calm-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color || 'var(--text-1)', fontWeight: 600, marginTop: 2 }}>
          {p.name}: {p.value}
        </div>
      ))}
    </div>
  )
}

function KpiCard({ label, value, sub, icon: Icon, colorVar }) {
  return (
    <div
      className="stat-card machine-calm-card machine-calm-stat stagger"
      style={{
        color: colorVar,
        borderRadius: 20,
        padding: 18,
        minHeight: 132,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)' }}>{label}</div>
          <div className="stat-sub" style={{ marginTop: 5 }}>{sub}</div>
        </div>
        <div
          className="stat-icon-wrap machine-calm-icon-wrap"
          style={{
            color: colorVar,
          }}
        >
          <Icon width={20} height={20} />
        </div>
      </div>
      <div
        className="stat-value"
        style={{
          color: 'var(--text-1)',
          fontFamily: 'Inter, system-ui, sans-serif',
          fontSize: typeof value === 'number' ? 30 : 22,
          marginTop: 12,
          lineHeight: 1.05,
          letterSpacing: '-0.03em',
          overflowWrap: 'anywhere',
        }}
      >
        {value}
      </div>
    </div>
  )
}

function WidgetCard({ title, subtitle, icon: Icon, colorVar, children, minHeight = 240, footer }) {
  return (
    <div
      className="card machine-calm-card stagger"
      style={{
        borderRadius: 20,
        padding: 18,
        minHeight,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>{title}</div>
          <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 3 }}>{subtitle}</div>
        </div>
        <div
          className="stat-icon-wrap machine-calm-icon-wrap"
          style={{
            color: colorVar,
          }}
        >
          <Icon width={20} height={20} />
        </div>
      </div>
      <div style={{ minHeight: 0 }}>
        {children}
      </div>
      {footer && (
        <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text-3)' }}>
          {footer}
        </div>
      )}
    </div>
  )
}

const storageKey = (user, scopeKey) => {
  const tenantId = user?.tenant_id ?? 'global'
  const username = user?.username ?? 'anonymous'
  return `cropsentinel_dashboard_widgets_${DASHBOARD_WIDGET_PREF_VERSION}:${scopeKey}:${tenantId}:${username}`
}

const legacyStorageKey = user => {
  const tenantId = user?.tenant_id ?? 'global'
  const username = user?.username ?? 'anonymous'
  return `croppro_dashboard_kpis_v1:${tenantId}:${username}`
}

const normalizeWidgetIds = (ids, fallback) => {
  if (!Array.isArray(ids)) return fallback
  const clean = ids.filter(id => typeof id === 'string' && id.trim())
  return clean.length >= WIDGET_MIN_SELECTION ? Array.from(new Set(clean)) : fallback
}

const loadWidgetPreference = (user, scopeKey, fallback) => {
  if (typeof window === 'undefined') return fallback
  try {
    const raw = window.localStorage.getItem(storageKey(user, scopeKey)) || window.localStorage.getItem(legacyStorageKey(user))
    if (!raw) return fallback
    return normalizeWidgetIds(JSON.parse(raw), fallback)
  } catch {
    return fallback
  }
}

const saveWidgetPreference = (user, scopeKey, ids, fallback) => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(storageKey(user, scopeKey), JSON.stringify(normalizeWidgetIds(ids, fallback)))
}

const moveItem = (items, fromIndex, toIndex) => {
  if (toIndex < 0 || toIndex >= items.length) return items
  const next = [...items]
  const [moved] = next.splice(fromIndex, 1)
  next.splice(toIndex, 0, moved)
  return next
}

const safeNum = value => (Number.isFinite(Number(value)) ? Number(value) : 0)

export default function Dashboard() {
  const { user } = useAuth()
  const { get } = useApi()
  const navigate = useNavigate()
  const [overview, setOverview] = useState(null)
  const [machines, setMachines] = useState([])
  const [machineAnalytics, setMachineAnalytics] = useState(null)
  const [machineProductivity, setMachineProductivity] = useState(null)
  const [browserLogsStats, setBrowserLogsStats] = useState(null)
  const [appUsageStats, setAppUsageStats] = useState(null)
  const [inputRows, setInputRows] = useState([])
  const [fileStats, setFileStats] = useState(null)
  const [fileLogs, setFileLogs] = useState([])
  const [networkStats, setNetworkStats] = useState(null)
  const [networkLogs, setNetworkLogs] = useState([])
  const [alertsStats, setAlertsStats] = useState(null)
  const [alertsLogs, setAlertsLogs] = useState([])
  const [dlpStats, setDlpStats] = useState(null)
  const [dlpEvents, setDlpEvents] = useState([])
  const [dlpIncidents, setDlpIncidents] = useState([])
  const [phishingEvents, setPhishingEvents] = useState([])
  const [phishingIncidents, setPhishingIncidents] = useState([])
  const [phishingAllowlists, setPhishingAllowlists] = useState([])
  const [selectedMachineId, setSelectedMachineId] = useState('all')
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [showWidgetEditor, setShowWidgetEditor] = useState(false)
  const [selectedWidgets, setSelectedWidgets] = useState(() => GLOBAL_DEFAULT_WIDGET_IDS)
  const [draftWidgets, setDraftWidgets] = useState(() => GLOBAL_DEFAULT_WIDGET_IDS)
  const refreshRef = useRef(null)

  const scopeKey = selectedMachineId === 'all' ? 'all' : `machine:${selectedMachineId}`
  const scopeFallback = selectedMachineId === 'all' ? GLOBAL_DEFAULT_WIDGET_IDS : MACHINE_DEFAULT_WIDGET_IDS
  const selectedMachine = selectedMachineId === 'all'
    ? null
    : machines.find(m => m.machine_id === selectedMachineId) || null

  const loadData = useCallback(async () => {
    try {
      const machineScope = selectedMachineId === 'all' ? '' : selectedMachineId
      const requests = [
        get('/api/machines'),
        get('/api/analytics/overview'),
        get('/api/alerts/stats'),
        get('/api/alerts/logs?limit=20'),
        get('/api/dlp/stats'),
        get('/api/dlp/events?limit=20'),
        get('/api/dlp/incidents?limit=20'),
        get('/api/phishing/events?limit=20'),
        get('/api/phishing/incidents?limit=20'),
        get('/api/phishing/allowlists'),
        get('/api/files/stats'),
        get('/api/activity/file-logs?limit=20'),
        get('/api/network/stats'),
        get('/api/activity/network-logs?limit=20'),
      ]

      if (machineScope) {
        requests.push(
          get(`/api/analytics/machine/${machineScope}`),
          get(`/api/analytics/productivity/${machineScope}`),
          get(`/api/activity/browser-logs?machine_id=${encodeURIComponent(machineScope)}&limit=20`),
          get(`/api/activity/app-usage?machine_id=${encodeURIComponent(machineScope)}&limit=20`),
          get(`/api/activity/input/${encodeURIComponent(machineScope)}`),
        )
      }

      const results = await Promise.allSettled(requests)
      const valueAt = index => (results[index]?.status === 'fulfilled' ? results[index].value : null)

      const ms = valueAt(0)
      const ov = valueAt(1)
      const alertStats = valueAt(2)
      const alertLogs = valueAt(3)
      const dlpStatsRes = valueAt(4)
      const dlpEventsRes = valueAt(5)
      const dlpIncidentsRes = valueAt(6)
      const phishingEventsRes = valueAt(7)
      const phishingIncidentsRes = valueAt(8)
      const phishingAllowlistsRes = valueAt(9)
      const fileStatsRes = valueAt(10)
      const fileLogsRes = valueAt(11)
      const networkStatsRes = valueAt(12)
      const networkLogsRes = valueAt(13)
      const analytics = machineScope ? valueAt(14) : null
      const productivity = machineScope ? valueAt(15) : null
      const browserLogsRes = machineScope ? valueAt(16) : null
      const appUsageRes = machineScope ? valueAt(17) : null
      const inputRowsRes = machineScope ? valueAt(18) : null

      setMachines(ms || [])
      setOverview(ov)
      setAlertsStats(alertStats)
      setAlertsLogs(Array.isArray(alertLogs) ? alertLogs : (alertLogs?.logs || alertLogs?.items || []))
      setDlpStats(dlpStatsRes)
      setDlpEvents((dlpEventsRes?.events || dlpEventsRes?.items || []))
      setDlpIncidents((dlpIncidentsRes?.items || dlpIncidentsRes?.incidents || dlpIncidentsRes?.data || []))
      setPhishingEvents((phishingEventsRes?.events || []))
      setPhishingIncidents((phishingIncidentsRes?.items || phishingIncidentsRes?.incidents || phishingIncidentsRes?.data || []))
      setPhishingAllowlists((phishingAllowlistsRes?.items || phishingAllowlistsRes || []))
      setFileStats(fileStatsRes)
      setFileLogs((fileLogsRes?.items || fileLogsRes?.files || []))
      setNetworkStats(networkStatsRes)
      setNetworkLogs((networkLogsRes?.items || networkLogsRes?.logs || []))
      setMachineAnalytics(machineScope ? analytics : null)
      setMachineProductivity(machineScope ? productivity : null)
      setBrowserLogsStats(browserLogsRes?.stats || null)
      setAppUsageStats(appUsageRes?.stats || null)
      setInputRows(inputRowsRes?.items || inputRowsRes || [])
      setLastUpdate(new Date())
    } catch {
      // dashboard handles failures through existing page states
    } finally {
      setLoading(false)
    }
  }, [get, selectedMachineId])

  const queueRefresh = useCallback(() => {
    if (refreshRef.current) clearTimeout(refreshRef.current)
    refreshRef.current = setTimeout(() => {
      refreshRef.current = null
      loadData()
    }, 500)
  }, [loadData])

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => {
    const id = setInterval(() => loadData(), 60000)
    return () => clearInterval(id)
  }, [loadData])

  useEffect(() => {
    const stored = loadWidgetPreference(user, scopeKey, scopeFallback)
    setSelectedWidgets(stored)
    setDraftWidgets(stored)
  }, [user, scopeKey, scopeFallback])

  useEffect(() => () => {
    if (refreshRef.current) clearTimeout(refreshRef.current)
  }, [])

  useWsListener(msg => {
    if (msg.type === 'machine_online') {
      setMachines(ms => ms.map(m => (m.machine_id === msg.machine_id ? { ...m, online: true } : m)))
      queueRefresh()
    }
    if (msg.type === 'machine_offline') {
      setMachines(ms => ms.map(m => (m.machine_id === msg.machine_id ? { ...m, online: false } : m)))
      queueRefresh()
    }
    if (msg.type === 'new_alert' || msg.type === 'dlp_alert_activity' || msg.type === 'phishing_alert_activity') {
      queueRefresh()
    }
  })

  if (loading) {
    return (
      <div className="loading-center">
        <div className="spinner" style={{ width: 32, height: 32, borderWidth: 3 }} />
        <span>Loading dashboard...</span>
      </div>
    )
  }

  const online = machines.filter(m => m.online)
  const offline = Math.max(0, machines.length - online.length)
  const viewLabel = selectedMachine ? `${selectedMachine.hostname}${selectedMachine.username ? ` Â· ${selectedMachine.username}` : ''}` : 'All machines'

  const globalAppData = (overview?.top_apps || []).slice(0, 8).map(a => ({
    name: a.app_name.length > 13 ? `${a.app_name.slice(0, 13)}...` : a.app_name,
    minutes: Math.round((a.total || 0) / 60),
  }))
  const globalPieData = (overview?.top_domains || []).slice(0, 6).map(d => ({
    name: d.domain.replace('www.', ''),
    value: d.visits,
  }))
  const globalTrendData = (overview?.daily_activity || []).map(d => ({
    label: d.date.slice(5),
    machines: d.machines,
    value: Math.round((d.total_seconds || 0) / 3600),
  }))

  const machineAppData = (machineAnalytics?.app_usage || []).slice(0, 8).map(a => ({
    name: a.app_name.length > 13 ? `${a.app_name.slice(0, 13)}...` : a.app_name,
    minutes: Math.round((a.total_seconds || 0) / 60),
  }))
  const machinePieData = (machineAnalytics?.browser_usage || []).slice(0, 6).map(d => ({
    name: d.domain.replace('www.', ''),
    value: d.visits,
  }))
  const machineTrendData = (machineAnalytics?.hourly_activity || []).map(d => ({
    label: `${d.hour}:00`,
    value: Math.round((d.total_seconds || 0) / 60),
  }))

  const scopeAppData = selectedMachineId === 'all' ? globalAppData : machineAppData
  const scopePieData = selectedMachineId === 'all' ? globalPieData : machinePieData
  const scopeTrendData = selectedMachineId === 'all' ? globalTrendData : machineTrendData

  const appProductivity = overview?.app_productivity || {}
  const domainProductivity = overview?.domain_productivity || {}
  const totalHours = globalTrendData.reduce((sum, day) => sum + (day.value || 0), 0)
  const averageDailyHours = globalTrendData.length ? `${Math.round(totalHours / globalTrendData.length)}h` : '-'
  const productiveAppTime = secsToHM(appProductivity.productive || 0)
  const productiveVisits = domainProductivity.productive || 0
  const topAppName = selectedMachineId === 'all'
    ? (overview?.top_apps?.[0]?.app_name || '-').slice(0, 14)
    : (machineAnalytics?.app_usage?.[0]?.app_name || '-').slice(0, 14)
  const topDomainName = selectedMachineId === 'all'
    ? (overview?.top_domains?.[0]?.domain || '-').replace('www.', '').slice(0, 18)
    : (machineAnalytics?.browser_usage?.[0]?.domain || '-').replace('www.', '').slice(0, 18)
  const machineActiveTime = secsToHM(machineAnalytics?.total_active_seconds || 0)
  const browserVisits = machineAnalytics?.browser_visits || 0
  const productivityScore = `${safeNum(machineProductivity?.score)}%`
  const productiveSeconds = secsToHM(machineProductivity?.productive_seconds || 0)
  const productiveBrowserSeconds = secsToHM(machineProductivity?.productive_browser_seconds || 0)
  const peakHour = machineAnalytics?.hourly_activity?.length
    ? machineAnalytics.hourly_activity.reduce((best, row) => {
        if (!best) return row
        return safeNum(row.total_seconds) > safeNum(best.total_seconds) ? row : best
      }, null)
    : null

  const browserCategoryData = Object.entries(browserLogsStats?.by_category || {})
    .map(([name, value]) => ({
      name: name.charAt(0).toUpperCase() + name.slice(1),
      value: safeNum(value),
      fill: name === 'productive' ? 'var(--green)' : name === 'unproductive' ? 'var(--red)' : 'var(--text-3)',
    }))
    .filter(item => item.value > 0)

  const appCategoryData = Object.entries(appUsageStats?.by_category || {})
    .map(([name, value]) => ({
      name: name.charAt(0).toUpperCase() + name.slice(1),
      value: safeNum(value),
      fill: name === 'productive' ? 'var(--green)' : 'var(--text-3)',
    }))
    .filter(item => item.value > 0)

  const inputChartData = (inputRows || []).slice(0, 20).map((row, index) => ({
    name: `#${Math.max(1, (inputRows || []).length - index)}`,
    keys: safeNum(row.key_event_count),
    clicks: safeNum(row.mouse_click_count),
  }))
  const inputTotals = {
    keys: (inputRows || []).reduce((sum, row) => sum + safeNum(row.key_event_count), 0),
    clicks: (inputRows || []).reduce((sum, row) => sum + safeNum(row.mouse_click_count), 0),
  }

  const fileActionData = (fileStats?.by_action || []).map((row) => ({
    name: (row.action || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase()),
    value: safeNum(row.cnt),
    fill: row.action === 'delete' ? 'var(--red)' : row.action === 'create' ? 'var(--green)' : 'var(--amber)',
  })).filter(item => item.value > 0)

  const fileExtData = (() => {
    const counts = new Map()
    fileLogs.forEach((item) => {
      let ext = item.file_ext || ''
      if (!ext || ext.length > 10 || /^\.\d+$/.test(ext)) ext = item.is_directory ? 'folder' : 'other'
      counts.set(ext, (counts.get(ext) || 0) + 1)
    })
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name, value]) => ({ name, value }))
  })()

  const latestNetworkSnapshots = networkStats?.latest_by_machine || []
  const networkTopPortsData = (() => {
    const counts = new Map()
    latestNetworkSnapshots.forEach((snapshot) => {
      ;(snapshot.listening_ports || []).forEach((port) => {
        const label = `${port.port} (${port.process || '?'})`
        counts.set(label, (counts.get(label) || 0) + 1)
      })
    })
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name, value]) => ({ name, value }))
  })()

  const networkTopHostsData = (() => {
    const counts = new Map()
    latestNetworkSnapshots.forEach((snapshot) => {
      ;(snapshot.connections || []).forEach((conn) => {
        const name = conn.domain || conn.remote_ip || 'unknown'
        counts.set(name, (counts.get(name) || 0) + 1)
      })
    })
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name, value]) => ({ name: name.length > 26 ? `${name.slice(0, 23)}...` : name, value, full: name }))
  })()

  const networkProtocolPieData = (() => {
    const counts = new Map()
    latestNetworkSnapshots.forEach((snapshot) => {
      ;(snapshot.connections || []).forEach((conn) => {
        const key = String(conn.protocol || 'tcp').toUpperCase()
        counts.set(key, (counts.get(key) || 0) + 1)
      })
      ;(snapshot.listening_ports || []).forEach((port) => {
        const key = String(port.protocol || 'tcp').toUpperCase()
        counts.set(key, (counts.get(key) || 0) + 1)
      })
    })
    return Array.from(counts.entries()).map(([name, value], index) => ({
      name,
      value,
      fill: PALETTE[index % PALETTE.length],
    }))
  })()

  const networkBandwidthData = [...networkLogs]
    .reverse()
    .slice(-20)
    .map((item) => ({
      time: new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      sent: safeNum(item.bytes_sent),
      recv: safeNum(item.bytes_recv),
    }))

  const alertsSeverityData = (alertsStats?.by_severity || []).map((row, index) => ({
    name: row.severity || 'unknown',
    value: safeNum(row.count),
    fill: PALETTE[index % PALETTE.length],
  })).filter(item => item.value > 0)
  const alertCoverageData = [
    { name: 'Unread', value: safeNum(alertsStats?.unread), fill: 'var(--red)' },
    { name: 'Today', value: safeNum(alertsStats?.today), fill: 'var(--amber)' },
    { name: 'Total', value: safeNum(alertsStats?.total), fill: 'var(--brand)' },
  ].filter(item => item.value > 0)

  const dlpRiskData = Object.entries(dlpStats?.by_risk || {}).map(([name, value], index) => ({
    name: name.charAt(0).toUpperCase() + name.slice(1),
    value: safeNum(value),
    fill: PALETTE[index % PALETTE.length],
  })).filter(item => item.value > 0)
  const dlpDestinationData = Object.entries(dlpStats?.by_destination || {})
    .map(([name, value], index) => ({
      name: name || 'Unknown',
      value: safeNum(value),
      fill: PALETTE[index % PALETTE.length],
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6)
  const dlpTopFilesData = (dlpStats?.top_files || []).slice(0, 5).map((row, index) => ({
    name: (row.file_name || row.file_path || 'unknown').slice(0, 24),
    value: safeNum(row.hit_count),
    fill: PALETTE[index % PALETTE.length],
  }))
  const dlpTotalEvents = safeNum(dlpStats?.total)
  const dlpOpenIncidents = dlpIncidents.filter(item => (item.state || 'open') === 'open').length
  const dlpBlockedEvents = dlpEvents.filter(item => item.action_taken === 'block_transfer').length
  const dlpUniqueFiles = safeNum(dlpStats?.unique_sensitive_files)

  const phishingSeverityData = (() => {
    const counts = new Map()
    phishingIncidents.forEach((item) => {
      const key = String(item.severity || 'medium')
      counts.set(key, (counts.get(key) || 0) + 1)
    })
    return Array.from(counts.entries()).map(([name, value], index) => ({
      name,
      value,
      fill: PALETTE[index % PALETTE.length],
    }))
  })()
  const phishingDomainData = (() => {
    const counts = new Map()
    phishingIncidents.forEach((item) => {
      const name = item.domain || item.url || 'unknown'
      counts.set(name, (counts.get(name) || 0) + 1)
    })
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([name, value], index) => ({
        name: name.replace(/^https?:\/\//, '').replace(/^www\./, '').slice(0, 24),
        value,
        fill: PALETTE[index % PALETTE.length],
      }))
  })()
  const phishingWarnings = phishingIncidents.filter(item => item.warning_shown).length
  const phishingTrustedSites = phishingAllowlists.length
  const phishingEventsCount = phishingEvents.length

  const widgetCatalog = [
    {
      id: 'total_machines',
      kind: 'stat',
      label: 'Total Machines',
      category: 'Overview',
      description: 'Registered endpoints',
      previewValue: safeNum(overview?.total_machines),
      render: () => (
        <KpiCard
          label="Total Machines"
          value={overview?.total_machines ?? 0}
          sub="Registered endpoints"
          icon={MachinesIcon}
          colorVar="var(--brand)"
        />
      ),
    },
    {
      id: 'online_now',
      kind: 'stat',
      label: 'Online Now',
      category: 'Overview',
      description: 'Active connections',
      previewValue: online.length,
      render: () => (
        <KpiCard
          label="Online Now"
          value={online.length}
          sub="Active connections"
          icon={OnlineIcon}
          colorVar="var(--green)"
        />
      ),
    },
    {
      id: 'offline_now',
      kind: 'stat',
      label: 'Offline Now',
      category: 'Overview',
      description: 'Machines not connected',
      previewValue: offline,
      render: () => (
        <KpiCard
          label="Offline Now"
          value={offline}
          sub="Machines not connected"
          icon={OfflineIcon}
          colorVar="var(--red)"
        />
      ),
    },
    {
      id: 'active_today',
      kind: 'stat',
      label: 'Active Today',
      category: 'Overview',
      description: 'Machines with data',
      previewValue: safeNum(overview?.active_today),
      render: () => (
        <KpiCard
          label="Active Today"
          value={overview?.active_today ?? 0}
          sub="Machines with data"
          icon={TodayIcon}
          colorVar="var(--amber)"
        />
      ),
    },
    {
      id: 'top_application',
      kind: 'stat',
      label: 'Top Application',
      category: 'Overview',
      description: 'Most used today',
      previewValue: safeNum(overview?.top_apps?.[0]?.total) || 1,
      render: () => (
        <KpiCard
          label="Top Application"
          value={topAppName}
          sub="Most used today"
          icon={AppIcon}
          colorVar="var(--purple)"
        />
      ),
    },
    {
      id: 'top_domain',
      kind: 'stat',
      label: 'Top Domain',
      category: 'Overview',
      description: 'Highest visit volume',
      previewValue: safeNum(overview?.top_domains?.[0]?.visits) || 1,
      render: () => (
        <KpiCard
          label="Top Domain"
          value={topDomainName}
          sub="Highest visit volume"
          icon={DomainIcon}
          colorVar="var(--brand)"
        />
      ),
    },
    {
      id: 'productive_time',
      kind: 'stat',
      label: 'Productive Time',
      category: 'Overview',
      description: 'Tracked app time',
      previewValue: safeNum(appProductivity.productive || 0) / 60,
      render: () => (
        <KpiCard
          label="Productive Time"
          value={productiveAppTime}
          sub="Tracked app time"
          icon={TimeIcon}
          colorVar="var(--green)"
        />
      ),
    },
    {
      id: 'productive_visits',
      kind: 'stat',
      label: 'Productive Visits',
      category: 'Overview',
      description: 'Productive domains',
      previewValue: safeNum(domainProductivity.productive),
      render: () => (
        <KpiCard
          label="Productive Visits"
          value={productiveVisits}
          sub="Productive domains"
          icon={VisitsIcon}
          colorVar="var(--amber)"
        />
      ),
    },
    {
      id: 'avg_daily_hours',
      kind: 'stat',
      label: 'Avg Daily Hours',
      category: 'Overview',
      description: '7-day average',
      previewValue: safeNum(averageDailyHours.replace('h', '')),
      render: () => (
        <KpiCard
          label="Avg Daily Hours"
          value={averageDailyHours}
          sub="7-day average"
          icon={AverageHoursIcon}
          colorVar="var(--brand)"
        />
      ),
    },
    {
      id: 'active_time',
      kind: 'stat',
      label: 'Active Time',
      category: 'Machine',
      description: 'Tracked usage time',
      previewValue: safeNum(machineAnalytics?.total_active_seconds) / 60,
      render: () => (
        <KpiCard
          label="Active Time"
          value={machineActiveTime}
          sub="Tracked usage time"
          icon={TimeIcon}
          colorVar="var(--brand)"
        />
      ),
    },
    {
      id: 'browser_visits',
      kind: 'stat',
      label: 'Browser Visits',
      category: 'Machine',
      description: 'Recorded visits',
      previewValue: safeNum(browserVisits),
      render: () => (
        <KpiCard
          label="Browser Visits"
          value={browserVisits}
          sub="Recorded visits"
          icon={VisitsIcon}
          colorVar="var(--green)"
        />
      ),
    },
    {
      id: 'productivity_score',
      kind: 'stat',
      label: 'Productivity Score',
      category: 'Machine',
      description: 'Machine activity score',
      previewValue: safeNum(machineProductivity?.score),
      render: () => (
        <KpiCard
          label="Productivity Score"
          value={productivityScore}
          sub="Machine activity score"
          icon={TodayIcon}
          colorVar="var(--amber)"
        />
      ),
    },
    {
      id: 'top_application_machine',
      kind: 'stat',
      label: 'Top Application',
      category: 'Machine',
      description: 'Most used app',
      previewValue: safeNum(machineAnalytics?.app_usage?.[0]?.total_seconds) / 60 || 1,
      render: () => (
        <KpiCard
          label="Top Application"
          value={topAppName}
          sub="Most used app"
          icon={AppIcon}
          colorVar="var(--purple)"
        />
      ),
    },
    {
      id: 'top_domain_machine',
      kind: 'stat',
      label: 'Top Domain',
      category: 'Machine',
      description: 'Most visited domain',
      previewValue: safeNum(machineAnalytics?.browser_usage?.[0]?.visits) || 1,
      render: () => (
        <KpiCard
          label="Top Domain"
          value={topDomainName}
          sub="Most visited domain"
          icon={DomainIcon}
          colorVar="var(--brand)"
        />
      ),
    },
    {
      id: 'peak_hour',
      kind: 'stat',
      label: 'Peak Hour',
      category: 'Machine',
      description: 'Busiest hour',
      previewValue: safeNum(peakHour?.total_seconds) / 60 || 1,
      render: () => (
        <KpiCard
          label="Peak Hour"
          value={peakHour ? `${peakHour.hour}:00` : '-'}
          sub="Busiest hour"
          icon={AverageHoursIcon}
          colorVar="var(--cyan)"
        />
      ),
    },
    {
      id: 'productive_browser',
      kind: 'stat',
      label: 'Productive Browser',
      category: 'Machine',
      description: 'Productive browser time',
      previewValue: safeNum(machineProductivity?.productive_browser_seconds) / 60,
      render: () => (
        <KpiCard
          label="Productive Browser"
          value={productiveBrowserSeconds}
          sub="Productive browser time"
          icon={VisitsIcon}
          colorVar="var(--amber)"
        />
      ),
    },
    {
      id: 'overview_app_usage',
      kind: 'chart',
      label: 'App Usage Chart',
      category: 'Overview',
      description: 'Top applications in the current scope',
      previewValue: scopeAppData.length || 1,
      render: () => (
        <WidgetCard
          title={selectedMachineId === 'all' ? 'App Usage' : 'App Usage'}
          subtitle={selectedMachineId === 'all' ? 'Top apps in the current scope' : 'Top apps on the selected machine'}
          icon={ChartBarIcon}
          colorVar="var(--brand)"
          minHeight={310}
          footer={scopeAppData.length ? `${scopeAppData.length} app buckets` : 'No app data'}
        >
          {scopeAppData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No app data</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={scopeAppData} margin={{ left: -18 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TTip />} />
                <Bar dataKey="minutes" radius={[8, 8, 0, 0]} fill={PALETTE[0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'overview_domain_mix',
      kind: 'chart',
      label: 'Domain Mix',
      category: 'Overview',
      description: 'Top domains or productivity split',
      previewValue: scopePieData.length || 1,
      render: () => (
        <WidgetCard
          title={selectedMachineId === 'all' ? 'Top Domains' : 'Browser Usage'}
          subtitle={selectedMachineId === 'all' ? 'Domain mix and productivity split' : 'Domain usage on the selected machine'}
          icon={ChartPieIcon}
          colorVar="var(--brand)"
          minHeight={310}
          footer={scopePieData.length ? `${scopePieData.length} segments` : 'No domain data'}
        >
          {scopePieData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No domain data</div>
          ) : selectedMachineId === 'all' ? (() => {
            const domProd = [
              { name: 'Productive', value: safeNum(domainProductivity.productive || 0), fill: '#0F9D8A' },
              { name: 'Unproductive', value: safeNum(domainProductivity.unproductive || 0), fill: '#DC2626' },
              { name: 'Neutral', value: safeNum(domainProductivity.neutral || 0), fill: '#64748B' },
            ].filter(d => d.value > 0)

            if (domProd.length === 0) {
              return (
                <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No domain data</div>
              )
            }

            return (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <ResponsiveContainer width="55%" height={190}>
                  <PieChart>
                    <Pie data={domProd} cx="50%" cy="50%" innerRadius={44} outerRadius={74} dataKey="value" stroke="none" paddingAngle={3}>
                      {domProd.map((d, i) => <Cell key={i} fill={d.fill} />)}
                    </Pie>
                    <Tooltip content={<TTip />} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {domProd.map((d, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                      <span style={{ width: 10, height: 10, borderRadius: 2, background: d.fill, flexShrink: 0 }} />
                      <span style={{ flex: 1, color: 'var(--text-2)' }}>{d.name}</span>
                      <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>{d.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )
          })() : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <ResponsiveContainer width="55%" height={190}>
                <PieChart>
                  <Pie data={scopePieData} cx="50%" cy="50%" innerRadius={44} outerRadius={74} dataKey="value" stroke="none" paddingAngle={3}>
                    {scopePieData.map((d, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                  </Pie>
                  <Tooltip content={<TTip />} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {scopePieData.slice(0, 6).map((d, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: PALETTE[i % PALETTE.length], flexShrink: 0 }} />
                    <span style={{ flex: 1, color: 'var(--text-2)' }}>{d.name}</span>
                    <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>{d.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'overview_trend',
      kind: 'chart',
      label: 'Activity Trend',
      category: 'Overview',
      description: 'Seven day or hourly trend',
      previewValue: scopeTrendData.length || 1,
      render: () => (
        <WidgetCard
          title={selectedMachineId === 'all' ? '7-Day Activity Trend' : 'Hourly Activity Trend'}
          subtitle={selectedMachineId === 'all' ? 'Fleet activity over the last 7 days' : 'Selected machine hourly trend'}
          icon={ChartLineIcon}
          colorVar="var(--brand)"
          minHeight={270}
        >
          {scopeTrendData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No trend data</div>
          ) : (
            <ResponsiveContainer width="100%" height={170}>
              <LineChart data={scopeTrendData} margin={{ left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TTip />} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey={selectedMachineId === 'all' ? 'machines' : 'value'} stroke={PALETTE[0]} strokeWidth={2.5} dot={{ r: 3 }} name={selectedMachineId === 'all' ? 'Machines' : 'Minutes'} />
                {selectedMachineId === 'all' && (
                  <Line type="monotone" dataKey="value" stroke={PALETTE[1]} strokeWidth={2.5} dot={{ r: 3 }} name="Hours" />
                )}
              </LineChart>
            </ResponsiveContainer>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'alerts_summary',
      kind: 'chart',
      label: 'Alerts Summary',
      category: 'Alerts',
      description: 'Unread, today, and total alerts',
      previewValue: safeNum(alertsStats?.total),
      render: () => (
        <WidgetCard title="Alerts Summary" subtitle="Unread, today, and total alerts" icon={AlertsIcon} colorVar="var(--red)" minHeight={280}>
          {alertCoverageData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No alert data</div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <ResponsiveContainer width="48%" height={180}>
                <PieChart>
                  <Pie data={alertCoverageData} dataKey="value" innerRadius={40} outerRadius={62} stroke="none" paddingAngle={4}>
                    {alertCoverageData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
                  </Pie>
                  <Tooltip content={<TTip />} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {alertCoverageData.map(item => (
                  <div key={item.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: item.fill, flexShrink: 0 }} />
                    <span style={{ flex: 1, color: 'var(--text-2)' }}>{item.name}</span>
                    <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'alerts_severity',
      kind: 'chart',
      label: 'Alert Severity',
      category: 'Alerts',
      description: 'Severity breakdown',
      previewValue: alertsSeverityData.length || 1,
      render: () => (
        <WidgetCard title="Alert Severity" subtitle="Severity breakdown by log volume" icon={AlertsIcon} colorVar="var(--amber)" minHeight={280}>
          {alertsSeverityData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No severity data</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={alertsSeverityData} margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TTip />} />
                <Bar dataKey="value" radius={[8, 8, 0, 0]}>
                  {alertsSeverityData.map((_, index) => <Cell key={index} fill={PALETTE[index % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'dlp_summary',
      kind: 'chart',
      label: 'DLP Summary',
      category: 'DLP',
      description: 'Risk, incidents, and blocks',
      previewValue: dlpTotalEvents,
      render: () => (
        <WidgetCard title="DLP Summary" subtitle="Risk and incident snapshot" icon={DlpIcon} colorVar="var(--brand)" minHeight={300}>
          <div style={{ display: 'grid', gap: 10, marginBottom: 14 }}>
            <div className="stat-card" style={{ padding: 12, minHeight: 'auto' }}>
              <div className="stat-label">Open alerts</div>
              <div className="stat-value" style={{ color: 'var(--brand)', fontSize: 26 }}>{dlpOpenIncidents}</div>
              <div className="stat-sub">Needs review</div>
            </div>
            <div className="stat-card" style={{ padding: 12, minHeight: 'auto' }}>
              <div className="stat-label">Recent blocks</div>
              <div className="stat-value" style={{ color: 'var(--red)', fontSize: 26 }}>{dlpBlockedEvents}</div>
              <div className="stat-sub">High-risk transfers stopped</div>
            </div>
          </div>
          {dlpRiskData.length ? (
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie data={dlpRiskData} cx="50%" cy="50%" innerRadius={42} outerRadius={64} dataKey="value" stroke="none" paddingAngle={2}>
                  {dlpRiskData.map((entry, index) => <Cell key={index} fill={entry.fill} />)}
                </Pie>
                <Tooltip content={<TTip />} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-3)', fontSize: 13 }}>No DLP risk data</div>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'dlp_destination',
      kind: 'chart',
      label: 'DLP Destinations',
      category: 'DLP',
      description: 'Where sensitive files move to',
      previewValue: dlpDestinationData.length || 1,
      render: () => (
        <WidgetCard title="DLP Destinations" subtitle="Where sensitive files were headed" icon={DlpIcon} colorVar="var(--amber)" minHeight={300}>
          {dlpDestinationData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No destination data</div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <ResponsiveContainer width="50%" height={190}>
                <PieChart>
                  <Pie data={dlpDestinationData} cx="50%" cy="50%" innerRadius={40} outerRadius={66} dataKey="value" stroke="none" paddingAngle={3}>
                    {dlpDestinationData.map((entry, index) => <Cell key={index} fill={entry.fill} />)}
                  </Pie>
                  <Tooltip content={<TTip />} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {dlpDestinationData.map(item => (
                  <div key={item.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: item.fill, flexShrink: 0 }} />
                    <span style={{ flex: 1, color: 'var(--text-2)' }}>{item.name}</span>
                    <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'dlp_files',
      kind: 'chart',
      label: 'DLP Files',
      category: 'DLP',
      description: 'Top sensitive file hits',
      previewValue: dlpTopFilesData.length || 1,
      render: () => (
        <WidgetCard title="DLP Files" subtitle={`Unique sensitive files: ${dlpUniqueFiles}`} icon={DlpIcon} colorVar="var(--purple)" minHeight={300}>
          {dlpTopFilesData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No flagged files</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={dlpTopFilesData} layout="vertical" margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TTip />} />
                <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                  {dlpTopFilesData.map((_, index) => <Cell key={index} fill={PALETTE[index % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'phishing_summary',
      kind: 'chart',
      label: 'Phishing Summary',
      category: 'Phishing',
      description: 'Warnings, incidents, and trusted sites',
      previewValue: phishingEventsCount,
      render: () => (
        <WidgetCard title="Phishing Summary" subtitle="Warnings and recent incidents" icon={PhishingIcon} colorVar="var(--red)" minHeight={300}>
          <div style={{ display: 'grid', gap: 10, marginBottom: 14 }}>
            <div className="stat-card" style={{ padding: 12, minHeight: 'auto' }}>
              <div className="stat-label">Warnings</div>
              <div className="stat-value" style={{ color: 'var(--red)', fontSize: 26 }}>{phishingWarnings}</div>
              <div className="stat-sub">Users who saw a warning</div>
            </div>
            <div className="stat-card" style={{ padding: 12, minHeight: 'auto' }}>
              <div className="stat-label">Trusted sites</div>
              <div className="stat-value" style={{ color: 'var(--brand)', fontSize: 26 }}>{phishingTrustedSites}</div>
              <div className="stat-sub">Allowlisted destinations</div>
            </div>
          </div>
          {phishingSeverityData.length ? (
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie data={phishingSeverityData} cx="50%" cy="50%" innerRadius={42} outerRadius={64} dataKey="value" stroke="none" paddingAngle={2}>
                  {phishingSeverityData.map((entry, index) => <Cell key={index} fill={entry.fill} />)}
                </Pie>
                <Tooltip content={<TTip />} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-3)', fontSize: 13 }}>No phishing data</div>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'phishing_domains',
      kind: 'chart',
      label: 'Phishing Domains',
      category: 'Phishing',
      description: 'Recent suspicious domains',
      previewValue: phishingDomainData.length || 1,
      render: () => (
        <WidgetCard title="Phishing Domains" subtitle={`Recent suspicious domains (${phishingEventsCount} events)`} icon={PhishingIcon} colorVar="var(--amber)" minHeight={300}>
          {phishingDomainData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No phishing activity yet</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={phishingDomainData} layout="vertical" margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TTip />} />
                <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                  {phishingDomainData.map((_, index) => <Cell key={index} fill={PALETTE[index % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'browser_activity',
      kind: 'chart',
      label: 'Browser Activity',
      category: 'Browser',
      description: 'Productive, unproductive, neutral',
      previewValue: browserCategoryData.length || 1,
      render: () => (
        <WidgetCard title="Browser Activity" subtitle="Browser log category split" icon={ChartPieIcon} colorVar="var(--green)" minHeight={260}>
          {selectedMachineId === 'all' ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>Select a machine to view browser log categories</div>
          ) : browserCategoryData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No browser category data</div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <ResponsiveContainer width="50%" height={180}>
                <PieChart>
                  <Pie data={browserCategoryData} cx="50%" cy="50%" innerRadius={42} outerRadius={66} dataKey="value" stroke="none" paddingAngle={2}>
                    {browserCategoryData.map((entry, index) => <Cell key={index} fill={entry.fill} />)}
                  </Pie>
                  <Tooltip content={<TTip />} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {browserCategoryData.map(item => (
                  <div key={item.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: item.fill, flexShrink: 0 }} />
                    <span style={{ flex: 1, color: 'var(--text-2)' }}>{item.name}</span>
                    <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'input_activity',
      kind: 'chart',
      label: 'Input Activity',
      category: 'Input',
      description: 'Keys and clicks over recent buckets',
      previewValue: inputChartData.length || 1,
      render: () => (
        <WidgetCard title="Input Activity" subtitle="Keys and clicks across recent buckets" icon={InputIcon} colorVar="var(--brand)" minHeight={300}>
          {selectedMachineId === 'all' ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>Select a machine to view input activity</div>
          ) : inputChartData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No input buckets</div>
          ) : (
            <>
              <div className="grid-2" style={{ marginBottom: 12 }}>
                <div className="stat-card" style={{ padding: 12, minHeight: 'auto' }}>
                  <div className="stat-label">Key events</div>
                  <div className="stat-value" style={{ color: 'var(--brand)', fontSize: 26 }}>{inputTotals.keys}</div>
                  <div className="stat-sub">Visible rows</div>
                </div>
                <div className="stat-card" style={{ padding: 12, minHeight: 'auto' }}>
                  <div className="stat-label">Mouse clicks</div>
                  <div className="stat-value" style={{ color: 'var(--green)', fontSize: 26 }}>{inputTotals.clicks}</div>
                  <div className="stat-sub">Visible rows</div>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={inputChartData} margin={{ left: 8, right: 12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" />
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<TTip />} />
                  <Bar dataKey="keys" name="Key events" fill="var(--brand)" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="clicks" name="Mouse clicks" fill="var(--success)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'file_activity',
      kind: 'chart',
      label: 'File Activity',
      category: 'Files',
      description: 'File event distribution',
      previewValue: fileActionData.length || 1,
      render: () => (
        <WidgetCard title="File Activity" subtitle="File event distribution" icon={FileIcon} colorVar="var(--amber)" minHeight={300}>
          {fileActionData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No file activity</div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <ResponsiveContainer width="50%" height={190}>
                <PieChart>
                  <Pie data={fileActionData} cx="50%" cy="50%" innerRadius={42} outerRadius={66} dataKey="value" stroke="none" paddingAngle={2}>
                    {fileActionData.map((entry, index) => <Cell key={index} fill={entry.fill} />)}
                  </Pie>
                  <Tooltip content={<TTip />} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {fileActionData.map(item => (
                  <div key={item.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: item.fill, flexShrink: 0 }} />
                    <span style={{ flex: 1, color: 'var(--text-2)' }}>{item.name}</span>
                    <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'file_extensions',
      kind: 'chart',
      label: 'File Extensions',
      category: 'Files',
      description: 'Most common extensions',
      previewValue: fileExtData.length || 1,
      render: () => (
        <WidgetCard title="File Extensions" subtitle="Top file extensions and folders" icon={FileIcon} colorVar="var(--purple)" minHeight={300}>
          {fileExtData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No file extension data</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={fileExtData} barSize={18}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TTip />} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {fileExtData.map((_, index) => <Cell key={index} fill={PALETTE[index % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'network_ports',
      kind: 'chart',
      label: 'Network Ports',
      category: 'Network',
      description: 'Listening ports by process',
      previewValue: networkTopPortsData.length || 1,
      render: () => (
        <WidgetCard title="Network Ports" subtitle="Top listening ports by process" icon={NetworkIcon} colorVar="var(--brand)" minHeight={300}>
          {networkTopPortsData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No port data</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={networkTopPortsData} layout="vertical" margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TTip />} />
                <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                  {networkTopPortsData.map((_, index) => <Cell key={index} fill={PALETTE[index % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'network_bandwidth',
      kind: 'chart',
      label: 'Bandwidth Trend',
      category: 'Network',
      description: 'Sent and received traffic',
      previewValue: networkBandwidthData.length || 1,
      render: () => (
        <WidgetCard title="Bandwidth Trend" subtitle="Recent traffic snapshots" icon={NetworkIcon} colorVar="var(--green)" minHeight={300}>
          {networkBandwidthData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No bandwidth data</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={networkBandwidthData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" vertical={false} />
                <XAxis dataKey="time" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TTip />} />
                <Line type="monotone" dataKey="sent" stroke={PALETTE[0]} strokeWidth={2.5} dot={{ r: 2 }} name="Sent" />
                <Line type="monotone" dataKey="recv" stroke={PALETTE[1]} strokeWidth={2.5} dot={{ r: 2 }} name="Received" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'network_hosts',
      kind: 'chart',
      label: 'Network Hosts',
      category: 'Network',
      description: 'Top domains or IPs',
      previewValue: networkTopHostsData.length || 1,
      render: () => (
        <WidgetCard title="Network Hosts" subtitle="Top connections by host" icon={NetworkIcon} colorVar="var(--amber)" minHeight={300}>
          {networkTopHostsData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No host data</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={networkTopHostsData} barSize={18}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 9 }} axisLine={false} tickLine={false} interval={0} angle={-18} textAnchor="end" height={52} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TTip />} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {networkTopHostsData.map((_, index) => <Cell key={index} fill={PALETTE[index % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </WidgetCard>
      ),
    },
    {
      id: 'network_protocols',
      kind: 'chart',
      label: 'Network Protocols',
      category: 'Network',
      description: 'Protocol mix',
      previewValue: networkProtocolPieData.length || 1,
      render: () => (
        <WidgetCard title="Network Protocols" subtitle="Protocol mix across recent snapshots" icon={NetworkIcon} colorVar="var(--cyan)" minHeight={300}>
          {networkProtocolPieData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No protocol data</div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <ResponsiveContainer width="50%" height={190}>
                <PieChart>
                  <Pie data={networkProtocolPieData} cx="50%" cy="50%" innerRadius={42} outerRadius={66} dataKey="value" stroke="none" paddingAngle={2}>
                    {networkProtocolPieData.map((item, index) => <Cell key={index} fill={item.fill} />)}
                  </Pie>
                  <Tooltip content={<TTip />} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {networkProtocolPieData.map(item => (
                  <div key={item.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: item.fill, flexShrink: 0 }} />
                    <span style={{ flex: 1, color: 'var(--text-2)' }}>{item.name}</span>
                    <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </WidgetCard>
      ),
    },
  ]

  const availableWidgets = widgetCatalog.filter(widget => !draftWidgets.includes(widget.id))
  const visibleWidgets = selectedWidgets
    .map(id => widgetCatalog.find(widget => widget.id === id))
    .filter(Boolean)
  const visibleStatWidgets = visibleWidgets.filter(widget => widget.kind === 'stat')
  const visibleChartWidgets = visibleWidgets.filter(widget => widget.kind === 'chart')

  const openWidgetEditor = () => {
    setDraftWidgets(selectedWidgets)
    setShowWidgetEditor(true)
  }

  const saveWidgetLayout = () => {
    const normalized = normalizeWidgetIds(draftWidgets, scopeFallback)
    setSelectedWidgets(normalized)
    saveWidgetPreference(user, scopeKey, normalized, scopeFallback)
    setShowWidgetEditor(false)
  }

  const resetWidgetLayout = () => setDraftWidgets(scopeFallback)

  const toggleDraftWidget = widgetId => {
    setDraftWidgets(current => (
      current.includes(widgetId)
        ? current.filter(id => id !== widgetId)
        : [...current, widgetId]
    ))
  }

  const selectedPreview = visibleWidgets.map((widget, index) => ({
    name: widget.label,
    value: Math.max(1, safeNum(widget.previewValue)),
    fill: PALETTE[index % PALETTE.length],
  }))
  const coveragePreview = [
    { name: 'Visible', value: visibleWidgets.length, fill: 'var(--brand)' },
    { name: 'Hidden', value: availableWidgets.length, fill: 'var(--bg-4)' },
  ].filter(item => item.value > 0)

  const headerMachineOptions = [
    { machine_id: 'all', hostname: 'All machines', username: '', ip_address: '', os: '' },
    ...machines,
  ]

  return (
    <div className="fade-in machine-calm-shell">
      <div className="page-header machine-calm-header">
        <div>
          <div className="page-title">Overview</div>
          <div className="page-subtitle">
            Fleet activity at a glance{lastUpdate ? ` · Last updated ${lastUpdate.toLocaleTimeString()}` : ''}
          </div>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline btn-sm machine-calm-btn" onClick={openWidgetEditor}>Customize</button>
        </div>
      </div>

      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        flexWrap: 'wrap',
        marginBottom: 18,
      }}>
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          borderRadius: 999,
          border: '1px solid color-mix(in srgb, var(--machine-calm-1) 18%, var(--border))',
          background: 'color-mix(in srgb, var(--bg-2) 96%, transparent)',
          color: 'var(--text-2)',
          fontSize: 12,
          fontWeight: 600,
        }}>
          <MachinesIcon width={16} height={16} />
          Viewing {viewLabel}
        </div>
        {selectedMachine && (
          <div style={{
            display: 'flex',
            gap: 8,
            flexWrap: 'wrap',
          }}>
            <span className="badge badge-blue" style={{ color: 'var(--machine-calm-1)', borderColor: 'color-mix(in srgb, var(--machine-calm-1) 18%, transparent)', background: 'color-mix(in srgb, var(--machine-calm-1) 10%, transparent)' }}>OS: {selectedMachine.os || '-'}</span>
            <span className="badge badge-blue" style={{ color: 'var(--machine-calm-1)', borderColor: 'color-mix(in srgb, var(--machine-calm-1) 18%, transparent)', background: 'color-mix(in srgb, var(--machine-calm-1) 10%, transparent)' }}>IP: {selectedMachine.ip_address || '-'}</span>
            <span className="badge badge-blue" style={{ color: 'var(--machine-calm-1)', borderColor: 'color-mix(in srgb, var(--machine-calm-1) 18%, transparent)', background: 'color-mix(in srgb, var(--machine-calm-1) 10%, transparent)' }}>User: {selectedMachine.username || '-'}</span>
          </div>
        )}
      </div>

      <div
        className="stagger"
        style={{
          marginBottom: 20,
          display: 'grid',
          gap: 16,
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        }}
      >
      <div
        className="stagger"
        style={{
          marginBottom: 20,
          display: 'grid',
          gap: 16,
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        }}
      >
        {/* All Machines Card */}
        <div
          onClick={() => setSelectedMachineId('all')}
          style={{
            cursor: 'pointer',
            padding: '16px 20px',
            borderRadius: 16,
            background: selectedMachineId === 'all'
              ? 'color-mix(in srgb, var(--machine-calm-1) 12%, var(--bg-2))'
              : 'var(--bg-2)',
            border: `2px solid ${selectedMachineId === 'all' ? 'var(--machine-calm-1)' : 'var(--border-0)'}`,
            boxShadow: selectedMachineId === 'all'
              ? '0 8px 30px rgba(59, 123, 248, 0.15)'
              : 'var(--shadow-sm)',
            transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
            position: 'relative',
            overflow: 'hidden',
          }}
          className="machine-calm-card"
          onMouseEnter={e => {
            if (selectedMachineId !== 'all') {
              e.currentTarget.style.transform = 'translateY(-2px)'
              e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--machine-calm-1) 50%, var(--border-0))'
            }
          }}
          onMouseLeave={e => {
            if (selectedMachineId !== 'all') {
              e.currentTarget.style.transform = 'none'
              e.currentTarget.style.borderColor = 'var(--border-0)'
            }
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-1)' }}>All Machines</span>
            <span style={{
              width: 8, height: 8, borderRadius: '50%',
              background: 'var(--machine-calm-1)',
              boxShadow: '0 0 10px var(--machine-calm-1)',
              animation: 'pulse 2s infinite'
            }} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 12px', fontSize: 12 }}>
            <div>
              <div style={{ color: 'var(--text-3)' }}>Total Fleet</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-1)' }}>{machines.length}</div>
            </div>
            <div>
              <div style={{ color: 'var(--text-3)' }}>Online</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--success)' }}>{machines.filter(m => m.online).length}</div>
            </div>
            <div>
              <div style={{ color: 'var(--text-3)' }}>Offline</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-3)' }}>{machines.filter(m => !m.online).length}</div>
            </div>
            <div>
              <div style={{ color: 'var(--text-3)' }}>Combined Scope</div>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--brand)', marginTop: 4 }}>Fleet View</div>
            </div>
          </div>
        </div>

        {/* Machine Cards */}
        {machines.map(machine => {
          const isSelected = selectedMachineId === machine.machine_id
          return (
            <div
              key={machine.machine_id}
              onClick={() => navigate(`/machines/${machine.machine_id}`)}
              style={{
                cursor: 'pointer',
                padding: '16px 20px',
                borderRadius: 16,
                background: isSelected
                  ? 'color-mix(in srgb, var(--machine-calm-1) 12%, var(--bg-2))'
                  : 'var(--bg-2)',
                border: `2px solid ${isSelected ? 'var(--machine-calm-1)' : 'var(--border-0)'}`,
                boxShadow: isSelected
                  ? '0 8px 30px rgba(59, 123, 248, 0.15)'
                  : 'var(--shadow-sm)',
                transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                position: 'relative',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
              className="machine-calm-card"
              onMouseEnter={e => {
                if (!isSelected) {
                  e.currentTarget.style.transform = 'translateY(-2px)'
                  e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--machine-calm-1) 50%, var(--border-0))'
                }
              }}
              onMouseLeave={e => {
                if (!isSelected) {
                  e.currentTarget.style.transform = 'none'
                  e.currentTarget.style.borderColor = 'var(--border-0)'
                }
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                  <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 8 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-1)' }} className="mono">
                      {machine.hostname}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                      {machine.username || 'Unknown user'} · {machine.ip_address || 'No IP'}
                    </div>
                  </div>
                  <span style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: machine.online ? 'var(--success)' : 'var(--text-3)',
                    boxShadow: machine.online ? '0 0 10px var(--success)' : 'none',
                    flexShrink: 0,
                    marginTop: 4,
                  }} />
                </div>

                <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span>OS</span>
                    <span style={{ color: 'var(--text-2)', fontWeight: 600 }}>{machine.os || 'Unknown OS'}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span>Active App</span>
                    <span style={{ color: 'var(--success)', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160 }} title={machine.active_app}>
                      {machine.active_app || '—'}
                    </span>
                  </div>
                  {machine.online && (
                    <div style={{ marginTop: 8 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 10 }}>
                        <span>CPU Usage</span>
                        <span className="mono">{Math.round(machine.cpu_percent || 0)}%</span>
                      </div>
                      <div style={{ height: 4, background: 'var(--border-0)', borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{
                          width: `${Math.round(machine.cpu_percent || 0)}%`,
                          height: '100%',
                          background: 'var(--machine-calm-1)',
                          borderRadius: 2,
                          transition: 'width 0.3s ease',
                        }} />
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10, borderTop: '1px solid var(--border-0)', paddingTop: 10 }}>
                <button
                  onClick={e => {
                    e.stopPropagation()
                    navigate(`/machines/${machine.machine_id}`)
                  }}
                  className="btn btn-outline btn-sm machine-calm-btn"
                  style={{ padding: '4px 10px', fontSize: 11, minHeight: 'auto' }}
                >
                  Details
                </button>
                {machine.online && (
                  <button
                    onClick={e => {
                      e.stopPropagation()
                      navigate(`/live?machine=${machine.machine_id}`)
                    }}
                    className="btn btn-primary btn-sm machine-calm-primary"
                    style={{ padding: '4px 10px', fontSize: 11, minHeight: 'auto' }}
                  >
                    Live
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
      </div>

      {visibleChartWidgets.length > 0 && (
        <div
          style={{
            marginBottom: 20,
            display: 'grid',
            gap: 16,
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          }}
        >
          {visibleChartWidgets.map(widget => (
            <div key={widget.id}>{widget.render()}</div>
          ))}
        </div>
      )}

      <div className="card card-flush machine-calm-card">
        <div className="card-header" style={{ padding: '18px 22px 0' }}>
          <span className="card-title-lg">
            {selectedMachineId === 'all' ? `Online Machines (${online.length})` : `Selected Machine: ${selectedMachine?.hostname || 'Machine'}`}
          </span>
          <button className="btn btn-outline btn-sm machine-calm-btn" onClick={() => navigate('/machines')}>
            View All
          </button>
        </div>

        {selectedMachineId === 'all' ? (
          online.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon"><MachinesIcon width={36} height={36} /></div>
              <div className="empty-state-title">No machines online</div>
              <div className="empty-state-sub">Machines will appear here when the agent connects</div>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table machine-calm-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Hostname</th>
                    <th>User</th>
                    <th>OS</th>
                    <th>IP</th>
                    <th>Active App</th>
                    <th>CPU</th>
                    <th style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {online.slice(0, 10).map(m => (
                    <tr key={m.machine_id}>
                      <td><span className="dot-online" /></td>
                      <td>
                        <span className="mono" style={{ fontSize: 12, fontWeight: 600 }}>{m.hostname}</span>
                      </td>
                      <td style={{ color: 'var(--text-2)' }}>{m.username || '-'}</td>
                      <td><span className="badge badge-blue" style={{ fontSize: 10, color: 'var(--machine-calm-1)', borderColor: 'color-mix(in srgb, var(--machine-calm-1) 18%, transparent)', background: 'color-mix(in srgb, var(--machine-calm-1) 10%, transparent)' }}>{m.os}</span></td>
                      <td><span className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{m.ip_address}</span></td>
                      <td style={{ maxWidth: 130 }} className="truncate">
                        <span style={{ color: 'var(--text-2)', fontSize: 12 }}>{m.active_app || '-'}</span>
                      </td>
                      <td style={{ width: 110 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <div style={{ flex: 1, height: 4, background: 'var(--surface-4)', borderRadius: 2, overflow: 'hidden' }}>
                            <div
                              style={{
                                width: `${m.cpu_percent || 0}%`,
                                height: '100%',
                                borderRadius: 2,
                                background: (m.cpu_percent || 0) > 80 ? '#c3aa87' : '#5c8a92',
                                transition: 'width .5s',
                              }}
                            />
                          </div>
                          <span className="mono" style={{ fontSize: 11, color: 'var(--text-3)', minWidth: 32 }}>
                            {Math.round(m.cpu_percent || 0)}%
                          </span>
                        </div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <div style={{ display: 'flex', gap: 5, justifyContent: 'flex-end' }}>
                          <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => navigate(`/machines/${m.machine_id}`)}>Details</button>
                          <button className="btn btn-outline btn-sm machine-calm-btn" onClick={() => navigate(`/remote?machine=${m.machine_id}`)}>Remote</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : selectedMachine ? (
          <div style={{ padding: '0 22px 22px', display: 'grid', gap: 12 }}>
            <div className="empty-state" style={{ paddingTop: 22, paddingBottom: 22 }}>
              <div className="empty-state-title" style={{ fontSize: 18 }}>{selectedMachine.hostname}</div>
              <div className="empty-state-sub">{selectedMachine.username || 'No user'} · {selectedMachine.os || 'Unknown OS'} · {selectedMachine.ip_address || 'No IP'}</div>
            </div>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', justifyContent: 'center' }}>
              <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => navigate(`/machines/${selectedMachine.machine_id}`)}>Open details</button>
              <button className="btn btn-outline btn-sm machine-calm-btn" onClick={() => navigate(`/remote?machine=${selectedMachine.machine_id}`)}>Remote access</button>
            </div>
          </div>
        ) : null}
      </div>

      {showWidgetEditor && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15, 23, 42, 0.32)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 20,
            zIndex: 50,
          }}
        >
          <div className="card machine-calm-card overview-customize-modal">
            <div className="card-header overview-customize-header" style={{ alignItems: 'flex-start' }}>
              <div>
                <div className="card-title">Customize overview</div>
                <div style={{ fontSize: 13, color: 'var(--text-3)', marginTop: 4 }}>
                  Pick the widgets you want on the overview. Order and visibility are saved per user, tenant, and scope.
                </div>
              </div>
              <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => setShowWidgetEditor(false)}>Close</button>
            </div>

            <div className="overview-customize-grid">
              <div className="overview-customize-panel">
                <div className="overview-customize-panel-head">
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>
                    Visible widgets ({draftWidgets.length})
                  </div>
                  <div className="overview-customize-panel-sub">Drag order mentally here: top items stay most prominent.</div>
                </div>
                <div className="overview-customize-list">
                  {draftWidgets.map((widgetId, index) => {
                    const widget = widgetCatalog.find(item => item.id === widgetId)
                    if (!widget) return null
                    return (
                      <div
                        key={widget.id}
                        className="overview-customize-item"
                      >
                        <div className="overview-customize-item-copy">
                          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>{widget.label}</div>
                          <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>{widget.description}</div>
                        </div>
                        <div className="overview-customize-item-actions">
                          <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => setDraftWidgets(current => moveItem(current, index, index - 1))} disabled={index === 0}>Up</button>
                          <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => setDraftWidgets(current => moveItem(current, index, index + 1))} disabled={index === draftWidgets.length - 1}>Down</button>
                          <button className="btn btn-outline btn-sm machine-calm-btn" onClick={() => toggleDraftWidget(widget.id)} disabled={draftWidgets.length <= WIDGET_MIN_SELECTION} title={draftWidgets.length <= WIDGET_MIN_SELECTION ? `Keep at least ${WIDGET_MIN_SELECTION} widgets visible` : 'Remove widget'}>Remove</button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div className="overview-customize-panel">
                <div className="overview-customize-panel-head">
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>
                    Available widgets
                  </div>
                  <div className="overview-customize-panel-sub">Add back any widget that is currently hidden.</div>
                </div>
                <div className="overview-customize-list">
                  {availableWidgets.length === 0 && (
                    <div className="overview-customize-empty">All widgets are already in use.</div>
                  )}
                  {availableWidgets.map(widget => (
                    <div
                      key={widget.id}
                      className="overview-customize-item overview-customize-item-available"
                    >
                      <div className="overview-customize-item-copy">
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>{widget.label}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>{widget.description}</div>
                      </div>
                      <button className="btn btn-primary btn-sm machine-calm-primary" onClick={() => toggleDraftWidget(widget.id)}>Add</button>
                    </div>
                  ))}
                </div>
              </div>

              <div className="overview-customize-panel overview-customize-preview-panel">
                <div className="overview-customize-panel-head">
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>
                    Preview
                  </div>
                  <div className="overview-customize-panel-sub">Quick coverage and ordering snapshot before saving.</div>
                </div>

                <div className="overview-customize-preview-grid">
                  <div className="overview-customize-preview-chart">
                    {selectedPreview.length === 0 ? (
                      <div className="overview-customize-empty">Add widgets to see a preview</div>
                    ) : (
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={selectedPreview} layout="vertical" margin={{ left: 8, right: 12 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" />
                          <XAxis type="number" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                          <YAxis dataKey="name" type="category" width={92} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                          <Tooltip content={<TTip />} />
                          <Bar dataKey="value" radius={[0, 8, 8, 0]}>
                            {selectedPreview.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>

                  <div className="overview-customize-coverage">
                    <div className="overview-customize-coverage-chart">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie data={coveragePreview} dataKey="value" innerRadius={36} outerRadius={58} stroke="none" paddingAngle={4}>
                            {coveragePreview.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
                          </Pie>
                          <Tooltip content={<TTip />} />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="overview-customize-coverage-copy">
                      <div style={{ fontSize: 13, color: 'var(--text-2)' }}>Coverage</div>
                      {coveragePreview.map(item => (
                        <div key={item.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                          <span style={{ width: 10, height: 10, borderRadius: 2, background: item.fill, flexShrink: 0 }} />
                          <span style={{ flex: 1, color: 'var(--text-2)' }}>{item.name}</span>
                          <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>{item.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="overview-customize-footer">
              <div style={{ fontSize: 12, color: 'var(--text-3)' }}>
                Minimum visible widgets: {WIDGET_MIN_SELECTION} · Scope: {selectedMachineId === 'all' ? 'All machines' : selectedMachine?.hostname || 'Selected machine'}
              </div>
              <div className="overview-customize-footer-actions">
                <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={resetWidgetLayout}>Reset default</button>
                <button className="btn btn-outline btn-sm machine-calm-btn" onClick={() => setShowWidgetEditor(false)}>Cancel</button>
                <button className="btn btn-primary btn-sm machine-calm-primary" onClick={saveWidgetLayout}>Save layout</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}



