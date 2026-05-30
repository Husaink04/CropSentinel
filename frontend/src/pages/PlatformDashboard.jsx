import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePlatformApi } from './PlatformLayout'
import { InlineBanner, PageStateView } from '../components/ui/PageState'
import { usePageContext } from '../hooks/usePageContext'

const fmtDate = ts => {
  if (!ts) return '--'
  const d = new Date(ts)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function PlatformDashboard() {
  const api = usePlatformApi()
  const navigate = useNavigate()
  const { setPageContext, clearPageContext } = usePageContext()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchStats = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get('/api/platform/stats')
      setData(res)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => { fetchStats() }, [fetchStats])
  useEffect(() => {
    setPageContext('Platform Scope', 'Cross-tenant overview')
    return () => clearPageContext()
  }, [setPageContext, clearPageContext])

  const safe = data || {
    active_tenants: 0,
    max_tenants: 0,
    total_machines: 0,
    active_seats: 0,
    total_users: 0,
    license_tier: 'none',
    license_customer: '--',
    max_seats: 0,
    license_expires: null,
    tenant_list: [],
  }

  const seatPct = safe.max_seats ? Math.round((safe.active_seats / safe.max_seats) * 100) : 0
  const tenantPct = safe.max_tenants ? Math.round((safe.active_tenants / safe.max_tenants) * 100) : 0

  return (
    <div className="fade-in">
      <div className="platform-page-head">
        <div>
          <div className="platform-page-title">Platform Overview</div>
          <div className="platform-page-sub">Cross-tenant health, capacity, and license posture</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-outline btn-sm" onClick={fetchStats}>Refresh</button>
          <button className="btn btn-primary btn-sm" onClick={() => navigate('/platform/tenants')}>Manage Tenants</button>
        </div>
      </div>

      {error && (
        <InlineBanner
          tone="danger"
          title="Failed to load platform stats"
          message={error.message}
          actionLabel="Retry"
          onAction={fetchStats}
          onClose={() => setError(null)}
        />
      )}

      <PageStateView
        state={loading ? 'loading' : (error && !data ? 'error' : 'ready')}
        title="Could not load platform data"
        message={error?.message || 'Retry to continue.'}
        onRetry={fetchStats}
      >
        <div className="platform-grid-4" style={{ marginBottom: 12 }}>
          <div className="platform-card">
            <div className="platform-stat-label">Active Tenants</div>
            <div className="platform-stat-value" style={{ color: 'var(--brand)' }}>{safe.active_tenants}</div>
            <div className="platform-stat-sub">
              {safe.max_tenants ? `of ${safe.max_tenants} allowed` : 'Unlimited'}
            </div>
          </div>
          <div className="platform-card">
            <div className="platform-stat-label">Total Machines</div>
            <div className="platform-stat-value" style={{ color: 'var(--cyan)' }}>{safe.total_machines}</div>
            <div className="platform-stat-sub">{safe.active_seats} active seats in use</div>
          </div>
          <div className="platform-card">
            <div className="platform-stat-label">Total Users</div>
            <div className="platform-stat-value" style={{ color: 'var(--purple)' }}>{safe.total_users}</div>
            <div className="platform-stat-sub">Across all tenants</div>
          </div>
          <div className="platform-card">
            <div className="platform-stat-label">License Tier</div>
            <div className="platform-stat-value" style={{ color: 'var(--green)' }}>{String(safe.license_tier || 'none').toUpperCase()}</div>
            <div className="platform-stat-sub">{safe.license_customer || '--'}</div>
          </div>
        </div>

        <div className="platform-grid-2" style={{ marginBottom: 12 }}>
          <div className="platform-card">
            <div className="platform-stat-label">Seat Usage</div>
            <div className="platform-stat-sub">{safe.active_seats} / {safe.max_seats || '∞'}</div>
            <div className="platform-progress"><span style={{ width: `${Math.min(100, seatPct)}%` }} /></div>
          </div>
          <div className="platform-card">
            <div className="platform-stat-label">Tenant Slots</div>
            <div className="platform-stat-sub">{safe.active_tenants} / {safe.max_tenants || '∞'}</div>
            <div className="platform-progress"><span style={{ width: `${Math.min(100, tenantPct)}%` }} /></div>
          </div>
        </div>

        <div className="platform-card" style={{ marginBottom: 12 }}>
          <div className="platform-stat-label">License Details</div>
          <div className="platform-grid-4" style={{ marginTop: 10 }}>
            <div><strong>Tier</strong><div className="platform-page-sub">{String(safe.license_tier || 'none').toUpperCase()}</div></div>
            <div><strong>Customer</strong><div className="platform-page-sub">{safe.license_customer || '--'}</div></div>
            <div><strong>Max Seats</strong><div className="platform-page-sub">{safe.max_seats || 'Unlimited'}</div></div>
            <div><strong>Expires</strong><div className="platform-page-sub">{fmtDate(safe.license_expires)}</div></div>
          </div>
        </div>

        <div className="platform-table-wrap">
          <table className="platform-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Slug</th>
                <th>Status</th>
                <th>Machines</th>
                <th>Users</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {(safe.tenant_list || []).map((t) => (
                <tr key={t.id}>
                  <td style={{ fontWeight: 700 }}>{t.name}</td>
                  <td className="mono" style={{ color: 'var(--text-3)' }}>{t.slug}</td>
                  <td>
                    <span className={`badge ${t.status === 'active' ? 'badge-green' : 'badge-amber'}`}>
                      {t.status === 'active' ? 'Active' : 'Suspended'}
                    </span>
                  </td>
                  <td>{t.machine_count}</td>
                  <td>{t.user_count}</td>
                  <td style={{ color: 'var(--text-3)' }}>{fmtDate(t.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </PageStateView>
    </div>
  )
}
