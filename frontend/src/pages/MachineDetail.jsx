import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useAuth'
import {
  AppIcon,
  AverageHoursIcon,
  ChartBarIcon,
  ChartPieIcon,
  DomainIcon,
  MachinesIcon,
  NetworkIcon,
  TimeIcon,
} from '../components/ui/OverviewIcons'
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'

const fmt = (s) => {
  if (!s) return '0m'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h ? `${h}h ${m}m` : `${m}m`
}

const fmtTs = (ts) => (ts ? new Date(ts).toLocaleString() : '--')
const calmChartColors = ['#5c8a92', '#7aa39b', '#b6926c', '#8b95b5', '#6b8bb6', '#8ba79a']
const fmtCount = (value) => Number(value || 0).toLocaleString()
const fmtPct = (value) => `${Math.round(Number(value || 0) * 100)}%`

const safeHealth = (value) => {
  if (!value) return {}
  if (typeof value === 'string') {
    try {
      return JSON.parse(value)
    } catch {
      return {}
    }
  }
  return typeof value === 'object' ? value : {}
}

function TTip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip machine-calm-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color || p.fill, fontWeight: 600, fontSize: 12, marginTop: 2 }}>
          {p.name}: {p.value}
        </div>
      ))}
    </div>
  )
}

const TABS = [
  { id: 'overview', label: 'Overview', icon: ChartPieIcon },
  { id: 'apps', label: 'Applications', icon: AppIcon },
  { id: 'browser', label: 'Browser', icon: DomainIcon },
  { id: 'diagnostics', label: 'Diagnostics', icon: NetworkIcon },
]

function DetailMetricCard({ icon: Icon, label, value, subtext, tone = 'brand' }) {
  return (
    <div className={`stat-card machine-calm-card machine-calm-stat machine-calm-tone-${tone}`}>
      <div className="machine-calm-stat-head">
        <span className="stat-icon-wrap machine-calm-icon-wrap">
          <Icon size={18} />
        </span>
        <div className="stat-label" style={{ marginBottom: 0 }}>{label}</div>
      </div>
      <div className="stat-value machine-calm-stat-value">{value}</div>
      <div className="stat-sub">{subtext}</div>
    </div>
  )
}

