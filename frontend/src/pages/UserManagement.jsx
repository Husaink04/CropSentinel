/**
 * CropSentinel — User Management  v1.0
 * =================================
 * Full RBAC user CRUD with role assignment, machine-level access,
 * animated cards, search/filter, and polished modal forms.
 */

import { useState, useEffect, useCallback } from 'react'
import { useApi, useAuth } from '../hooks/useAuth'
import { usePageContext } from '../hooks/usePageContext'
import { UsersIcon } from '../components/ui/OverviewIcons'

// ── Constants ─────────────────────────────────────────────────────────────────

const ROLES = [
  { value: 'admin',           label: 'Admin',           icon: '⬢', color: 'var(--brand)',  bg: 'var(--brand-subtle)',  desc: 'Full system access' },
  { value: 'manager',         label: 'Manager',         icon: '◈', color: '#8B5CF6',       bg: 'var(--purple-subtle)', desc: 'Monitor & manage alerts' },
  { value: 'viewer',          label: 'Viewer',          icon: '◎', color: 'var(--green)',   bg: 'var(--success-subtle)',desc: 'Read-only access' },
  { value: 'remote_operator', label: 'Remote Operator', icon: '⊞', color: '#F5A623',       bg: 'var(--warning-subtle)',desc: 'View & remote control' },
]

const ROLE_MAP = Object.fromEntries(ROLES.map(r => [r.value, r]))

const PERMS_BY_ROLE = {
  admin:           [
    { perm: 'Full access', desc: 'All permissions including user & settings management' },
  ],
  manager:         [
    { perm: 'machines.view',      desc: 'View all machines'          },
    { perm: 'activity.view',      desc: 'View activity logs'         },
    { perm: 'screenshots.view',   desc: 'View screenshots'           },
    { perm: 'analytics.view',     desc: 'View analytics dashboards'  },
    { perm: 'productivity.view',  desc: 'View productivity scores'   },
    { perm: 'alerts.view/manage', desc: 'View & manage alert rules'  },
    { perm: 'reports.generate',   desc: 'Generate PDF reports'       },
  ],
  viewer:          [
    { perm: 'machines.view',      desc: 'View all machines'          },
    { perm: 'activity.view',      desc: 'View activity logs'         },
    { perm: 'screenshots.view',   desc: 'View screenshots'           },
    { perm: 'analytics.view',     desc: 'View analytics dashboards'  },
    { perm: 'productivity.view',  desc: 'View productivity scores'   },
  ],
  remote_operator: [
    { perm: 'machines.view',      desc: 'View all machines'          },
    { perm: 'activity.view',      desc: 'View activity logs'         },
    { perm: 'screenshots.view',   desc: 'View screenshots'           },
    { perm: 'analytics.view',     desc: 'View analytics dashboards'  },
    { perm: 'remote.access',      desc: 'Remote desktop access'      },
  ],
}

