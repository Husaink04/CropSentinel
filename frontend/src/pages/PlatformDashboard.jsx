import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePlatformApi, usePlatformAuth } from './PlatformLayout'
import { InlineBanner, PageStateView } from '../components/ui/PageState'
import { usePageContext } from '../hooks/usePageContext'

const fmtDate = ts => {
  if (!ts) return '--'
  const d = new Date(ts)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

async function parseUploadResponse(res) {
  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return res.json().catch(() => ({}))
  }
  const text = await res.text().catch(() => '')
  return {
    detail: text.trim().startsWith('<')
      ? 'Server returned an unexpected HTML response.'
      : (text || 'License upload failed'),
  }
}

export default function PlatformDashboard() {
  const api = usePlatformApi()
  const { token, user } = usePlatformAuth()
  const navigate = useNavigate()
  const { setPageContext, clearPageContext } = usePageContext()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [uploadMessage, setUploadMessage] = useState('')
  const fileInputRef = useRef(null)

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
    setPageContext(user?.is_msp ? 'MSP Scope' : 'Platform Scope', user?.is_msp ? 'Partner tenant overview' : 'Cross-tenant overview')
    return () => clearPageContext()
  }, [clearPageContext, setPageContext, user?.is_msp])

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
    license_bootstrap_mode: false,
    license_error: '',
    tenant_list: [],
  }

  const isMsp = Boolean(user?.is_msp)
  const seatPct = safe.max_seats ? Math.round((safe.active_seats / safe.max_seats) * 100) : 0
  const tenantPct = safe.max_tenants ? Math.round((safe.active_tenants / safe.max_tenants) * 100) : 0
  const isBootstrap = Boolean(safe.license_bootstrap_mode)

  const openLicensePicker = useCallback(() => {
    setUploadError('')
    setUploadMessage('')
    fileInputRef.current?.click()
  }, [])

  const uploadLicense = useCallback(async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setUploading(true)
    setUploadError('')
    setUploadMessage('')
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch('/api/license/upload', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      })
      const payload = await parseUploadResponse(res)
      if (!res.ok) {
        throw new Error(payload?.detail || payload?.message || 'License upload failed')
      }
      setUploadMessage(`License installed: ${payload?.license?.license_id || file.name}`)
      await fetchStats()
    } catch (err) {
      setUploadError(err.message || 'License upload failed')
    } finally {
      setUploading(false)
    }
  }, [fetchStats, token])

  return (
    <div className="fade-in">
      <div className="platform-page-head">
        <div>
          <div className="platform-page-title">{isMsp ? 'MSP Partner Administration' : 'Platform Overview'}</div>
          <div className="platform-page-sub">
            {isMsp ? 'Monitor your client portfolio, active seats, and partner capacity.' : 'Cross-tenant health, capacity, and license posture'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-outline btn-sm" onClick={fetchStats}>Refresh</button>
          <button className="btn btn-primary btn-sm" onClick={() => navigate('/platform/tenants')}>
            {isMsp ? 'Manage Client Tenants' : 'Manage Tenants'}
          </button>
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

      {!isMsp && isBootstrap && (
        <div style={{ marginBottom: 12 }}>
          <InlineBanner
            tone="warning"
            title="License required before tenant rollout"
            message={
              safe.license_error
                ? `${safe.license_error}. Upload the signed customer or MSP license.key file to activate seats, tenant limits, and licensed features.`
                : 'Upload the signed customer or MSP license.key file to activate seats, tenant limits, and licensed features.'
            }
            actionLabel={uploading ? 'Uploading...' : 'Upload license.key'}
            onAction={uploading ? undefined : openLicensePicker}
          />
          <input
            ref={fileInputRef}
            type="file"
            accept=".key,application/json"
            style={{ display: 'none' }}
            onChange={uploadLicense}
          />
        </div>
      )}

      {!isMsp && uploadError && (
        <div style={{ marginBottom: 12 }}>
          <InlineBanner
            tone="danger"
            title="License upload failed"
            message={uploadError}
            onClose={() => setUploadError('')}
          />
        </div>
      )}

      {!isMsp && uploadMessage && (
        <div style={{ marginBottom: 12 }}>
          <InlineBanner
            tone="info"
            title="License installed"
            message={uploadMessage}
            onClose={() => setUploadMessage('')}
          />
        </div>
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
              {isMsp ? 'Active client workspaces' : safe.max_tenants ? `of ${safe.max_tenants} allowed` : 'Unlimited'}
            </div>
          </div>
          <div className="platform-card">
            <div className="platform-stat-label">{isMsp ? 'Client Machines' : 'Total Machines'}</div>
            <div className="platform-stat-value" style={{ color: 'var(--cyan)' }}>{safe.total_machines}</div>
            <div className="platform-stat-sub">{safe.active_seats} active seats in use</div>
          </div>
          <div className="platform-card">
            <div className="platform-stat-label">{isMsp ? 'Client Users' : 'Total Users'}</div>
            <div className="platform-stat-value" style={{ color: 'var(--purple)' }}>{safe.total_users}</div>
            <div className="platform-stat-sub">{isMsp ? 'Across your client tenants' : 'Across all tenants'}</div>
          </div>
          <div className="platform-card">
            <div className="platform-stat-label">{isMsp ? 'Partner Tier' : 'License Tier'}</div>
            <div className="platform-stat-value" style={{ color: 'var(--green)' }}>{String(safe.license_tier || 'none').toUpperCase()}</div>
            <div className="platform-stat-sub">{safe.license_customer || '--'}</div>
          </div>
        </div>

        <div className="platform-grid-2" style={{ marginBottom: 12 }}>
          <div className="platform-card">
            <div className="platform-stat-label">{isMsp ? 'Allocated Seats' : 'Seat Usage'}</div>
            <div className="platform-stat-sub">{safe.active_seats} / {safe.max_seats || '∞'}</div>
            <div className="platform-progress"><span style={{ width: `${Math.min(100, seatPct)}%` }} /></div>
          </div>
          {!isMsp && (
            <div className="platform-card">
              <div className="platform-stat-label">Tenant Slots</div>
              <div className="platform-stat-sub">{safe.active_tenants} / {safe.max_tenants || '∞'}</div>
              <div className="platform-progress"><span style={{ width: `${Math.min(100, tenantPct)}%` }} /></div>
            </div>
          )}
        </div>

        <div className="platform-card" style={{ marginBottom: 12 }}>
          <div className="platform-stat-label">License Details</div>
          <div className="platform-grid-4" style={{ marginTop: 10 }}>
            <div><strong>Tier</strong><div className="platform-page-sub">{String(safe.license_tier || 'none').toUpperCase()}</div></div>
            <div><strong>{isMsp ? 'Partner' : 'Customer'}</strong><div className="platform-page-sub">{safe.license_customer || '--'}</div></div>
            <div><strong>Max Seats</strong><div className="platform-page-sub">{safe.max_seats || 'Unlimited'}</div></div>
            <div><strong>{isMsp ? 'Scope' : 'Expires'}</strong><div className="platform-page-sub">{isMsp ? 'MSP Sub-Tenants' : fmtDate(safe.license_expires)}</div></div>
          </div>
        </div>

        <div className="platform-table-wrap">
          <div className="platform-table-header">
            <div>
              <div className="platform-table-title">{isMsp ? 'Client Tenant Directory' : 'Tenant Directory'}</div>
              <div className="platform-table-subtitle">
                {isMsp ? 'Only sub-tenants provisioned under your MSP account appear here.' : 'All tenants provisioned on this platform.'}
              </div>
            </div>
          </div>
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