export default function MachineDetail() {
  const { machineId } = useParams()
  const { get } = useApi()
  const navigate = useNavigate()

  const [machine, setMachine] = useState(null)
  const [analytics, setAnalytics] = useState(null)
  const [browser, setBrowser] = useState([])
  const [tab, setTab] = useState('overview')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      get(`/api/machines/${machineId}`),
      get(`/api/analytics/machine/${machineId}`),
      get(`/api/analytics/browser/${machineId}?limit=50`),
    ])
      .then(([m, a, b]) => {
        setMachine(m)
        setAnalytics(a)
        setBrowser(Array.isArray(b) ? b : [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [get, machineId])

  useEffect(() => {
    const timer = setInterval(() => {
      get(`/api/machines/${machineId}`)
        .then((fresh) => setMachine((current) => (current ? { ...current, ...fresh } : fresh)))
        .catch(() => {})
    }, 15000)
    return () => clearInterval(timer)
  }, [get, machineId])

  const downloadReport = () => {
    get(`/api/reports/generate/${machineId}`)
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `CropSentinel_${machine?.hostname}.pdf`
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch(() => {})
  }

  if (loading) {
    return <div className="loading-center"><div className="spinner" style={{ width: 32, height: 32 }} /></div>
  }
  if (!machine) {
    return <div className="loading-center" style={{ color: 'var(--red)' }}>Machine not found</div>
  }

  const appUsage = analytics?.app_usage || []
  const appPie = appUsage.slice(0, 6).map((a) => ({ name: a.app_name, value: a.total_seconds }))
  const hourly = Array.from({ length: 24 }, (_, h) => {
    const hour = String(h).padStart(2, '0')
    const row = (analytics?.hourly_activity || []).find((entry) => entry.hour === hour)
    return { hour: `${hour}:00`, mins: Math.round((row?.total_seconds || 0) / 60) }
  })
  const topApp = appUsage[0]
  const consentLabel = machine.consent_given ? 'Granted' : 'Pending'
  const badgeClass = machine.online ? 'badge-green' : 'badge-gray'
  const health = safeHealth(machine.agent_health)
  const queueHealth = safeHealth(health.queue)
  const runtimeHealth = safeHealth(health.runtime)
  const policyHealth = safeHealth(health.policy)
  const selfThrottleHealth = safeHealth(health.self_throttle)

  return (
    <div className="fade-in machine-calm-shell">
      <div className="machine-calm-hero">
        <button
          onClick={() => navigate('/machines')}
          className="machine-calm-back"
        >
          Back to Machines
        </button>

        <div className="page-header machine-calm-header" style={{ marginBottom: 0 }}>
          <div className="machine-calm-title-wrap">
            <div className="machine-calm-avatar">
              <MachinesIcon size={24} />
            </div>
            <div>
              <div className="machine-calm-title-row">
                <div className="mono machine-calm-title">{machine.hostname}</div>
                <span className={`badge ${badgeClass}`}>
                  {machine.online ? 'Online' : 'Offline'}
                </span>
              </div>
              <div className="page-subtitle machine-calm-subtitle">
                {machine.username || 'Unknown user'} · {machine.ip_address || 'No IP'} · {machine.os || 'Unknown OS'}
              </div>
            </div>
          </div>

          <div className="page-actions">
            <button className="btn btn-outline btn-sm machine-calm-btn" onClick={() => navigate(`/live?machine=${machineId}`)}>
              Live View
            </button>
            <button className="btn btn-primary btn-sm machine-calm-primary" onClick={downloadReport}>
              PDF Report
            </button>
          </div>
        </div>
      </div>

      <div className="grid-4" style={{ marginBottom: 20 }}>
        <DetailMetricCard
          icon={TimeIcon}
          label="Active Time"
          value={fmt(analytics?.total_active_seconds || 0)}
          subtext={`${analytics?.browser_visits || 0} browser visits`}
          tone="brand"
        />
        <DetailMetricCard
          icon={AppIcon}
          label="Top App"
          value={topApp?.app_name || '--'}
          subtext={fmt(topApp?.total_seconds || 0)}
          tone="sage"
        />
        <DetailMetricCard
          icon={ChartBarIcon}
          label="CPU / RAM"
          value={`${Math.round(machine.cpu_percent || 0)}% / ${Math.round(machine.memory_percent || 0)}%`}
          subtext="Current resource usage"
          tone="sand"
        />
        <DetailMetricCard
          icon={AverageHoursIcon}
          label="Active App"
          value={machine.active_app || '--'}
          subtext={`Idle ${Math.round((machine.idle_seconds || 0) / 60)}m`}
          tone="slate"
        />
      </div>

      <div className="tab-group machine-calm-tabs" style={{ marginBottom: 20, display: 'flex' }}>
        {TABS.map((entry) => {
          const Icon = entry.icon
          return (
            <button
              key={entry.id}
              className={`tab-btn${tab === entry.id ? ' active' : ''}`}
              onClick={() => setTab(entry.id)}
            >
              <Icon size={15} />
              {entry.label}
            </button>
          )
        })}
      </div>

      {tab === 'overview' && (
        <div className="slide-in" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="grid-2">
            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 16 }}>
                <div>
                  <div className="card-title">App Distribution</div>
                  <div className="stat-sub">A softer breakdown of the most active applications.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap">
                  <ChartPieIcon size={18} />
                </span>
              </div>
              {appPie.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-state-icon"><AppIcon size={34} /></div>
                  <div className="empty-state-title">No app data</div>
                </div>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <ResponsiveContainer width={160} height={160}>
                    <PieChart>
                      <Pie data={appPie} cx="50%" cy="50%" innerRadius={45} outerRadius={72} dataKey="value" stroke="none">
                        {appPie.map((_, i) => <Cell key={i} fill={calmChartColors[i % calmChartColors.length]} />)}
                      </Pie>
                      <Tooltip formatter={(v) => fmt(v)} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {appPie.map((d, i) => (
                      <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                        <div style={{ width: 8, height: 8, borderRadius: 999, background: calmChartColors[i % calmChartColors.length], flexShrink: 0 }} />
                        <span style={{ flex: 1, color: 'var(--text-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</span>
                        <span className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{fmt(d.value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 16 }}>
                <div>
                  <div className="card-title">Hourly Activity</div>
                  <div className="stat-sub">Minutes active through the day.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap">
                  <ChartBarIcon size={18} />
                </span>
              </div>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={hourly} barSize={8} margin={{ left: -20, right: 4, top: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="hour" tick={{ fontSize: 9 }} interval={3} tickFormatter={(v) => v.slice(0, 2)} />
                  <YAxis tick={{ fontSize: 9 }} unit="m" />
                  <Tooltip content={<TTip />} />
                  <Bar dataKey="mins" name="Minutes" fill="#6b8bb6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card machine-calm-card">
            <div className="card-header" style={{ marginBottom: 16 }}>
              <div>
                <div className="card-title">Machine Details</div>
                <div className="stat-sub">Key enrollment and connectivity metadata.</div>
              </div>
              <span className="stat-icon-wrap machine-calm-icon-wrap">
                <NetworkIcon size={18} />
              </span>
            </div>
            <div className="machine-calm-detail-grid">
              {[
                ['Machine ID', machine.machine_id ? `${machine.machine_id.slice(0, 20)}...` : '--', true],
                ['Hostname', machine.hostname || '--', true],
                ['Username', machine.username || '--', false],
                ['OS', `${machine.os || '--'} ${machine.os_version || ''}`.trim(), false],
                ['IP Address', machine.ip_address || '--', true],
                ['MAC Address', machine.mac_address || '--', true],
                ['Agent Version', machine.agent_version || '--', false],
                ['First Seen', fmtTs(machine.first_seen), false],
                ['Last Seen', fmtTs(machine.last_seen), false],
                ['Consent', consentLabel, false],
              ].map(([k, v, mono]) => (
                <div key={k} className="machine-calm-detail-item">
                  <div className="machine-calm-detail-label">{k}</div>
                  <div className={mono ? 'mono machine-calm-detail-value' : 'machine-calm-detail-value'}>{v}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === 'apps' && (
        <div className="slide-in">
          {!appUsage.length ? (
            <div className="empty-state machine-calm-card">
              <div className="empty-state-icon"><AppIcon size={34} /></div>
              <div className="empty-state-title">No app data</div>
            </div>
          ) : (
            <div className="card machine-calm-card" style={{ padding: 0, overflow: 'hidden' }}>
              <table className="data-table machine-calm-table">
                <thead>
                  <tr><th>#</th><th>App</th><th>Time</th><th>Sessions</th><th>Share</th></tr>
                </thead>
                <tbody>
                  {appUsage.map((a, i) => {
                    const maxS = appUsage[0]?.total_seconds || 1
                    const pct = Math.round((a.total_seconds / maxS) * 100)
                    return (
                      <tr key={`${a.app_name}-${i}`}>
                        <td style={{ color: 'var(--text-3)', fontSize: 12 }}>{i + 1}</td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{ width: 8, height: 8, borderRadius: 999, background: calmChartColors[i % calmChartColors.length], flexShrink: 0 }} />
                            <span style={{ fontSize: 12, fontWeight: 600 }}>{a.app_name}</span>
                          </div>
                        </td>
                        <td className="mono" style={{ fontSize: 12, color: '#5c8a92', fontWeight: 600 }}>{fmt(a.total_seconds)}</td>
                        <td style={{ fontSize: 12, color: 'var(--text-2)' }}>{a.sessions}</td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div className="machine-calm-meter">
                              <div style={{ width: `${pct}%`, height: '100%', background: calmChartColors[i % calmChartColors.length], borderRadius: 999 }} />
                            </div>
                            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{pct}%</span>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'browser' && (
        <div className="slide-in">
          {!browser.length ? (
            <div className="empty-state machine-calm-card">
              <div className="empty-state-icon"><DomainIcon size={34} /></div>
              <div className="empty-state-title">No browser history</div>
            </div>
          ) : (
            <div className="card machine-calm-card" style={{ padding: 0, overflow: 'hidden' }}>
              <table className="data-table machine-calm-table">
                <thead><tr><th>Time</th><th>Browser</th><th>Domain</th><th>Title</th><th>Duration</th></tr></thead>
                <tbody>
                  {browser.map((r, i) => (
                    <tr key={`${r.timestamp}-${i}`}>
                      <td className="mono" style={{ fontSize: 11, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>
                        {new Date(r.timestamp).toLocaleString()}
                      </td>
                      <td><span className="badge badge-blue" style={{ fontSize: 10 }}>{r.browser}</span></td>
                      <td className="mono" style={{ fontSize: 12, color: '#5c8a92' }}>{r.domain}</td>
                      <td style={{ fontSize: 12, color: 'var(--text-2)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <a href={r.url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }} title={r.url}>
                          {r.title || r.url || '--'}
                        </a>
                      </td>
                      <td className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>
                        {fmt(r.duration_seconds)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'diagnostics' && (
        <div className="slide-in" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="grid-4">
            <DetailMetricCard
              icon={NetworkIcon}
              label="Queue Depth"
              value={fmtCount(queueHealth.queue_depth)}
              subtext={`${fmtCount(queueHealth.buffer_size)} buffered locally`}
              tone="brand"
            />
            <DetailMetricCard
              icon={ChartBarIcon}
              label="WS ACK Pending"
              value={fmtCount(queueHealth.ws_ack_pending)}
              subtext={health.ws_connected ? 'WebSocket transport live' : 'HTTP fallback or disconnected'}
              tone="sage"
            />
            <DetailMetricCard
              icon={TimeIcon}
              label="Retry / Error"
              value={`${fmtPct(queueHealth.retry_rate || 0)} / ${fmtPct(queueHealth.error_rate || 0)}`}
              subtext={`${fmtCount(queueHealth.ack_timeouts)} ACK timeouts`}
              tone="sand"
            />
            <DetailMetricCard
              icon={AverageHoursIcon}
              label="Self-Throttle"
              value={selfThrottleHealth.active ? 'Active' : 'Idle'}
              subtext={selfThrottleHealth.reason || `Sync every ${fmtCount(queueHealth.sync_interval_s)}s`}
              tone="slate"
            />
          </div>

          <div className="grid-2">
            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 16 }}>
                <div>
                  <div className="card-title">Queue Diagnostics</div>
                  <div className="stat-sub">Offline queue depth, retries, and delivery health from the agent heartbeat.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap">
                  <NetworkIcon size={18} />
                </span>
              </div>
              <div className="machine-calm-detail-grid">
                {[
                  ['Queue Depth', fmtCount(queueHealth.queue_depth), true],
                  ['Buffer Size', fmtCount(queueHealth.buffer_size), true],
                  ['ACK Pending', fmtCount(queueHealth.ws_ack_pending), true],
                  ['Backpressure', queueHealth.backpressure ? 'true' : 'false', false],
                  ['Sync Interval', `${fmtCount(queueHealth.sync_interval_s)} sec`, false],
                  ['Enqueued', fmtCount(queueHealth.enqueued), true],
                  ['Sent', fmtCount(queueHealth.sent), true],
                  ['Failed', fmtCount(queueHealth.failed), true],
                  ['Retried', fmtCount(queueHealth.retried), true],
                  ['Dropped', fmtCount(queueHealth.dropped), true],
                  ['WS Sent', fmtCount(queueHealth.ws_sent), true],
                  ['HTTP Sent', fmtCount(queueHealth.http_sent), true],
                  ['ACK Timeouts', fmtCount(queueHealth.ack_timeouts), true],
                  ['Partial Failures', fmtCount(queueHealth.partial_failures), true],
                  ['Backpressure', queueHealth.backpressure ? 'true' : 'false', false],
                ].map(([k, v, mono]) => (
                  <div key={k} className="machine-calm-detail-item">
                    <div className="machine-calm-detail-label">{k}</div>
                    <div className={mono ? 'mono machine-calm-detail-value' : 'machine-calm-detail-value'}>{v}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 16 }}>
                <div>
                  <div className="card-title">Runtime Cadence</div>
                  <div className="stat-sub">The active performance profile currently applied on the endpoint.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap">
                  <TimeIcon size={18} />
                </span>
              </div>
              <div className="machine-calm-detail-grid">
                {[
                  ['Screenshot Interval', `${fmtCount(runtimeHealth.screenshot_interval_seconds)} sec`, false],
                  ['Browser Sync', `${fmtCount(runtimeHealth.browser_sync_interval_seconds)} sec`, false],
                  ['Heartbeat', `${fmtCount(runtimeHealth.heartbeat_interval_seconds)} sec`, false],
                  ['App Tracker', `${fmtCount(runtimeHealth.app_tracker_interval_seconds)} sec`, false],
                  ['Network Tracker', `${fmtCount(runtimeHealth.network_interval_seconds)} sec`, false],
                  ['USB Tracker', `${fmtCount(runtimeHealth.usb_interval_seconds)} sec`, false],
                  ['Print Tracker', `${fmtCount(runtimeHealth.print_interval_seconds)} sec`, false],
                  ['File Fast Sweep', `${fmtCount(runtimeHealth.file_cache_fast_sweep_seconds)} sec`, false],
                  ['File Recursive Sweep', `${fmtCount(runtimeHealth.file_cache_recursive_sweep_seconds)} sec`, false],
                  ['File Sweeper Enabled', runtimeHealth.file_cache_sweeper_enabled ? 'true' : 'false', false],
                  ['Configured Screenshot', `${fmtCount(runtimeHealth.configured_screenshot_interval_seconds)} sec`, false],
                  ['Configured Browser Sync', `${fmtCount(runtimeHealth.configured_browser_sync_interval_seconds)} sec`, false],
                  ['Configured Heartbeat', `${fmtCount(runtimeHealth.configured_heartbeat_interval_seconds)} sec`, false],
                  ['WebSocket Connected', health.ws_connected ? 'true' : 'false', false],
                  ['DLP Policy Version', fmtCount(policyHealth.dlp_policy_version), true],
                  ['Phishing Policy Version', fmtCount(policyHealth.phishing_policy_version), true],
                ].map(([k, v, mono]) => (
                  <div key={k} className="machine-calm-detail-item">
                    <div className="machine-calm-detail-label">{k}</div>
                    <div className={mono ? 'mono machine-calm-detail-value' : 'machine-calm-detail-value'}>{v}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 16 }}>
                <div>
                  <div className="card-title">Throttle Policy</div>
                  <div className="stat-sub">Automatic protection thresholds that temporarily slow expensive collectors on stressed endpoints.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap">
                  <AverageHoursIcon size={18} />
                </span>
              </div>
              <div className="machine-calm-detail-grid">
                {[
                  ['Enabled', selfThrottleHealth.enabled ? 'true' : 'false', false],
                  ['Active', selfThrottleHealth.active ? 'true' : 'false', false],
                  ['Reason', selfThrottleHealth.reason || '--', false],
                  ['CPU Threshold', `${fmtCount(selfThrottleHealth.cpu_percent_threshold)}%`, false],
                  ['Memory Threshold', `${fmtCount(selfThrottleHealth.memory_percent_threshold)}%`, false],
                  ['Queue Threshold', fmtCount(selfThrottleHealth.queue_depth_threshold), true],
                  ['Multiplier', `${Number(selfThrottleHealth.interval_multiplier || 0).toFixed(1)}x`, false],
                  ['Cooldown', `${fmtCount(selfThrottleHealth.cooldown_seconds)} sec`, false],
                ].map(([k, v, mono]) => (
                  <div key={k} className="machine-calm-detail-item">
                    <div className="machine-calm-detail-label">{k}</div>
                    <div className={mono ? 'mono machine-calm-detail-value' : 'machine-calm-detail-value'}>{v}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
