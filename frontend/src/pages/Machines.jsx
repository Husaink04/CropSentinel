import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, useWsListener } from '../hooks/useAuth'
import { useNotifications } from '../hooks/useNotifications'
import { usePageContext } from '../hooks/usePageContext'
import { InlineBanner } from '../components/ui/PageState'
import {
  MachinesIcon,
  OnlineIcon,
  OfflineIcon,
  TodayIcon,
} from '../components/ui/OverviewIcons'

const PAGE_SIZES = [25, 50, 100, 200]
const DEFAULT_PAGE_SIZE = 50
const SEARCH_DEBOUNCE_MS = 250

const fmtAgo = (ts) => {
  if (!ts) return '--'
  const s = Math.floor((Date.now() - new Date(ts)) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function MetricCard({ icon: Icon, label, value, colorClass, subtext }) {
  return (
    <div className={`stat-card machine-calm-card machine-calm-stat ${colorClass}`}>
      <div className="machine-calm-stat-head">
        <span className="stat-icon-wrap machine-calm-icon-wrap">
          <Icon size={18} />
        </span>
        <div className="stat-label" style={{ marginBottom: 0 }}>{label}</div>
      </div>
      <div className="stat-value machine-calm-stat-value">{value}</div>
      {subtext ? <div className="stat-sub">{subtext}</div> : null}
    </div>
  )
}

function MachineEmptyState() {
  return (
    <div className="empty-state machine-calm-empty">
      <div className="empty-state-icon machine-calm-empty-icon">
        <MachinesIcon size={40} />
      </div>
      <div className="empty-state-title">No machines found</div>
      <div className="empty-state-sub">Deploy the agent or adjust filters to see enrolled devices.</div>
    </div>
  )
}

export default function Machines() {
  const { get, del } = useApi()
  const { push } = useNotifications()
  const { setPageContext, clearPageContext } = usePageContext()
  const navigate = useNavigate()

  const [machines, setMachines] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [confirm, setConfirm] = useState(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [summary, setSummary] = useState({ total: 0, online: 0 })

  useEffect(() => {
    setPageContext('Tenant Scope', 'Machines')
    return () => clearPageContext()
  }, [setPageContext, clearPageContext])

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, filter, pageSize])

  const loadSummary = useCallback(() => {
    get('/api/machines?limit=1')
      .then((res) => {
        const grand = res?._meta?.total ?? (Array.isArray(res) ? res.length : 0)
        get('/api/machines?limit=1&status=online')
          .then((onlineRows) => {
            const onlineTotal = onlineRows?._meta?.total ?? 0
            setSummary({ total: grand, online: onlineTotal })
          })
          .catch(() => setSummary({ total: grand, online: 0 }))
      })
      .catch(() => {})
  }, [get])

  const load = useCallback(() => {
    setLoading(true)
    setLoadError(null)
    const params = new URLSearchParams({
      limit: String(pageSize),
      offset: String((page - 1) * pageSize),
    })
    if (debouncedSearch) params.set('search', debouncedSearch)
    if (filter !== 'all') params.set('status', filter)

    get(`/api/machines?${params.toString()}`)
      .then((res) => {
        setMachines(Array.isArray(res) ? res : [])
        setTotal(res?._meta?.total ?? (Array.isArray(res) ? res.length : 0))
      })
      .catch((err) => setLoadError(err))
      .finally(() => setLoading(false))
  }, [debouncedSearch, filter, get, page, pageSize])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadSummary() }, [loadSummary])

  useWsListener((msg) => {
    if (['machine_online', 'machine_offline', 'machine_unstable'].includes(msg.type)) {
      load()
      loadSummary()
    }
  })

  const deleteMachine = async (m) => {
    try {
      await del(`/api/machines/${m.machine_id}`)
      push({ type: 'success', title: `${m.hostname} deleted` })
      load()
    } catch (e) {
      push({ type: 'error', title: e.message, message: e.actionable_hint || '' })
    } finally {
      setConfirm(null)
    }
  }

  const deleteActivity = async (m) => {
    try {
      await del(`/api/machines/${m.machine_id}/activity`)
      push({ type: 'success', title: `Activity cleared for ${m.hostname}` })
    } catch (e) {
      push({ type: 'error', title: e.message, message: e.actionable_hint || '' })
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])
  const pageStart = (page - 1) * pageSize

  if (loading) {
    return <div className="loading-center"><div className="spinner" style={{ width: 28, height: 28 }} /></div>
  }

  return (
    <div className="fade-in machine-calm-shell">
      <div className="page-header machine-calm-header">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <MachinesIcon size={24} />
          </div>
          <div>
            <div className="page-title">Machines</div>
            <div className="page-subtitle">A calmer view of your device fleet with live health and usage signals.</div>
          </div>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline btn-sm machine-calm-btn" onClick={load}>Refresh</button>
        </div>
      </div>

      {loadError && (
        <InlineBanner
          tone="danger"
          title="Failed to load machine list"
          message={loadError.message}
          actionLabel="Retry"
          onAction={load}
          onClose={() => setLoadError(null)}
        />
      )}

      <div className="grid-4" style={{ marginBottom: 20 }}>
        <MetricCard icon={MachinesIcon} label="Total" value={summary.total} colorClass="machine-calm-tone-brand" subtext="Registered machines" />
        <MetricCard icon={OnlineIcon} label="Online" value={summary.online} colorClass="machine-calm-tone-sage" subtext="Currently connected" />
        <MetricCard icon={OfflineIcon} label="Offline" value={Math.max(0, summary.total - summary.online)} colorClass="machine-calm-tone-sand" subtext="Need attention" />
        <MetricCard icon={TodayIcon} label="With Consent" value={machines.filter((m) => m.consent_given).length} colorClass="machine-calm-tone-slate" subtext="Visible on this page" />
      </div>

      <div className="filter-bar machine-calm-toolbar">
        <input
          className="input-field machine-calm-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search hostname, user, IP..."
          style={{ maxWidth: 320, fontSize: 12 }}
        />
        <div className="tab-group machine-calm-tabs">
          {['all', 'online', 'offline'].map((status) => (
            <button
              key={status}
              className={`tab-btn${filter === status ? ' active' : ''}`}
              onClick={() => setFilter(status)}
              style={{ textTransform: 'capitalize' }}
            >
              {status}
            </button>
          ))}
        </div>
        <span style={{ fontSize: 12, color: 'var(--text-3)', marginLeft: 'auto' }}>
          {total} machine{total !== 1 ? 's' : ''}
        </span>
      </div>

      {total === 0 ? (
        <MachineEmptyState />
      ) : (
        <div className="card machine-calm-card machine-calm-table-shell" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="data-table machine-calm-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Machine</th>
                <th>User</th>
                <th>OS</th>
                <th>IP</th>
                <th>CPU</th>
                <th>RAM</th>
                <th>Last Seen</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {machines.map((m) => {
                const cpu = Math.round(m.cpu_percent || 0)
                const ram = Math.round(m.memory_percent || 0)
                return (
                  <tr key={m.machine_id}>
                    <td>
                      <span className={m.online ? 'dot-online' : 'dot-offline'} />
                    </td>
                    <td>
                      <button
                        onClick={() => navigate(`/machines/${m.machine_id}`)}
                        className="machine-calm-machine-link"
                      >
                        <div className="machine-calm-machine-main">
                          <span className="machine-calm-machine-badge">
                            <MachinesIcon size={14} />
                          </span>
                          <div>
                            <div className="mono machine-calm-machine-name">{m.hostname}</div>
                            <div className="machine-calm-machine-id">{m.machine_id.slice(0, 16)}...</div>
                          </div>
                        </div>
                      </button>
                    </td>
                    <td style={{ fontSize: 12, color: 'var(--text-2)' }}>{m.username || '--'}</td>
                    <td style={{ fontSize: 12, color: 'var(--text-3)' }}>{m.os || '--'}</td>
                    <td className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{m.ip_address || '--'}</td>
                    <td>
                      <div className="machine-calm-usage">
                        <div className="machine-calm-meter">
                          <div className="machine-calm-meter-fill machine-calm-meter-cpu" style={{ width: `${cpu}%` }} />
                        </div>
                        <span className="mono machine-calm-usage-text">{cpu}%</span>
                      </div>
                    </td>
                    <td>
                      <div className="machine-calm-usage">
                        <div className="machine-calm-meter">
                          <div className="machine-calm-meter-fill machine-calm-meter-ram" style={{ width: `${ram}%` }} />
                        </div>
                        <span className="mono machine-calm-usage-text">{ram}%</span>
                      </div>
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--text-3)' }}>{fmtAgo(m.last_seen)}</td>
                    <td>
                      <div style={{ display: 'flex', gap: 5 }}>
                        <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => navigate(`/machines/${m.machine_id}`)}>Detail</button>
                        <button className="btn btn-danger btn-sm" onClick={() => setConfirm(m)} style={{ fontSize: 11 }}>Delete</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {total > pageSize && (
            <div className="machine-calm-pagination">
              <div>
                Showing <strong style={{ color: 'var(--text-1)' }}>{pageStart + 1}</strong>-
                <strong style={{ color: 'var(--text-1)' }}>{Math.min(pageStart + pageSize, total)}</strong>
                {' '}of <strong style={{ color: 'var(--text-1)' }}>{total}</strong>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>Per page</span>
                  <select
                    value={pageSize}
                    onChange={(e) => setPageSize(Number(e.target.value))}
                    className="input-field"
                    style={{ padding: '4px 8px', fontSize: 12, width: 'auto' }}
                  >
                    {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </label>
                <div style={{ display: 'flex', gap: 4 }}>
                  <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => setPage(1)} disabled={page <= 1} aria-label="First page">{'<<'}</button>
                  <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} aria-label="Previous page">{'<'}</button>
                  <span style={{ padding: '4px 10px', fontSize: 12, color: 'var(--text-2)' }}>
                    Page {page} / {totalPages}
                  </span>
                  <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} aria-label="Next page">{'>'}</button>
                  <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => setPage(totalPages)} disabled={page >= totalPages} aria-label="Last page">{'>>'}</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {confirm && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 20 }}>
          <div className="card machine-calm-card" style={{ maxWidth: 360, padding: 28 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--red)', marginBottom: 8 }}>Delete Machine?</div>
            <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 20, lineHeight: 1.6 }}>
              This permanently deletes <strong className="mono">{confirm.hostname}</strong> and all its
              activity data, screenshots, and alert logs. This cannot be undone.
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between', flexWrap: 'wrap' }}>
              <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => deleteActivity(confirm)}>Clear Activity Only</button>
              <div style={{ display: 'flex', gap: 10, marginLeft: 'auto' }}>
                <button className="btn btn-outline btn-sm machine-calm-btn" onClick={() => setConfirm(null)}>Cancel</button>
                <button className="btn btn-danger btn-sm" onClick={() => deleteMachine(confirm)}>Delete</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
