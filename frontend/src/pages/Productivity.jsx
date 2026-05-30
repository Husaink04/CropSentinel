import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useApi } from '../hooks/useAuth'
import { VisitsIcon } from '../components/ui/OverviewIcons'

const COLORS = {
  productive: 'var(--success)',
  supportive: 'var(--brand)',
  neutral: 'var(--text-3)',
  distracting: 'var(--danger)',
  excluded: 'var(--border-1)',
}

const TAG_COLORS = {
  productive: 'badge-green',
  supportive: 'badge-blue',
  neutral: 'badge-gray',
  distracting: 'badge-red',
}

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'logs', label: 'Logs' },
  { id: 'rules', label: 'Rules' },
]

const fmtSecs = (seconds) => {
  if (!seconds || seconds <= 0) return '0m'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`
}

const scoreColor = (value) => (
  value >= 75 ? 'var(--success)' : value >= 50 ? 'var(--warning)' : 'var(--danger)'
)

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map((item, index) => (
        <div key={index} style={{ color: item.color || item.fill, fontWeight: 600, fontSize: 12 }}>
          {item.name}: {typeof item.value === 'number' ? Math.round(item.value) : item.value}
        </div>
      ))}
    </div>
  )
}

function RuleCard({ title, description, color, rules, onAdd, onRemove }) {
  const [value, setValue] = useState('')

  return (
    <div className="card machine-calm-card analytics-card" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--text-3)' }}>{description}</div>
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          className="input-field machine-calm-search"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && value.trim()) {
              onAdd(value.trim())
              setValue('')
            }
          }}
          placeholder="Add rule..."
          style={{ fontSize: 12 }}
        />
        <button
          className="btn btn-primary"
          onClick={() => {
            if (!value.trim()) return
            onAdd(value.trim())
            setValue('')
          }}
          style={{ padding: '8px 14px', flexShrink: 0 }}
        >
          +
        </button>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, minHeight: 40 }}>
        {rules.map((rule) => (
          <span
            key={`${rule.category}-${rule.match_value}`}
            className={`badge ${TAG_COLORS[color]}`}
            style={{ cursor: 'pointer', gap: 5 }}
            onClick={() => onRemove(rule.match_value)}
          >
            {rule.match_value}
            {rule.always_active ? ' *' : ''}
          </span>
        ))}
        {!rules.length && <span style={{ fontSize: 12, color: 'var(--text-3)' }}>No rules yet</span>}
      </div>
    </div>
  )
}

export default function Productivity() {
  const navigate = useNavigate()
  const { get, put } = useApi()

  const [tab, setTab] = useState('overview')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [overview, setOverview] = useState(null)
  const [machineRows, setMachineRows] = useState([])
  const [logs, setLogs] = useState([])
  const [policy, setPolicy] = useState({ productivity_apps: [], productivity_domains: [] })
  const [loading, setLoading] = useState(true)
  const [logsLoading, setLogsLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState(null)
  const [logFilters, setLogFilters] = useState({ machine_id: '', date: '', category: '' })

  const queryString = useMemo(() => {
    const params = new URLSearchParams()
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    return params.toString()
  }, [startDate, endDate])

  const showToast = (msg, type = 'green') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3200)
  }

  const loadOverview = useCallback(async () => {
    const qs = queryString ? `?${queryString}` : ''
    const [overviewPayload, machinePayload, settings] = await Promise.all([
      get(`/api/productivity/overview${qs}`),
      get(`/api/productivity/machines${qs}`),
      get('/api/settings'),
    ])
    setOverview(overviewPayload)
    setMachineRows(machinePayload.items || [])
    setPolicy({
      productivity_apps: settings.productivity_apps || [],
      productivity_domains: settings.productivity_domains || [],
    })
  }, [get, queryString])

  const loadLogs = useCallback(async () => {
    setLogsLoading(true)
    const params = new URLSearchParams({ limit: '200' })
    if (logFilters.machine_id) params.set('machine_id', logFilters.machine_id)
    if (logFilters.date) params.set('date', logFilters.date)
    const rows = await get(`/api/analytics/productivity-logs?${params}`)
    const filtered = logFilters.category
      ? rows.filter((row) => row.category === logFilters.category)
      : rows
    setLogs(filtered)
    setLogsLoading(false)
  }, [get, logFilters])

  useEffect(() => {
    setLoading(true)
    loadOverview().finally(() => setLoading(false))
  }, [loadOverview])

  useEffect(() => {
    if (tab === 'logs') {
      loadLogs().catch(() => {
        setLogs([])
        setLogsLoading(false)
      })
    }
  }, [tab, loadLogs])

  const updateRules = (collection, nextRules) => {
    setPolicy((current) => ({ ...current, [collection]: nextRules }))
  }

  const addRule = (collection, category, matchValue, alwaysActive = false) => {
    const normalized = matchValue.toLowerCase()
    const next = [...policy[collection]]
    if (next.some((rule) => rule.match_value === normalized && rule.category === category)) return
    next.push({
      match_value: normalized,
      match_type: 'contains',
      category,
      weight: category === 'productive' ? 1 : category === 'supportive' ? 0.72 : 0,
      always_active: alwaysActive,
    })
    updateRules(collection, next)
  }

  const removeRule = (collection, category, matchValue) => {
    updateRules(
      collection,
      policy[collection].filter((rule) => !(rule.category === category && rule.match_value === matchValue.toLowerCase())),
    )
  }

  const saveRules = async () => {
    setSaving(true)
    try {
      await put('/api/settings', {
        productivity_apps: policy.productivity_apps,
        productivity_domains: policy.productivity_domains,
      })
      showToast('Productivity policy saved')
      await loadOverview()
    } catch (error) {
      showToast(error.message, 'red')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="loading-center">
        <div className="spinner" style={{ width: 32, height: 32 }} />
        <span>Loading productivity analytics...</span>
      </div>
    )
  }

  const summary = overview?.summary || {}
  const scoreDistribution = (overview?.score_distribution || []).map((item) => ({
    name: item.band,
    value: item.count,
  }))
  const topFocusDrivers = overview?.top_focus_drivers || []
  const topDistractionDrivers = overview?.top_distraction_drivers || []
  const findings = overview?.findings || []
  const trend = overview?.trend || {}
  const machineChart = machineRows.slice(0, 10).map((row) => ({
    name: (row.hostname || row.machine_id || '').slice(0, 12),
    score: row.productivity_score || 0,
  }))

  const productiveAppRules = policy.productivity_apps.filter((rule) => rule.category === 'productive')
  const supportiveAppRules = policy.productivity_apps.filter((rule) => rule.category === 'supportive')
  const productiveDomainRules = policy.productivity_domains.filter((rule) => rule.category === 'productive')
  const supportiveDomainRules = policy.productivity_domains.filter((rule) => rule.category === 'supportive')
  const distractingDomainRules = policy.productivity_domains.filter((rule) => rule.category === 'distracting')

  return (
    <div className="fade-in analytics-shell" style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      <div className="page-header machine-calm-header analytics-hero" style={{ marginBottom: 20 }}>
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <VisitsIcon size={24} />
          </div>
          <div>
            <div className="page-title">Productivity Intelligence</div>
            <div className="page-subtitle">
              {summary.machine_count || 0} machine{summary.machine_count === 1 ? '' : 's'} tracked.
              Average score <strong style={{ color: scoreColor(summary.avg_score || 0) }}> {summary.avg_score || 0}</strong>.
            </div>
          </div>
        </div>
        <div className="page-actions" style={{ display: 'flex', gap: 8 }}>
          <input type="date" className="input-field machine-calm-search" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          <input type="date" className="input-field machine-calm-search" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          <button className="btn btn-outline machine-calm-btn btn-sm" onClick={loadOverview}>Refresh</button>
        </div>
      </div>

      <div className="grid-4" style={{ marginBottom: 20 }}>
        {[
          { label: 'Avg Score', value: summary.avg_score || 0, color: scoreColor(summary.avg_score || 0), sub: `${trend.direction || 'flat'} ${trend.score_delta || 0} vs previous` },
          { label: 'Focus Time', value: fmtSecs(summary.focus_time_seconds || 0), color: 'var(--brand)', sub: 'Sustained focused work' },
          { label: 'Distracting Share', value: `${Math.round((summary.distracting_share || 0) * 100)}%`, color: 'var(--danger)', sub: 'Across all active time' },
          { label: 'Workload Risk', value: summary.workload_risk_count || 0, color: 'var(--warning)', sub: `${summary.low_confidence_count || 0} low-confidence machines` },
        ].map((item) => (
          <div key={item.label} className="stat-card machine-calm-card machine-calm-stat analytics-kpi">
            <div className="stat-label">{item.label}</div>
            <div className="stat-value" style={{ color: item.color, fontSize: 32 }}>{item.value}</div>
            <div className="stat-sub">{item.sub}</div>
          </div>
        ))}
      </div>

      <div className="tab-group analytics-tabs" style={{ marginBottom: 20 }}>
        {TABS.map((entry) => (
          <button key={entry.id} className={`tab-btn ${tab === entry.id ? 'active' : ''}`} onClick={() => setTab(entry.id)}>
            {entry.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="slide-in" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="grid-2">
            <div className="card machine-calm-card analytics-card">
              <div className="card-header" style={{ marginBottom: 14 }}>
                <span className="card-title">Machine Scoreboard</span>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Top 10 by score</span>
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={machineChart} margin={{ top: 4, right: 16, bottom: 4, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10 }} domain={[0, 100]} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar dataKey="score" name="Score" radius={[4, 4, 0, 0]} maxBarSize={38} fill="var(--brand)" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="card machine-calm-card analytics-card">
              <div className="card-header" style={{ marginBottom: 14 }}>
                <span className="card-title">Score Distribution</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <ResponsiveContainer width="55%" height={220}>
                  <PieChart>
                    <Pie data={scoreDistribution} dataKey="value" nameKey="name" innerRadius={48} outerRadius={80}>
                      {scoreDistribution.map((_, index) => <Cell key={index} fill={['#0f9d8a', '#5c8a92', '#f5a623', '#dc2626'][index % 4]} />)}
                    </Pie>
                    <Tooltip content={<ChartTooltip />} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ flex: 1, display: 'grid', gap: 8 }}>
                  {scoreDistribution.map((item, index) => (
                    <div key={item.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                      <span style={{ width: 8, height: 8, borderRadius: 8, background: ['#0f9d8a', '#5c8a92', '#f5a623', '#dc2626'][index % 4] }} />
                      <span style={{ flex: 1 }}>{item.name}</span>
                      <span className="mono" style={{ color: 'var(--text-3)' }}>{item.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="grid-2">
            <div className="card machine-calm-card analytics-card">
              <div className="card-header" style={{ marginBottom: 10 }}>
                <span className="card-title">Top Focus Drivers</span>
              </div>
              {!topFocusDrivers.length ? (
                <div className="empty-state" style={{ minHeight: 140 }}>
                  <div className="empty-state-title">No focus drivers yet</div>
                </div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr><th>Tool</th><th>Time</th></tr>
                  </thead>
                  <tbody>
                    {topFocusDrivers.map((item) => (
                      <tr key={item.name}>
                        <td>{item.name}</td>
                        <td className="mono">{fmtSecs(item.seconds)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="card machine-calm-card analytics-card">
              <div className="card-header" style={{ marginBottom: 10 }}>
                <span className="card-title">Top Distraction Drivers</span>
              </div>
              {!topDistractionDrivers.length ? (
                <div className="empty-state" style={{ minHeight: 140 }}>
                  <div className="empty-state-title">No distraction drivers yet</div>
                </div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr><th>Domain</th><th>Time</th></tr>
                  </thead>
                  <tbody>
                    {topDistractionDrivers.map((item) => (
                      <tr key={item.name}>
                        <td>{item.name}</td>
                        <td className="mono">{fmtSecs(item.seconds)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="card machine-calm-card analytics-card">
            <div className="card-header" style={{ marginBottom: 10 }}>
              <span className="card-title">Findings Queue</span>
            </div>
            {!findings.length ? (
              <div style={{ textAlign: 'center', padding: 26, color: 'var(--text-3)' }}>No findings in this range</div>
            ) : (
              <div style={{ display: 'grid', gap: 10 }}>
                {findings.slice(0, 8).map((finding, index) => (
                  <div key={`${finding.machine_id}-${index}`} className="card" style={{ padding: 14, border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700 }}>{finding.title}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>{finding.description}</div>
                      </div>
                      <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/machines/${finding.machine_id}/productivity`)}>
                        {finding.hostname || 'Open'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card machine-calm-card analytics-card" style={{ padding: 0, overflow: 'hidden' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Machine</th>
                  <th>Score</th>
                  <th>Confidence</th>
                  <th>Focus</th>
                  <th>Distracting</th>
                  <th>Workload</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {machineRows.map((row) => (
                  <tr key={row.machine_id}>
                    <td>
                      <div style={{ display: 'grid', gap: 2 }}>
                        <span style={{ fontWeight: 700 }}>{row.hostname || row.machine_id}</span>
                        <span className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{row.username || '-'}</span>
                      </div>
                    </td>
                    <td style={{ color: scoreColor(row.productivity_score || 0), fontWeight: 700 }}>{row.productivity_score || 0}</td>
                    <td>{row.score_confidence || 0}%</td>
                    <td>{fmtSecs(row.focus_time_seconds)}</td>
                    <td>{fmtSecs(row.distracting_time_seconds)}</td>
                    <td>{row.workload_intensity_score || 0}</td>
                    <td>
                      <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/machines/${row.machine_id}/productivity`)}>
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'logs' && (
        <div className="slide-in" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="filter-bar analytics-filter-panel machine-calm-card">
            <select
              className="input-field machine-calm-search"
              style={{ maxWidth: 220 }}
              value={logFilters.machine_id}
              onChange={(e) => setLogFilters((current) => ({ ...current, machine_id: e.target.value }))}
            >
              <option value="">All Machines</option>
              {machineRows.map((machine) => (
                <option key={machine.machine_id} value={machine.machine_id}>{machine.hostname || machine.machine_id}</option>
              ))}
            </select>
            <input
              type="date"
              className="input-field machine-calm-search"
              style={{ maxWidth: 170 }}
              value={logFilters.date}
              onChange={(e) => setLogFilters((current) => ({ ...current, date: e.target.value }))}
            />
            <select
              className="input-field machine-calm-search"
              style={{ maxWidth: 220 }}
              value={logFilters.category}
              onChange={(e) => setLogFilters((current) => ({ ...current, category: e.target.value }))}
            >
              <option value="">All finding types</option>
              <option value="focus_finding">Focus</option>
              <option value="distraction_finding">Distraction</option>
              <option value="workload_finding">Workload</option>
              <option value="classification_gap_finding">Coverage gap</option>
              <option value="trend_finding">Trend</option>
            </select>
            <button className="btn btn-outline machine-calm-btn btn-sm" onClick={loadLogs}>Refresh</button>
            <span style={{ fontSize: 12, color: 'var(--text-3)', marginLeft: 'auto' }}>{logs.length} rows</span>
          </div>

          <div className="card machine-calm-card analytics-card" style={{ padding: 0, overflow: 'hidden' }}>
            <div className="card-header" style={{ padding: '16px 18px 0' }}>
              <span className="card-title">Productivity Logs</span>
            </div>
            {logsLoading ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <div className="spinner" style={{ width: 24, height: 24, margin: '0 auto' }} />
              </div>
            ) : !logs.length ? (
              <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-3)' }}>No productivity logs found</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Machine</th>
                    <th>User</th>
                    <th>Active</th>
                    <th>Focus</th>
                    <th>Score</th>
                    <th>Confidence</th>
                    <th>Major Driver</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((row, index) => (
                    <tr key={`${row.machine_id}-${index}`}>
                      <td className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{row.date}</td>
                      <td className="mono" style={{ fontSize: 12, color: 'var(--brand)' }}>{row.hostname}</td>
                      <td>{row.username || '-'}</td>
                      <td className="mono">{fmtSecs(row.active_time_seconds)}</td>
                      <td className="mono">{fmtSecs(row.focus_time_seconds)}</td>
                      <td style={{ color: scoreColor(row.score || 0), fontWeight: 700 }}>{row.score || 0}</td>
                      <td>{row.score_confidence || 0}%</td>
                      <td>{row.major_driver}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {tab === 'rules' && (
        <div className="slide-in" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div className="analytics-note" style={{ fontSize: 13, lineHeight: 1.7 }}>
            <strong style={{ color: 'var(--brand)' }}>How the policy works</strong><br />
            Productive rules drive the score hardest, supportive rules capture collaboration and research, and distracting domains pull the score down.
            Items marked with <strong>*</strong> are treated as always-active tools so meetings do not create false idle penalties.
          </div>
          <div className="grid-3">
            <RuleCard
              title="Productive Apps"
              description="Core work tools"
              color="productive"
              rules={productiveAppRules}
              onAdd={(value) => addRule('productivity_apps', 'productive', value)}
              onRemove={(value) => removeRule('productivity_apps', 'productive', value)}
            />
            <RuleCard
              title="Supportive Apps"
              description="Collaboration, docs, and AI assist"
              color="supportive"
              rules={supportiveAppRules}
              onAdd={(value) => addRule('productivity_apps', 'supportive', value, ['teams', 'zoom', 'meet', 'slack'].some((item) => value.toLowerCase().includes(item)))}
              onRemove={(value) => removeRule('productivity_apps', 'supportive', value)}
            />
            <RuleCard
              title="Distracting Domains"
              description="Known non-work sites"
              color="distracting"
              rules={distractingDomainRules}
              onAdd={(value) => addRule('productivity_domains', 'distracting', value)}
              onRemove={(value) => removeRule('productivity_domains', 'distracting', value)}
            />
          </div>
          <div className="grid-2">
            <RuleCard
              title="Productive Domains"
              description="Role-specific work sites"
              color="productive"
              rules={productiveDomainRules}
              onAdd={(value) => addRule('productivity_domains', 'productive', value)}
              onRemove={(value) => removeRule('productivity_domains', 'productive', value)}
            />
            <RuleCard
              title="Supportive Domains"
              description="Meetings, docs, and internal collaboration"
              color="supportive"
              rules={supportiveDomainRules}
              onAdd={(value) => addRule('productivity_domains', 'supportive', value, ['meet.', 'teams.', 'zoom'].some((item) => value.toLowerCase().includes(item)))}
              onRemove={(value) => removeRule('productivity_domains', 'supportive', value)}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button className="btn btn-primary" onClick={saveRules} disabled={saving} style={{ padding: '10px 22px' }}>
              {saving ? 'Saving...' : 'Save policy'}
            </button>
            <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
              Changes apply immediately to refreshed productivity analytics.
            </span>
          </div>
        </div>
      )}

      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: 24,
            right: 24,
            zIndex: 9999,
            background: 'var(--surface-3)',
            border: `1px solid ${toast.type === 'red' ? 'rgba(239,68,68,.3)' : 'rgba(16,185,129,.3)'}`,
            color: toast.type === 'red' ? 'var(--danger)' : 'var(--success)',
            padding: '12px 20px',
            borderRadius: 10,
            fontSize: 13,
            fontWeight: 500,
            boxShadow: 'var(--shadow-lg)',
          }}
        >
          {toast.type === 'red' ? 'Error:' : 'Saved:'} {toast.msg}
        </div>
      )}
    </div>
  )
}
