import { useCallback, useEffect, useMemo, useState } from 'react'
import { usePlatformApi, usePlatformAuth } from './PlatformLayout'
import { usePageContext } from '../hooks/usePageContext'
import { InlineBanner, PageStateView } from '../components/ui/PageState'

const initialCreate = {
  slug: '',
  name: '',
  customer_name: '',
  tier: 'starter',
  max_seats: '10',
  valid_days: '365',
  grace_days: '14',
}

const TIER_META = {
  starter: { label: 'Starter', tone: 'platform-chip platform-chip-slate' },
  professional: { label: 'Professional', tone: 'platform-chip platform-chip-brand' },
  enterprise: { label: 'Enterprise', tone: 'platform-chip platform-chip-green' },
  msp: { label: 'MSP', tone: 'platform-chip platform-chip-purple' },
}

const fmtDate = (ts) => {
  if (!ts) return '--'
  const d = new Date(ts)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function slugify(s) {
  return (s || '').toLowerCase().replace(/[^a-z0-9-_]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '')
}

function StatCard({ label, value, sub, tone = 'var(--brand)' }) {
  return (
    <div className="platform-card platform-stat-card">
      <div className="platform-stat-label">{label}</div>
      <div className="platform-stat-value" style={{ color: tone }}>{value}</div>
      <div className="platform-stat-sub">{sub}</div>
    </div>
  )
}

function TenantStatus({ status }) {
  return <span className={`badge ${status === 'active' ? 'badge-green' : 'badge-amber'}`}>{status || '--'}</span>
}

function TierBadge({ tier }) {
  const meta = TIER_META[tier] || { label: tier || 'Unknown', tone: 'platform-chip platform-chip-slate' }
  return <span className={meta.tone}>{meta.label}</span>
}

function TenantCreateModal({ open, onClose, onSubmit, saving, allowMspTier, isMsp }) {
  const [form, setForm] = useState(initialCreate)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setForm({ ...initialCreate, tier: 'starter' })
    setError('')
  }, [open])

  if (!open) return null

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }))

  const submit = async (e) => {
    e.preventDefault()
    const payload = {
      ...form,
      slug: slugify(form.slug || form.name),
      name: form.name.trim(),
      customer_name: (form.customer_name || form.name).trim(),
      max_seats: Number(form.max_seats || 0),
      valid_days: form.valid_days === '' ? null : Number(form.valid_days),
      grace_days: Number(form.grace_days || 0),
    }
    if (!payload.slug) return setError('Slug is required')
    if (!payload.name) return setError('Name is required')
    if (Number.isNaN(payload.max_seats) || payload.max_seats < 0) return setError('Max seats must be 0 or more')
    if (payload.valid_days !== null && (Number.isNaN(payload.valid_days) || payload.valid_days < 1)) {
      return setError('Valid days must be 1 or more, or blank')
    }
    if (Number.isNaN(payload.grace_days) || payload.grace_days < 0) return setError('Grace days must be 0 or more')
    setError('')
    await onSubmit(payload)
  }

  return (
    <div className="platform-modal-backdrop">
      <form className="platform-card platform-modal-card" style={{ width: 'min(560px, 94vw)' }} onSubmit={submit}>
        <div className="platform-card-head" style={{ marginBottom: 10 }}>
          <div>
            <div className="platform-page-title" style={{ fontSize: 20 }}>{isMsp ? 'Create Client Tenant' : 'Create Tenant'}</div>
            <p>{isMsp ? 'Set up a new client workspace under your MSP account.' : 'Set up a new workspace with a plan tier, slug, and seat limits.'}</p>
          </div>
        </div>
        {error && <InlineBanner tone="danger" title="Validation error" message={error} />}
        <div className="platform-grid-2" style={{ marginTop: 10 }}>
          <div className="form-group">
            <label className="form-label">Name</label>
            <input className="input-field" value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="Acme Corp" />
          </div>
          <div className="form-group">
            <label className="form-label">Slug</label>
            <input className="input-field" value={form.slug} onChange={(e) => set('slug', e.target.value)} placeholder="acme-corp" />
          </div>
          <div className="form-group">
            <label className="form-label">Customer Name</label>
            <input className="input-field" value={form.customer_name} onChange={(e) => set('customer_name', e.target.value)} placeholder="Acme Corp" />
          </div>
          <div className="form-group">
            <label className="form-label">Tier</label>
            <select className="input-field" value={form.tier} onChange={(e) => set('tier', e.target.value)}>
              <option value="starter">Starter</option>
              <option value="professional">Professional</option>
              <option value="enterprise">Enterprise</option>
              {allowMspTier && <option value="msp">MSP</option>}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Max Seats</label>
            <input className="input-field" type="number" min="0" value={form.max_seats} onChange={(e) => set('max_seats', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Valid Days</label>
            <input className="input-field" type="number" min="1" value={form.valid_days} onChange={(e) => set('valid_days', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Grace Days</label>
            <input className="input-field" type="number" min="0" value={form.grace_days} onChange={(e) => set('grace_days', e.target.value)} />
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>{saving ? 'Creating...' : isMsp ? 'Create Client Tenant' : 'Create Tenant'}</button>
        </div>
      </form>
    </div>
  )
}

function TenantDetailPanel({ tenant, onClose, onRefresh }) {
  const api = usePlatformApi()
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [copying, setCopying] = useState(false)
  const [copiedField, setCopiedField] = useState('')
  const [downloading, setDownloading] = useState(false)
  const [downloadPlatform, setDownloadPlatform] = useState('windows')
  const [name, setName] = useState('')
  const apiBase = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
  const fixedServerUrl = apiBase || window.location.origin
  const machineCount = detail?.machine_count ?? tenant?.machine_count ?? 0
  const userCount = detail?.user_count ?? tenant?.user_count ?? 0
  const tierValue = detail?.tier ?? tenant?.tier ?? '--'

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await api.get(`/api/tenants/${tenant.id}`)
      setDetail(d)
      setName(d.name || '')
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [api, tenant.id])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!copiedField) return undefined
    const id = window.setTimeout(() => setCopiedField(''), 1800)
    return () => window.clearTimeout(id)
  }, [copiedField])

  const copyToken = async () => {
    if (!detail?.enrollment_token) return
    setCopying(true)
    setError(null)
    try {
      await navigator.clipboard.writeText(detail.enrollment_token)
      setCopiedField('token')
    } catch (err) {
      setError(err)
    } finally {
      setCopying(false)
    }
  }

  const copyServerUrl = async () => {
    setCopying(true)
    setError(null)
    try {
      await navigator.clipboard.writeText(fixedServerUrl)
      setCopiedField('server')
    } catch (err) {
      setError(err)
    } finally {
      setCopying(false)
    }
  }

  const rotateToken = async () => {
    setSaving(true)
    setError(null)
    try {
      const r = await api.post(`/api/tenants/${tenant.id}/rotate-token`, {})
      setDetail((p) => ({ ...p, enrollment_token: r.enrollment_token }))
      setCopiedField('')
      onRefresh()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  const downloadAgentInstaller = async () => {
    setDownloading(true)
    setError(null)
    try {
      const token = localStorage.getItem('croppro_platform_token')
      const res = await fetch(`${apiBase}/api/agent-installers/${encodeURIComponent(downloadPlatform)}/latest`, {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })
      if (!res.ok) {
        let message = `Download failed (${res.status})`
        try {
          const data = await res.json()
          message = data?.detail || message
        } catch {
          // Ignore non-JSON download failures.
        }
        throw new Error(message)
      }
      const blob = await res.blob()
      const disposition = res.headers.get('Content-Disposition') || ''
      const match = disposition.match(/filename=\"?([^\"]+)\"?/)
      const fallbackExt = downloadPlatform === 'windows' ? 'exe' : 'tar.gz'
      const filename = match?.[1] || `cropsentinel-agent-${downloadPlatform}.${fallbackExt}`
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err)
    } finally {
      setDownloading(false)
    }
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const payload = { name }
      if (detail?.status) payload.status = detail.status
      await api.put(`/api/tenants/${tenant.id}`, payload)
      await load()
      onRefresh()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  const toggleStatus = async () => {
    if (!detail || detail.id === 1) return
    setSaving(true)
    setError(null)
    try {
      await api.put(`/api/tenants/${tenant.id}`, {
        name: detail.name,
        status: detail.status === 'active' ? 'suspended' : 'active',
      })
      await load()
      onRefresh()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  const deleteTenant = async () => {
    if (!detail || detail.id === 1) return
    if (!window.confirm(`Delete tenant "${detail.name}" permanently?`)) return
    setSaving(true)
    setError(null)
    try {
      await api.del(`/api/tenants/${tenant.id}`)
      onRefresh()
      onClose()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="platform-modal-backdrop">
      <div className="platform-card platform-modal-card" style={{ width: 'min(840px, 96vw)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
          <div>
            <div className="platform-page-title" style={{ fontSize: 20 }}>{tenant.name}</div>
            <div className="platform-page-sub">{tenant.slug}</div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>
        </div>

        {error && (
          <InlineBanner
            tone="danger"
            title="Tenant action failed"
            message={error.message}
            actionLabel="Retry"
            onAction={load}
            onClose={() => setError(null)}
          />
        )}

        <PageStateView state={loading ? 'loading' : 'ready'}>
          <div className="platform-grid-3" style={{ marginBottom: 12 }}>
            <StatCard label="Machines" value={machineCount} sub="Currently enrolled" tone="var(--brand)" />
            <StatCard label="Users" value={userCount} sub="Assigned to this tenant" tone="var(--green)" />
            <StatCard label="Tier" value={TIER_META[tierValue]?.label || tierValue} sub="Current subscription level" tone="var(--purple)" />
          </div>

          <div className="platform-grid-2" style={{ marginBottom: 10 }}>
            <div className="form-group platform-card-muted">
              <label className="form-label">Tenant Name</label>
              <input className="input-field" value={name} onChange={(e) => setName(e.target.value)} />
              <div className="platform-inline-help">Used across the platform and tenant-facing views.</div>
            </div>
            <div className="form-group platform-card-muted">
              <label className="form-label">Status</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                <TenantStatus status={detail?.status} />
                {detail?.id !== 1 && (
                  <button className="btn btn-outline btn-sm" onClick={toggleStatus} disabled={saving}>
                    {detail?.status === 'active' ? 'Suspend' : 'Activate'}
                  </button>
                )}
              </div>
              <div className="platform-inline-help">Suspended tenants keep data but cannot actively operate.</div>
            </div>
          </div>

          <div className="platform-card platform-detail-section" style={{ padding: 12, marginBottom: 10 }}>
            <div className="platform-card-head">
              <div>
                <h3>Enrollment Access</h3>
                <p>Use this token and server URL when enrolling a new machine.</p>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <TierBadge tier={tierValue} />
                <TenantStatus status={detail?.status} />
              </div>
            </div>
            <div className="platform-token-box mono">
              {detail?.enrollment_token || '--'}
            </div>
            <div className="platform-token-box mono" style={{ marginTop: 8 }}>
              {fixedServerUrl}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
              <button className="btn btn-ghost btn-sm" onClick={copyToken} disabled={copying || !detail?.enrollment_token}>
                {copying ? 'Copying...' : copiedField === 'token' ? 'Copied' : 'Copy Token'}
              </button>
              <button className="btn btn-ghost btn-sm" onClick={copyServerUrl} disabled={copying}>
                {copying ? 'Copying...' : copiedField === 'server' ? 'Copied' : 'Copy Server URL'}
              </button>
              <button className="btn btn-outline btn-sm" onClick={rotateToken} disabled={saving}>
                {saving ? 'Rotating...' : 'Rotate Token'}
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <select
                  className="input-field"
                  value={downloadPlatform}
                  onChange={(e) => setDownloadPlatform(e.target.value)}
                  disabled={downloading}
                  style={{ minWidth: 132, height: 36, paddingTop: 0, paddingBottom: 0 }}
                >
                  <option value="windows">Windows</option>
                  <option value="linux">Linux</option>
                </select>
                <button className="btn btn-primary btn-sm" onClick={downloadAgentInstaller} disabled={downloading}>
                  {downloading ? 'Downloading...' : 'Download Installer'}
                </button>
              </div>
            </div>
            <div className="platform-inline-help">Enter the server URL and enrollment token manually during install.</div>
          </div>

          <div className="platform-detail-actions">
            <button className="btn btn-danger btn-sm" onClick={deleteTenant} disabled={saving || detail?.id === 1}>
              Delete Tenant
            </button>
            <button className="btn btn-primary btn-sm" onClick={save} disabled={saving || !name.trim()}>
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </PageStateView>
      </div>
    </div>
  )
}

export default function TenantManagement() {
  const api = usePlatformApi()
  const { user } = usePlatformAuth()
  const { setPageContext, clearPageContext } = usePageContext()
  const [data, setData] = useState({ tenants: [], max_tenants: null })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [selected, setSelected] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get('/api/tenants')
      setData({
        tenants: Array.isArray(res?.tenants) ? res.tenants : [],
        max_tenants: res?.max_tenants ?? null,
      })
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    setPageContext(user?.is_msp ? 'MSP Scope' : 'Platform Scope', 'Tenants')
    return () => clearPageContext()
  }, [clearPageContext, setPageContext, user?.is_msp])

  const isMsp = Boolean(user?.is_msp)
  const tenants = useMemo(() => {
    const rows = data.tenants || []
    if (!isMsp) return rows
    return rows.filter((tenant) => Number(tenant.parent_tenant_id || 0) === Number(user?.tenant_id || 0))
  }, [data.tenants, isMsp, user?.tenant_id])
  const activeCount = tenants.filter((t) => t.status === 'active').length
  const suspendedCount = Math.max(0, tenants.length - activeCount)
  const totalMachines = tenants.reduce((sum, t) => sum + (Number(t.machine_count) || 0), 0)
  const totalUsers = tenants.reduce((sum, t) => sum + (Number(t.user_count) || 0), 0)
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return tenants
    return tenants.filter((t) =>
      String(t.id).includes(q) ||
      (t.name || '').toLowerCase().includes(q) ||
      (t.slug || '').toLowerCase().includes(q),
    )
  }, [tenants, search])

  const createTenant = async (payload) => {
    setCreating(true)
    try {
      await api.post('/api/tenants', payload)
      setCreateOpen(false)
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="fade-in">
      <div className="platform-card platform-tenant-hero">
        <div>
          <div className="platform-page-title">{isMsp ? 'Client Tenant Management' : 'Tenant Management'}</div>
          <div className="platform-page-sub">
            {isMsp
              ? 'Create, inspect, and manage the client tenants provisioned under your MSP account.'
              : 'Create, inspect, and manage all tenant workspaces with clearer enrollment and lifecycle controls.'}
          </div>
        </div>
        <div className="platform-tenant-hero-actions">
          <input
            className="input-field"
            placeholder="Search by tenant name, slug, or ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 280 }}
          />
          <button className="btn btn-primary btn-sm" onClick={() => setCreateOpen(true)}>
            {isMsp ? 'New Client Tenant' : 'New Tenant'}
          </button>
        </div>
      </div>

      {error && (
        <InlineBanner
          tone="danger"
          title="Tenant operation failed"
          message={error.message}
          actionLabel="Retry"
          onAction={load}
          onClose={() => setError(null)}
        />
      )}

      <PageStateView
        state={loading ? 'loading' : 'ready'}
        title="Could not load tenants"
        message={error?.message || ''}
        onRetry={load}
      >
        <div className="platform-grid-4" style={{ marginBottom: 12 }}>
          <StatCard label="Total Tenants" value={tenants.length} sub="Visible workspaces" tone="var(--brand)" />
          <StatCard label="Active Tenants" value={activeCount} sub="Ready for operations" tone="var(--green)" />
          <StatCard label="Suspended" value={suspendedCount} sub="Temporarily paused" tone="var(--amber)" />
          <StatCard label="Max Tenant Slots" value={isMsp ? '--' : (data.max_tenants ?? '∞')} sub={isMsp ? 'Managed by platform contract' : 'Platform capacity'} tone="var(--purple)" />
        </div>

        <div className="platform-grid-2 platform-grid-2-tenant" style={{ marginBottom: 12 }}>
          <div className="platform-card platform-card-muted">
            <div className="platform-stat-label">Enrolled Machines</div>
            <div className="platform-stat-value" style={{ color: 'var(--text-1)', fontSize: 24 }}>{totalMachines}</div>
            <div className="platform-stat-sub">{isMsp ? 'Machines currently attached across your client tenants.' : 'Machines currently attached across all tenants.'}</div>
          </div>
          <div className="platform-card platform-card-muted">
            <div className="platform-stat-label">Managed Users</div>
            <div className="platform-stat-value" style={{ color: 'var(--text-1)', fontSize: 24 }}>{totalUsers}</div>
            <div className="platform-stat-sub">{isMsp ? 'User accounts visible across your client tenants.' : 'User accounts visible from the platform control layer.'}</div>
          </div>
        </div>

        <div className="platform-table-wrap platform-tenant-table-wrap">
          <div className="platform-table-header">
            <div>
              <div className="platform-table-title">{isMsp ? 'Client Tenant Directory' : 'Tenant Directory'}</div>
              <div className="platform-table-subtitle">
                {isMsp ? 'Select a client tenant to manage status, enrollment, and agent deployment.' : 'Select a tenant to manage status, enrollment, and agent deployment.'}
              </div>
            </div>
            <div className="platform-table-meta">{filtered.length} shown</div>
          </div>
          <table className="platform-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Slug</th>
                <th>Tier</th>
                <th>Status</th>
                <th>Machines</th>
                <th>Users</th>
                <th>Created</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={t.id} onClick={() => setSelected(t)} style={{ cursor: 'pointer' }}>
                  <td className="mono" style={{ color: 'var(--text-3)' }}>#{t.id}</td>
                  <td>
                    <div style={{ fontWeight: 700 }}>{t.name}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>{t.customer_name || 'Customer workspace'}</div>
                  </td>
                  <td className="mono" style={{ color: 'var(--text-3)' }}>{t.slug}</td>
                  <td><TierBadge tier={t.tier} /></td>
                  <td><TenantStatus status={t.status} /></td>
                  <td>{t.machine_count || 0}</td>
                  <td>{t.user_count || 0}</td>
                  <td style={{ color: 'var(--text-3)' }}>{fmtDate(t.created_at)}</td>
                  <td style={{ textAlign: 'right', color: 'var(--text-3)', fontWeight: 600 }}>Open</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-title">No tenants match your search</div>
            </div>
          )}
        </div>
      </PageStateView>

      <TenantCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSubmit={createTenant}
        saving={creating}
        allowMspTier={!isMsp}
        isMsp={isMsp}
      />
      {selected && <TenantDetailPanel tenant={selected} onClose={() => setSelected(null)} onRefresh={load} />}
    </div>
  )
}
