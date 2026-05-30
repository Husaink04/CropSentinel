import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useApi } from '../hooks/useAuth'
import { useNotifications } from '../hooks/useNotifications'
import { usePageContext } from '../hooks/usePageContext'
import { InlineBanner, PageStateView } from '../components/ui/PageState'
import {
  AverageHoursIcon,
  MachinesIcon,
  OnlineIcon,
  AlertsIcon,
  ChartLineIcon,
  ChartPieIcon,
} from '../components/ui/OverviewIcons'

const COLORS = ['#5c8a92', '#7aa39b', '#c3aa87', '#8b95b5', '#6b8bb6', '#8ba79a']
const MACHINE_LIMIT = 25

const fmtDuration = (s) => {
  const v = Number(s || 0)
  const h = Math.floor(v / 3600)
  const m = Math.floor((v % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function TeamDashboardMetric({ icon: Icon, label, value, subtext, tone }) {
  return (
    <div className={`stat-card machine-calm-card machine-calm-stat ${tone}`}>
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

export default function TeamDashboard() {
  const { teamId } = useParams()
  const { get, post, del } = useApi()
  const { push } = useNotifications()
  const { setPageContext, clearPageContext } = usePageContext()
  const navigate = useNavigate()

  const [summary, setSummary] = useState(null)
  const [machines, setMachines] = useState([])
  const [totalMachines, setTotalMachines] = useState(0)
  const [allMachines, setAllMachines] = useState([])
  const [assignMachineId, setAssignMachineId] = useState('')
  const [machineSearch, setMachineSearch] = useState('')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [saving, setSaving] = useState(false)

  const rangeQuery = useMemo(() => {
    const params = new URLSearchParams()
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    return params.toString()
  }, [startDate, endDate])

  const loadSummary = useCallback(() => {
    const qs = rangeQuery ? `?${rangeQuery}` : ''
    return get(`/api/teams/${teamId}/productivity${qs}`).then(setSummary)
  }, [get, teamId, rangeQuery])

  const loadTeamMachines = useCallback(() => {
    const params = new URLSearchParams({
      limit: String(MACHINE_LIMIT),
      offset: String(offset),
    })
    if (machineSearch.trim()) params.set('search', machineSearch.trim())
    if (status) params.set('status', status)
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    return get(`/api/teams/${teamId}/machines?${params.toString()}`).then((rows) => {
      setMachines(Array.isArray(rows) ? rows : [])
      setTotalMachines(rows?._meta?.total ?? 0)
    })
  }, [get, teamId, offset, machineSearch, status, startDate, endDate])

  const loadAssignableMachines = useCallback(() => {
    return get('/api/machines?limit=500&offset=0').then((rows) => {
      setAllMachines(Array.isArray(rows) ? rows : [])
    })
  }, [get])

  const reload = useCallback(() => {
    setLoading(true)
    setLoadError(null)
    Promise.all([loadSummary(), loadTeamMachines(), loadAssignableMachines()])
      .catch((err) => setLoadError(err))
      .finally(() => setLoading(false))
  }, [loadSummary, loadTeamMachines, loadAssignableMachines])

  useEffect(() => { reload() }, [reload])
  useEffect(() => { setOffset(0) }, [machineSearch, status])
  useEffect(() => {
    setPageContext('Team', summary?.team?.name || teamId)
    return () => clearPageContext()
  }, [setPageContext, clearPageContext, summary?.team?.name, teamId])

  const assignMachine = async () => {
    if (!assignMachineId) return
    try {
      setSaving(true)
      await post(`/api/teams/${teamId}/machines`, { machine_id: assignMachineId })
      setAssignMachineId('')
      push({ type: 'success', title: 'Machine assigned to team' })
      reload()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setSaving(false)
    }
  }

  const removeMachine = async (machineId) => {
    if (!window.confirm('Remove this machine from the team?')) return
    try {
      setSaving(true)
      await del(`/api/teams/${teamId}/machines/${machineId}`)
      push({ type: 'success', title: 'Machine removed from team' })
      reload()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setSaving(false)
    }
  }

  const appUsage = (summary?.aggregated_app_usage || []).slice(0, 6).map((v) => ({
    name: v.app_name || 'Unknown',
    value: Number(v.total_seconds || 0),
  }))
  const trends = (summary?.team_trends || []).map((d) => ({
    date: d.date?.slice(5) || d.date,
    score: Number(d.avg_productivity || 0),
  }))
  const lowMachines = summary?.low_productivity_machines || []
  const teamFindings = summary?.findings || []
  const safeSummary = summary || {
    team: {},
    total_machines: 0,
    active_machines: 0,
    avg_productivity: 0,
    alerts_count: 0,
  }
  const avgProductivity = safeSummary.avg_productivity || safeSummary.summary?.avg_score || 0
  const activeMachines = safeSummary.active_machines || safeSummary.summary?.active_now || 0
  const totalMachineCount = safeSummary.total_machines || safeSummary.summary?.machine_count || 0

  return (
    <div className="fade-in machine-calm-shell">
      {loadError && (
        <InlineBanner
          tone="danger"
          title="Failed to load team dashboard"
          message={loadError.message}
          actionLabel="Retry"
          onAction={reload}
          onClose={() => setLoadError(null)}
        />
      )}

      <div className="machine-calm-hero">
        <button onClick={() => navigate('/teams')} className="machine-calm-back">Back to Teams</button>

        <PageStateView
          state={loading ? 'loading' : (loadError && !summary ? 'error' : (!summary ? 'empty' : 'ready'))}
          title={loadError ? 'Could not load team dashboard' : 'Team not found'}
          message={loadError ? (loadError.actionable_hint || loadError.message) : 'This team may have been removed or is not accessible.'}
          onRetry={reload}
        >
          <div className="page-header machine-calm-header">
            <div className="machine-calm-title-wrap">
              <div className="machine-calm-avatar">
                <AverageHoursIcon size={24} />
              </div>
              <div>
                <div className="page-title">{safeSummary.team?.name || 'Team'}</div>
                <div className="page-subtitle">{safeSummary.team?.description || 'Team productivity dashboard'}</div>
              </div>
            </div>
            <div className="page-actions team-dashboard-datebar">
              <input type="date" className="input-field machine-calm-search" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
              <input type="date" className="input-field machine-calm-search" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
              <button className="btn btn-outline btn-sm machine-calm-btn" onClick={reload} disabled={saving}>Refresh</button>
            </div>
          </div>

          <div className="grid-4" style={{ marginBottom: 14 }}>
            <TeamDashboardMetric icon={MachinesIcon} label="Total Machines" value={totalMachineCount} subtext="Assigned to this team" tone="machine-calm-tone-brand" />
            <TeamDashboardMetric icon={OnlineIcon} label="Active Now" value={activeMachines} subtext="Currently online" tone="machine-calm-tone-sage" />
            <TeamDashboardMetric icon={ChartLineIcon} label="Avg Productivity" value={`${avgProductivity}%`} subtext="Average score in range" tone="machine-calm-tone-sand" />
            <TeamDashboardMetric icon={AlertsIcon} label="Alerts" value={safeSummary.alerts_count || 0} subtext="Visible in current window" tone="machine-calm-tone-slate" />
          </div>

          <div className="grid-2" style={{ marginBottom: 14 }}>
            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 8 }}>
                <div>
                  <div className="card-title">Productivity Trend</div>
                  <div className="stat-sub">How this team has been scoring across the selected date range.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap"><ChartLineIcon size={18} /></span>
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={trends}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Line type="monotone" dataKey="score" stroke="#5c8a92" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 8 }}>
                <div>
                  <div className="card-title">Top App Usage</div>
                  <div className="stat-sub">Most active applications across machines in this team.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap"><ChartPieIcon size={18} /></span>
              </div>
              {appUsage.length === 0 ? (
                <div className="empty-state" style={{ minHeight: 180 }}>
                  <div className="empty-state-title">No app activity in range</div>
                </div>
              ) : (
                <div style={{ display: 'flex', gap: 10 }}>
                  <ResponsiveContainer width="55%" height={220}>
                    <PieChart>
                      <Pie data={appUsage} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80}>
                        {appUsage.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                      </Pie>
                      <Tooltip formatter={(v) => fmtDuration(v)} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div style={{ flex: 1, display: 'grid', alignContent: 'start', gap: 8 }}>
                    {appUsage.map((item, i) => (
                      <div key={item.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                        <span style={{ width: 8, height: 8, borderRadius: 8, background: COLORS[i % COLORS.length] }} />
                        <span style={{ flex: 1 }}>{item.name}</span>
                        <span className="mono" style={{ color: 'var(--text-3)' }}>{fmtDuration(item.value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {lowMachines.length > 0 && (
            <div className="card machine-calm-card" style={{ marginBottom: 14 }}>
              <div className="card-header" style={{ marginBottom: 10 }}>
                <div>
                  <div className="card-title" style={{ color: 'var(--amber)' }}>Low Productivity Machines</div>
                  <div className="stat-sub">Machines that may need review, coaching, or workload correction.</div>
                </div>
              </div>
              <div className="team-low-grid">
                {lowMachines.map((m) => (
                  <div key={m.machine_id} className="team-low-item">
                    <div>
                      <div className="mono" style={{ fontSize: 12, fontWeight: 700 }}>{m.hostname || m.machine_id}</div>
                      <div style={{ color: 'var(--text-3)', fontSize: 12, marginTop: 2 }}>{m.username || 'Unknown user'}</div>
                    </div>
                    <span style={{ color: 'var(--amber)', fontWeight: 700 }}>{m.productivity_score}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {teamFindings.length > 0 && (
            <div className="card machine-calm-card" style={{ marginBottom: 14 }}>
              <div className="card-header" style={{ marginBottom: 10 }}>
                <div>
                  <div className="card-title">Team Findings</div>
                  <div className="stat-sub">Cross-machine focus, distraction, and workload signals.</div>
                </div>
              </div>
              <div style={{ display: 'grid', gap: 10 }}>
                {teamFindings.slice(0, 6).map((finding, index) => (
                  <div key={`${finding.machine_id}-${index}`} style={{ border: '1px solid var(--border)', borderRadius: 12, padding: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700 }}>{finding.title}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>{finding.description}</div>
                      </div>
                      <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => navigate(`/machines/${finding.machine_id}/productivity`)}>
                        {finding.hostname || 'View'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid-2" style={{ marginBottom: 14 }}>
            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 10 }}>
                <div>
                  <div className="card-title">Assign Machine</div>
                  <div className="stat-sub">Add another machine into this team without leaving the page.</div>
                </div>
              </div>
              <div className="team-assign-grid">
                <select
                  className="input-field machine-calm-search"
                  value={assignMachineId}
                  onChange={(e) => setAssignMachineId(e.target.value)}
                >
                  <option value="">Select machine...</option>
                  {allMachines.map((m) => (
                    <option key={m.machine_id} value={m.machine_id}>
                      {m.hostname || m.machine_id} ({m.machine_id})
                    </option>
                  ))}
                </select>
                <button className="btn btn-primary machine-calm-primary" onClick={assignMachine} disabled={saving}>Assign</button>
              </div>
            </div>

            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 10 }}>
                <div>
                  <div className="card-title">Machine Filters</div>
                  <div className="stat-sub">Focus this table by search and connection state.</div>
                </div>
              </div>
              <div className="team-filter-grid">
                <input
                  className="input-field machine-calm-search"
                  placeholder="Search machines..."
                  value={machineSearch}
                  onChange={(e) => setMachineSearch(e.target.value)}
                />
                <select className="input-field machine-calm-search" value={status} onChange={(e) => setStatus(e.target.value)}>
                  <option value="">All status</option>
                  <option value="online">Online</option>
                  <option value="offline">Offline</option>
                </select>
                <div className="team-filter-count">
                  {totalMachines} machine{totalMachines !== 1 ? 's' : ''}
                </div>
              </div>
            </div>
          </div>

          <div className="card machine-calm-card" style={{ padding: 0, overflow: 'hidden' }}>
            {machines.length === 0 ? (
              <div className="empty-state" style={{ minHeight: 140 }}>
                <div className="empty-state-title">No machines in this team</div>
              </div>
            ) : (
              <table className="data-table machine-calm-table">
                <thead>
                  <tr>
                    <th>Machine</th>
                    <th>User</th>
                    <th>Status</th>
                    <th>Productivity</th>
                    <th>Active Time</th>
                    <th>Idle Time</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {machines.map((m) => (
                    <tr key={m.machine_id}>
                      <td>
                        <div className="machine-calm-machine-main">
                          <span className="machine-calm-machine-badge">
                            <MachinesIcon size={14} />
                          </span>
                          <div>
                            <div className="mono machine-calm-machine-name">{m.hostname || m.machine_id}</div>
                            <div className="machine-calm-machine-id">{m.machine_id.slice(0, 16)}...</div>
                          </div>
                        </div>
                      </td>
                      <td>{m.username || '--'}</td>
                      <td>
                        <span className={m.online ? 'badge badge-green' : 'badge badge-gray'}>
                          {m.online ? 'Online' : 'Offline'}
                        </span>
                      </td>
                      <td style={{ fontWeight: 700, color: 'var(--machine-calm-1)' }}>{m.productivity_score || 0}%</td>
                      <td>{fmtDuration(m.active_time_seconds)}</td>
                      <td>{fmtDuration(m.idle_time_seconds)}</td>
                      <td>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          <button
                            className="btn btn-ghost btn-sm machine-calm-btn"
                            onClick={() => navigate(`/machines/${m.machine_id}/productivity`)}
                          >
                            View
                          </button>
                          <button className="btn btn-danger btn-sm" onClick={() => removeMachine(m.machine_id)} disabled={saving}>
                            Remove
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {totalMachines > MACHINE_LIMIT && (
            <div className="machine-calm-pagination" style={{ marginTop: 10 }}>
              <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
                Showing {offset + 1}-{Math.min(offset + MACHINE_LIMIT, totalMachines)} of {totalMachines}
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                <button className="btn btn-ghost btn-sm machine-calm-btn" disabled={offset === 0} onClick={() => setOffset(0)}>{'<<'}</button>
                <button
                  className="btn btn-ghost btn-sm machine-calm-btn"
                  disabled={offset === 0}
                  onClick={() => setOffset((v) => Math.max(0, v - MACHINE_LIMIT))}
                >
                  {'<'}
                </button>
                <button
                  className="btn btn-ghost btn-sm machine-calm-btn"
                  disabled={offset + MACHINE_LIMIT >= totalMachines}
                  onClick={() => setOffset((v) => v + MACHINE_LIMIT)}
                >
                  {'>'}
                </button>
              </div>
            </div>
          )}
        </PageStateView>
      </div>
    </div>
  )
}
