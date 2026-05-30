import { useCallback, useEffect, useMemo, useState } from 'react'
import { usePlatformApi } from './PlatformLayout'
import { usePageContext } from '../hooks/usePageContext'
import { InlineBanner, PageStateView } from '../components/ui/PageState'

const ROLES = [
  { value: 'admin', label: 'Admin' },
  { value: 'manager', label: 'Manager' },
  { value: 'viewer', label: 'Viewer' },
  { value: 'remote_operator', label: 'Remote Operator' },
]

const newUserInitial = {
  tenant_id: '',
  username: '',
  password: '',
  display_name: '',
  role: 'viewer',
}

const fmtDate = (ts) => {
  if (!ts) return '--'
  const d = new Date(ts)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function CreatePlatformUserModal({ open, tenants, onClose, onSubmit, saving }) {
  const [form, setForm] = useState(newUserInitial)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setForm({ ...newUserInitial, tenant_id: String(tenants?.[0]?.id || '') })
    setError('')
  }, [open, tenants])

  if (!open) return null

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }))

  const submit = async (e) => {
    e.preventDefault()
    if (!form.tenant_id || !form.username.trim() || !form.password.trim()) {
      setError('Tenant, username, and password are required')
      return
    }
    setError('')
    await onSubmit({
      tenant_id: Number(form.tenant_id),
      username: form.username.trim(),
      password: form.password,
      display_name: (form.display_name || form.username).trim(),
      role: form.role,
      assigned_machines: [],
    })
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.28)', display: 'grid', placeItems: 'center', zIndex: 1200 }}>
      <form className="platform-card" style={{ width: 'min(560px, 94vw)' }} onSubmit={submit}>
        <div className="platform-page-title" style={{ fontSize: 20, marginBottom: 10 }}>Create Platform User</div>
        {error && <InlineBanner tone="danger" title="Validation error" message={error} />}

        <div className="platform-grid-2" style={{ marginTop: 10 }}>
          <div className="form-group">
            <label className="form-label">Tenant</label>
            <select className="input-field" value={form.tenant_id} onChange={(e) => set('tenant_id', e.target.value)}>
              <option value="">Select tenant</option>
              {tenants.map((t) => (
                <option key={t.id} value={t.id}>{t.name} (#{t.id})</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Role</label>
            <select className="input-field" value={form.role} onChange={(e) => set('role', e.target.value)}>
              {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Username</label>
            <input className="input-field" value={form.username} onChange={(e) => set('username', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Display Name</label>
            <input className="input-field" value={form.display_name} onChange={(e) => set('display_name', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Password</label>
            <input type="password" className="input-field" value={form.password} onChange={(e) => set('password', e.target.value)} />
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>{saving ? 'Creating...' : 'Create User'}</button>
        </div>
      </form>
    </div>
  )
}

export default function PlatformUsers() {
  const api = usePlatformApi()
  const { setPageContext, clearPageContext } = usePageContext()
  const [users, setUsers] = useState([])
  const [tenants, setTenants] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [tenantFilter, setTenantFilter] = useState('all')
  const [createOpen, setCreateOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [ul, tl] = await Promise.all([
        api.get('/api/platform/users'),
        api.get('/api/tenants'),
      ])
      setUsers(Array.isArray(ul) ? ul : [])
      setTenants(Array.isArray(tl?.tenants) ? tl.tenants : [])
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    setPageContext('Platform Scope', 'Users')
    return () => clearPageContext()
  }, [setPageContext, clearPageContext])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return users.filter((u) => {
      if (tenantFilter !== 'all' && String(u.tenant_id) !== String(tenantFilter)) return false
      if (!q) return true
      return (
        (u.username || '').toLowerCase().includes(q) ||
        (u.display_name || '').toLowerCase().includes(q) ||
        (u.tenant_name || '').toLowerCase().includes(q)
      )
    })
  }, [users, search, tenantFilter])

  const createUser = async (payload) => {
    setSaving(true)
    try {
      await api.post('/api/platform/users', payload)
      setCreateOpen(false)
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  const deleteUser = async (user) => {
    if (!window.confirm(`Delete user "${user.username}"?`)) return
    setSaving(true)
    try {
      await api.del(`/api/platform/users/${user.id}`)
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fade-in">
      <div className="platform-page-head">
        <div>
          <div className="platform-page-title">Platform Users</div>
          <div className="platform-page-sub">Manage users across all tenants</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            className="input-field"
            placeholder="Search users..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 220 }}
          />
          <select className="input-field" value={tenantFilter} onChange={(e) => setTenantFilter(e.target.value)} style={{ width: 180 }}>
            <option value="all">All tenants</option>
            {tenants.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <button className="btn btn-primary btn-sm" onClick={() => setCreateOpen(true)}>Create User</button>
        </div>
      </div>

      {error && (
        <InlineBanner
          tone="danger"
          title="User operation failed"
          message={error.message}
          actionLabel="Retry"
          onAction={load}
          onClose={() => setError(null)}
        />
      )}

      <PageStateView state={loading ? 'loading' : 'ready'} title="Failed to load users" message={error?.message || ''} onRetry={load}>
        <div className="platform-table-wrap">
          <table className="platform-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Display Name</th>
                <th>Role</th>
                <th>Tenant</th>
                <th>Status</th>
                <th>Created</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((u) => (
                <tr key={u.id}>
                  <td style={{ fontWeight: 700 }}>{u.username}</td>
                  <td>{u.display_name || '--'}</td>
                  <td><span className="badge badge-blue">{u.role}</span></td>
                  <td>{u.tenant_name || `Tenant #${u.tenant_id}`}</td>
                  <td>
                    <span className={`badge ${u.active ? 'badge-green' : 'badge-gray'}`}>
                      {u.active ? 'Active' : 'Disabled'}
                    </span>
                  </td>
                  <td style={{ color: 'var(--text-3)' }}>{fmtDate(u.created_at)}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button className="btn btn-danger btn-sm" onClick={() => deleteUser(u)} disabled={saving}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-title">No users match current filters</div>
            </div>
          )}
        </div>
      </PageStateView>

      <CreatePlatformUserModal
        open={createOpen}
        tenants={tenants}
        onClose={() => setCreateOpen(false)}
        onSubmit={createUser}
        saving={saving}
      />
    </div>
  )
}