const fmtDate = ts => {
  if (!ts) return '--'
  const d = new Date(ts)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// ── Reusable sub-components ───────────────────────────────────────────────────

function Toggle({ on, onChange }) {
  return (
    <div onClick={() => onChange(!on)} style={{
      position: 'relative', width: 38, height: 20, cursor: 'pointer', flexShrink: 0,
    }}>
      <div style={{
        width: 38, height: 20, borderRadius: 10,
        background: on ? 'var(--brand)' : 'var(--border-1)',
        transition: 'background .2s',
      }} />
      <div style={{
        position: 'absolute', top: 2, left: on ? 20 : 2,
        width: 16, height: 16, borderRadius: '50%', background: '#fff',
        transition: 'left .18s', boxShadow: '0 1px 4px rgba(0,0,0,.2)',
      }} />
    </div>
  )
}

function PwdStrength({ pwd }) {
  if (!pwd) return null
  const checks = [
    { ok: pwd.length >= 8,          label: '8+ chars' },
    { ok: /[A-Z]/.test(pwd),        label: 'Upper'    },
    { ok: /[a-z]/.test(pwd),        label: 'Lower'    },
    { ok: /\d/.test(pwd),           label: 'Number'   },
    { ok: /[^A-Za-z0-9]/.test(pwd), label: 'Symbol'   },
  ]
  const score = checks.filter(c => c.ok).length
  const colors = ['var(--red)', 'var(--red)', '#F5A623', '#F5A623', 'var(--green)']
  const labels = ['Very weak', 'Weak', 'Fair', 'Good', 'Strong']
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ display: 'flex', gap: 3, marginBottom: 4 }}>
        {[0,1,2,3,4].map(i => (
          <div key={i} style={{
            flex: 1, height: 3, borderRadius: 2,
            background: i < score ? colors[score - 1] : 'var(--border-1)',
            transition: 'background .2s',
          }} />
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10 }}>
        <span style={{ color: colors[score - 1] || 'var(--text-3)', fontWeight: 600 }}>
          {labels[score - 1] || ''}
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          {checks.map((c, i) => (
            <span key={i} style={{ color: c.ok ? 'var(--green)' : 'var(--text-3)' }}>{c.label}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function UserManagement() {
  const { get, post, put, del } = useApi()
  const { user: currentUser }   = useAuth()
  const { setPageContext, clearPageContext } = usePageContext()

  const [users, setUsers]       = useState([])
  const [machines, setMachines] = useState([])
  const [loading, setLoading]   = useState(true)
  const [search, setSearch]     = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [toast, setToast]       = useState(null)

  // Modal state
  const [modal, setModal]       = useState(null) // null | 'create' | 'edit'
  const [editUser, setEditUser] = useState(null)
  const [form, setForm]         = useState({ username: '', password: '', display_name: '', role: 'viewer', assigned_machines: [] })
  const [error, setError]       = useState('')
  const [saving, setSaving]     = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [showPwd, setShowPwd]   = useState(false)

  const showToast = (msg, type = 'green') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([get('/api/users'), get('/api/machines')])
      .then(([u, m]) => { setUsers(u); setMachines(m) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [get])

  useEffect(load, [])
  useEffect(() => {
    setPageContext('Tenant Scope', 'Users')
    return () => clearPageContext()
  }, [setPageContext, clearPageContext])

  // ── Filtered users ──────────────────────────────────────────────────────────
  const filtered = users.filter(u => {
    if (roleFilter && u.role !== roleFilter) return false
    if (search) {
      const s = search.toLowerCase()
      return (u.username?.toLowerCase().includes(s) ||
              u.display_name?.toLowerCase().includes(s) ||
              u.role?.toLowerCase().includes(s))
    }
    return true
  })

  // ── Modal helpers ───────────────────────────────────────────────────────────
  const openCreate = () => {
    setForm({ username: '', password: '', display_name: '', role: 'viewer', assigned_machines: [] })
    setError(''); setShowPwd(false); setModal('create')
  }

  const openEdit = (u) => {
    let assigned = u.assigned_machines || []
    if (typeof assigned === 'string') {
      try { assigned = JSON.parse(assigned) } catch { assigned = [] }
    }
    setEditUser(u)
    setForm({ username: u.username, password: '', display_name: u.display_name || '', role: u.role, assigned_machines: assigned })
    setError(''); setShowPwd(false); setModal('edit')
  }

  const handleSave = async () => {
    setError(''); setSaving(true)
    try {
      if (modal === 'create') {
        if (!form.username.trim()) { setError('Username is required'); setSaving(false); return }
        if (!form.password)        { setError('Password is required'); setSaving(false); return }
        if (form.password.length < 6) { setError('Password must be at least 6 characters'); setSaving(false); return }
        await post('/api/users', form)
        showToast(`User "${form.username}" created`)
      } else {
        const data = { display_name: form.display_name, role: form.role, assigned_machines: form.assigned_machines }
        if (form.password) {
          if (form.password.length < 6) { setError('Password must be at least 6 characters'); setSaving(false); return }
          data.password = form.password
        }
        await put(`/api/users/${editUser.id}`, data)
        showToast(`User "${editUser.username}" updated`)
      }
      setModal(null)
      load()
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  const handleDelete = async (u) => {
    try {
      await del(`/api/users/${u.id}`)
      setConfirmDelete(null)
      showToast(`User "${u.username}" deleted`, 'red')
      load()
    } catch (e) { showToast(e.message, 'red') }
  }

  const toggleActive = async (u) => {
    try {
      await put(`/api/users/${u.id}`, { active: !u.active })
      showToast(`User "${u.username}" ${u.active ? 'disabled' : 'enabled'}`, u.active ? 'amber' : 'green')
      load()
    } catch {}
  }

  const toggleMachine = (mid) => {
    setForm(f => {
      const set = new Set(f.assigned_machines)
      set.has(mid) ? set.delete(mid) : set.add(mid)
      return { ...f, assigned_machines: [...set] }
    })
  }

  const selectedRole = ROLE_MAP[form.role] || ROLE_MAP.viewer

  // ── Render ──────────────────────────────────────────────────────────────────

  if (loading) return (
    <div className="loading-center">
      <div className="spinner" style={{ width: 32, height: 32, borderWidth: 3 }} />
      <span>Loading users...</span>
    </div>
  )

  return (
    <div className="fade-in control-shell">

      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', top: 20, right: 20, zIndex: 2000,
          animation: 'fadeUp .25s ease-out',
        }}>
          <div className={`alert-toast alert-${toast.type}`}>{toast.msg}</div>
        </div>
      )}

      {/* ── Page Header ────────────────────────────────────────────────── */}
      <div className="page-header machine-calm-header analytics-hero control-hero">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <UsersIcon size={24} />
          </div>
          <div>
            <div className="page-title">User Management</div>
            <div className="page-subtitle">
              {users.length} user{users.length !== 1 ? 's' : ''} registered and {users.filter(u => u.active !== false).length} active.
            </div>
          </div>
        </div>
        <div className="control-actions">
          <button className="btn btn-primary" onClick={openCreate}>
            <span style={{ fontSize: 15, marginRight: 6 }}>+</span>
            New User
          </button>
        </div>
      </div>

      {/* ── Role Stat Cards ────────────────────────────────────────────── */}
      <div className="grid-4" style={{ marginBottom: 22 }}>
        {ROLES.map(r => {
          const count = users.filter(u => u.role === r.value).length
          const active = users.filter(u => u.role === r.value && u.active !== false).length
          const isFiltered = roleFilter === r.value
          return (
            <div key={r.value} className="stat-card machine-calm-card machine-calm-stat control-stat stagger"
              onClick={() => setRoleFilter(isFiltered ? '' : r.value)}
              style={{
                cursor: 'pointer', transition: 'all .2s',
                outline: isFiltered ? `2px solid ${r.color}` : '2px solid transparent',
                outlineOffset: -2,
              }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div className="stat-label">{r.label}s</div>
                <div style={{
                  width: 36, height: 36, borderRadius: 10, background: r.bg,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 18, color: r.color,
                }}>{r.icon}</div>
              </div>
              <div className="stat-value" style={{ color: r.color }}>{count}</div>
              <div className="stat-sub">{active} active &middot; {r.desc}</div>
            </div>
          )
        })}
      </div>

      {/* ── Filter Bar ─────────────────────────────────────────────────── */}
      <div className="filter-bar analytics-filter-panel machine-calm-card control-filter" style={{ marginBottom: 16 }}>
        <div style={{ position: 'relative', flex: 1, maxWidth: 320 }}>
          <span style={{
            position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)',
            fontSize: 13, color: 'var(--text-3)', pointerEvents: 'none',
          }}>&#x2315;</span>
          <input className="input-field machine-calm-search control-field" placeholder="Search users..."
            value={search} onChange={e => setSearch(e.target.value)}
            style={{ paddingLeft: 34, width: '100%' }} />
        </div>

        <div className="tab-group analytics-tabs" style={{ gap: 2 }}>
          <button className={`tab-btn${!roleFilter ? ' active' : ''}`}
            onClick={() => setRoleFilter('')}>All</button>
          {ROLES.map(r => (
            <button key={r.value}
              className={`tab-btn${roleFilter === r.value ? ' active' : ''}`}
              onClick={() => setRoleFilter(roleFilter === r.value ? '' : r.value)}>
              <span style={{ marginRight: 4 }}>{r.icon}</span>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Users Table ────────────────────────────────────────────────── */}
      {filtered.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">&#x2315;</div>
          <div className="empty-state-title">
            {search || roleFilter ? 'No users match your filters' : 'No users yet'}
          </div>
          <div className="empty-state-sub">
            {search || roleFilter
              ? 'Try adjusting your search or filter'
              : 'Create your first user to get started'}
          </div>
        </div>
      ) : (
        <div className="card machine-calm-card control-card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Status</th>
                <th>Machines</th>
                <th>Created</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(u => {
                const r = ROLE_MAP[u.role] || ROLE_MAP.viewer
                let assigned = u.assigned_machines || []
                if (typeof assigned === 'string') {
                  try { assigned = JSON.parse(assigned) } catch { assigned = [] }
                }
                const isSelf = u.username === currentUser?.username
                return (
                  <tr key={u.id}>
                    {/* User info */}
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{
                          width: 34, height: 34, borderRadius: 10, flexShrink: 0,
                          background: `linear-gradient(135deg, ${r.color}20, ${r.color}08)`,
                          border: `1px solid ${r.color}30`,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 13, fontWeight: 800, color: r.color,
                          textTransform: 'uppercase',
                        }}>
                          {(u.display_name || u.username || '?').slice(0, 2)}
                        </div>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-1)' }}>
                            {u.display_name || u.username}
                            {isSelf && (
                              <span style={{
                                fontSize: 9, fontWeight: 700, marginLeft: 6,
                                padding: '1px 6px', borderRadius: 100,
                                background: 'var(--brand-subtle)', color: 'var(--brand)',
                              }}>YOU</span>
                            )}
                          </div>
                          <div className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>
                            @{u.username}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Role badge */}
                    <td>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 100,
                        background: r.bg, color: r.color,
                      }}>
                        <span style={{ fontSize: 10 }}>{r.icon}</span>
                        {r.label}
                      </span>
                    </td>

                    {/* Status */}
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Toggle on={u.active !== false} onChange={() => !isSelf && toggleActive(u)} />
                        <span style={{
                          fontSize: 11, fontWeight: 600,
                          color: u.active !== false ? 'var(--green)' : 'var(--text-3)',
                        }}>
                          {u.active !== false ? 'Active' : 'Disabled'}
                        </span>
                      </div>
                    </td>

                    {/* Machines */}
                    <td>
                      {assigned.length === 0 ? (
                        <span className="badge badge-blue" style={{ fontSize: 10 }}>All machines</span>
                      ) : (
                        <span className="badge badge-gray" style={{ fontSize: 10 }}>
                          {assigned.length} machine{assigned.length !== 1 ? 's' : ''}
                        </span>
                      )}
                    </td>

                    {/* Created */}
                    <td style={{ fontSize: 12, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>
                      {fmtDate(u.created_at)}
                      {u.created_by && u.created_by !== 'system' && (
                        <div style={{ fontSize: 10, color: 'var(--text-3)', opacity: .7 }}>
                          by {u.created_by}
                        </div>
                      )}
                    </td>

                    {/* Actions */}
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => openEdit(u)}
                          style={{ fontSize: 11 }}>
                          Edit
                        </button>
                        {!isSelf && (
                          confirmDelete === u.id ? (
                            <div style={{ display: 'flex', gap: 4 }}>
                              <button className="btn btn-danger btn-sm" style={{ fontSize: 11 }}
                                onClick={() => handleDelete(u)}>
                                Confirm
                              </button>
                              <button className="btn btn-ghost btn-sm" style={{ fontSize: 11 }}
                                onClick={() => setConfirmDelete(null)}>
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button className="btn btn-ghost btn-sm"
                              onClick={() => setConfirmDelete(u.id)}
                              style={{ fontSize: 11, color: 'var(--red)' }}>
                              Delete
                            </button>
                          )
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Create / Edit Modal ────────────────────────────────────────── */}
      {modal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', backdropFilter: 'blur(4px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          animation: 'fadeIn .15s ease-out',
        }} onClick={() => setModal(null)}>
          <div className="card machine-calm-card control-card" style={{
            width: '100%', maxWidth: 520, padding: 0, maxHeight: '85vh', overflow: 'hidden',
            animation: 'fadeUp .2s ease-out',
            display: 'flex', flexDirection: 'column',
          }} onClick={e => e.stopPropagation()}>

            {/* Modal header */}
            <div style={{
              padding: '20px 24px 16px', borderBottom: '1px solid var(--border)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-1)' }}>
                  {modal === 'create' ? 'Create New User' : 'Edit User'}
                </div>
                {modal === 'edit' && (
                  <div className="mono" style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                    @{editUser?.username}
                  </div>
                )}
              </div>
              <button className="btn btn-ghost btn-icon" onClick={() => setModal(null)}
                style={{ fontSize: 18, width: 32, height: 32 }}>
                &times;
              </button>
            </div>

            {/* Modal body */}
            <div style={{ padding: '20px 24px', overflow: 'auto', flex: 1 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

                {/* Username (create only) */}
                {modal === 'create' && (
                  <div className="form-group">
                    <label className="form-label">Username</label>
                    <input className="input-field" value={form.username}
                      onChange={e => setForm(f => ({ ...f, username: e.target.value.toLowerCase().replace(/[^a-z0-9._-]/g, '') }))}
                      placeholder="john.doe" autoFocus />
                    <span className="form-hint">Lowercase, letters, numbers, dots, dashes only</span>
                  </div>
                )}

                {/* Display name */}
                <div className="form-group">
                  <label className="form-label">Display Name</label>
                  <input className="input-field" value={form.display_name}
                    onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))}
                    placeholder="John Doe" autoFocus={modal === 'edit'} />
                </div>

                {/* Password */}
                <div className="form-group">
                  <label className="form-label">
                    {modal === 'create' ? 'Password' : 'New Password'}
                    {modal === 'edit' && (
                      <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 400, marginLeft: 6 }}>
                        Leave blank to keep current
                      </span>
                    )}
                  </label>
                  <div style={{ position: 'relative' }}>
                    <input className="input-field"
                      type={showPwd ? 'text' : 'password'}
                      value={form.password}
                      onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                      placeholder={modal === 'create' ? 'Min 6 characters' : 'Unchanged'}
                      style={{ paddingRight: 40 }} />
                    <button type="button"
                      onClick={() => setShowPwd(p => !p)}
                      style={{
                        position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                        background: 'none', border: 'none', cursor: 'pointer',
                        fontSize: 13, color: 'var(--text-3)', padding: '2px 4px',
                      }}>
                      {showPwd ? '◉' : '○'}
                    </button>
                  </div>
                  <PwdStrength pwd={form.password} />
                </div>

                {/* Role selector */}
                <div className="form-group">
                  <label className="form-label">Role</label>
                  <div style={{
                    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
                  }}>
                    {ROLES.map(r => {
                      const sel = form.role === r.value
                      return (
                        <div key={r.value}
                          onClick={() => setForm(f => ({ ...f, role: r.value }))}
                          style={{
                            padding: '10px 14px', borderRadius: 'var(--r-md)',
                            border: `1.5px solid ${sel ? r.color : 'var(--border)'}`,
                            background: sel ? r.bg : 'transparent',
                            cursor: 'pointer', transition: 'all .15s',
                          }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{
                              fontSize: 16, color: sel ? r.color : 'var(--text-3)',
                              transition: 'color .15s',
                            }}>{r.icon}</span>
                            <div>
                              <div style={{
                                fontSize: 12.5, fontWeight: 700,
                                color: sel ? r.color : 'var(--text-2)',
                                transition: 'color .15s',
                              }}>{r.label}</div>
                              <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 1 }}>
                                {r.desc}
                              </div>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Permissions preview */}
                <div style={{
                  background: 'var(--bg-3)', borderRadius: 'var(--r-md)',
                  padding: '12px 16px', border: '1px solid var(--border)',
                }}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8,
                  }}>
                    <span style={{ fontSize: 14, color: selectedRole.color }}>{selectedRole.icon}</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-2)' }}>
                      {selectedRole.label} Permissions
                    </span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {(PERMS_BY_ROLE[form.role] || []).map((p, i) => (
                      <div key={i} style={{
                        display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5,
                      }}>
                        <span style={{ color: 'var(--green)', fontSize: 10, flexShrink: 0 }}>&#10003;</span>
                        <span className="mono" style={{ color: selectedRole.color, fontWeight: 600, minWidth: 110 }}>
                          {p.perm}
                        </span>
                        <span style={{ color: 'var(--text-3)' }}>{p.desc}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Machine assignment */}
                {form.role !== 'admin' && (
                  <div className="form-group">
                    <label className="form-label">
                      Machine Access
                      <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 400, marginLeft: 6 }}>
                        None selected = all machines
                      </span>
                    </label>
                    <div style={{
                      maxHeight: 160, overflow: 'auto',
                      background: 'var(--bg-3)', borderRadius: 'var(--r-md)',
                      border: '1px solid var(--border)', padding: 6,
                    }}>
                      {machines.length === 0 ? (
                        <div style={{ padding: '12px 10px', textAlign: 'center', fontSize: 12, color: 'var(--text-3)' }}>
                          No machines registered yet
                        </div>
                      ) : machines.map(m => {
                        const checked = form.assigned_machines.includes(m.machine_id)
                        return (
                          <label key={m.machine_id} style={{
                            display: 'flex', alignItems: 'center', gap: 10,
                            padding: '6px 10px', borderRadius: 'var(--r-sm)',
                            cursor: 'pointer', transition: 'background .1s',
                            background: checked ? `${selectedRole.color}10` : 'transparent',
                          }}>
                            <input type="checkbox" checked={checked}
                              onChange={() => toggleMachine(m.machine_id)}
                              style={{ accentColor: selectedRole.color }} />
                            <div style={{ flex: 1 }}>
                              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-1)' }}>
                                {m.hostname || 'Unknown'}
                              </span>
                              <span className="mono" style={{ fontSize: 10, color: 'var(--text-3)', marginLeft: 8 }}>
                                {m.machine_id.slice(0, 12)}...
                              </span>
                            </div>
                            {m.online && <span className="dot-online" />}
                          </label>
                        )
                      })}
                    </div>
                    {form.assigned_machines.length > 0 && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                        <span className="badge badge-blue" style={{ fontSize: 10 }}>
                          {form.assigned_machines.length} selected
                        </span>
                        <button className="btn btn-ghost btn-sm" style={{ fontSize: 10, padding: '2px 8px' }}
                          onClick={() => setForm(f => ({ ...f, assigned_machines: [] }))}>
                          Clear all
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {/* Error */}
                {error && (
                  <div style={{
                    background: 'var(--danger-subtle)', border: '1px solid rgba(239,68,68,.25)',
                    color: 'var(--red)', padding: '10px 14px', borderRadius: 'var(--r-md)',
                    fontSize: 12.5, fontWeight: 500,
                  }}>
                    {error}
                  </div>
                )}
              </div>
            </div>

            {/* Modal footer */}
            <div style={{
              padding: '14px 24px 18px', borderTop: '1px solid var(--border)',
              display: 'flex', justifyContent: 'flex-end', gap: 10,
            }}>
              <button className="btn btn-ghost" onClick={() => setModal(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? (
                  <><span className="spinner" style={{ width: 13, height: 13 }} /> Saving...</>
                ) : modal === 'create' ? 'Create User' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
