import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useAuth'
import { useNotifications } from '../hooks/useNotifications'
import { usePageContext } from '../hooks/usePageContext'
import { InlineBanner, PageStateView } from '../components/ui/PageState'
import {
  MachinesIcon,
  OnlineIcon,
  AverageHoursIcon,
  AlertsIcon,
} from '../components/ui/OverviewIcons'

const DEFAULT_LIMIT = 25

function TeamMetricCard({ icon: Icon, label, value, subtext, tone }) {
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

export default function Teams() {
  const { get, post, put, del } = useApi()
  const { push } = useNotifications()
  const { setPageContext, clearPageContext } = usePageContext()
  const navigate = useNavigate()

  const [teams, setTeams] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [saving, setSaving] = useState(false)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const [editing, setEditing] = useState(null)
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')

  const loadTeams = useCallback(() => {
    setLoading(true)
    setLoadError(null)
    const params = new URLSearchParams({
      limit: String(DEFAULT_LIMIT),
      offset: String(offset),
    })
    if (search.trim()) params.set('search', search.trim())

    get(`/api/teams?${params.toString()}`)
      .then((rows) => {
        setTeams(Array.isArray(rows) ? rows : [])
        setTotal(rows?._meta?.total ?? 0)
      })
      .catch((err) => setLoadError(err))
      .finally(() => setLoading(false))
  }, [get, offset, search])

  useEffect(() => { loadTeams() }, [loadTeams])
  useEffect(() => { setOffset(0) }, [search])
  useEffect(() => {
    setPageContext('Tenant Scope', 'Teams')
    return () => clearPageContext()
  }, [setPageContext, clearPageContext])

  const createTeam = async (e) => {
    e.preventDefault()
    if (!name.trim()) {
      push({ type: 'error', title: 'Team name is required' })
      return
    }
    try {
      setSaving(true)
      await post('/api/teams', { name: name.trim(), description: description.trim() })
      setName('')
      setDescription('')
      push({ type: 'success', title: 'Team created' })
      loadTeams()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setSaving(false)
    }
  }

  const startEdit = (team) => {
    setEditing(team.id)
    setEditName(team.name || '')
    setEditDescription(team.description || '')
  }

  const saveEdit = async () => {
    if (!editing) return
    if (!editName.trim()) {
      push({ type: 'error', title: 'Team name is required' })
      return
    }
    try {
      setSaving(true)
      await put(`/api/teams/${editing}`, {
        name: editName.trim(),
        description: editDescription.trim(),
      })
      setEditing(null)
      push({ type: 'success', title: 'Team updated' })
      loadTeams()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setSaving(false)
    }
  }

  const removeTeam = async (team) => {
    if (!window.confirm(`Delete "${team.name}"? This will remove its memberships.`)) return
    try {
      setSaving(true)
      await del(`/api/teams/${team.id}`)
      push({ type: 'success', title: 'Team deleted' })
      loadTeams()
    } catch (err) {
      push({ type: 'error', title: err.message, message: err.actionable_hint || '' })
    } finally {
      setSaving(false)
    }
  }

  const pageStart = offset + 1
  const pageEnd = Math.min(offset + DEFAULT_LIMIT, total)
  const totalMachines = teams.reduce((sum, team) => sum + Number(team.machine_count || 0), 0)
  const activeNow = teams.reduce((sum, team) => sum + Number(team.active_now || 0), 0)
  const describedTeams = teams.filter((team) => team.description?.trim()).length

  return (
    <div className="fade-in machine-calm-shell">
      <div className="page-header machine-calm-header">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <AverageHoursIcon size={24} />
          </div>
          <div>
            <div className="page-title">Teams</div>
            <div className="page-subtitle">Create operating groups, organize machines, and watch team performance in one calmer workflow.</div>
          </div>
        </div>
      </div>

      <div className="grid-4" style={{ marginBottom: 16 }}>
        <TeamMetricCard icon={AverageHoursIcon} label="Teams" value={total} subtext="Visible in this view" tone="machine-calm-tone-brand" />
        <TeamMetricCard icon={MachinesIcon} label="Machines" value={totalMachines} subtext="Assigned across listed teams" tone="machine-calm-tone-sage" />
        <TeamMetricCard icon={OnlineIcon} label="Active Now" value={activeNow} subtext="Currently online in these teams" tone="machine-calm-tone-sand" />
        <TeamMetricCard icon={AlertsIcon} label="With Notes" value={describedTeams} subtext="Teams with descriptions" tone="machine-calm-tone-slate" />
      </div>

      <div className="card machine-calm-card team-create-card" style={{ marginBottom: 14 }}>
        {loadError && (
          <InlineBanner
            tone="danger"
            title="Failed to load teams"
            message={loadError.message}
            actionLabel="Retry"
            onAction={loadTeams}
            onClose={() => setLoadError(null)}
          />
        )}
        <div className="card-header" style={{ marginBottom: 12 }}>
          <div>
            <div className="card-title">Create Team</div>
            <div className="stat-sub">Add a team name and a short purpose so the list stays understandable as it grows.</div>
          </div>
        </div>
        <form onSubmit={createTeam} className="team-form-grid">
          <input
            className="input-field machine-calm-search"
            placeholder="Team name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className="input-field machine-calm-search"
            placeholder="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <button className="btn btn-primary machine-calm-primary" type="submit" disabled={saving}>Create Team</button>
        </form>
      </div>

      <div className="filter-bar machine-calm-toolbar">
        <input
          className="input-field machine-calm-search"
          placeholder="Search teams..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ maxWidth: 320 }}
        />
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-3)' }}>
          {total} team{total !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="card machine-calm-card" style={{ padding: 0, overflow: 'hidden' }}>
        <PageStateView
          state={loading ? 'loading' : (loadError && teams.length === 0 ? 'error' : (teams.length === 0 ? 'empty' : 'ready'))}
          title={loadError ? 'Could not load teams' : 'No teams found'}
          message={loadError ? (loadError.actionable_hint || loadError.message) : 'Create your first team to get started.'}
          onRetry={loadTeams}
        >
          <table className="data-table machine-calm-table">
            <thead>
              <tr>
                <th>Team</th>
                <th>Description</th>
                <th>Machines</th>
                <th>Active Now</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {teams.map((team) => (
                <tr key={team.id}>
                  <td>
                    <div className="machine-calm-machine-main">
                      <span className="machine-calm-machine-badge">
                        <AverageHoursIcon size={14} />
                      </span>
                      <div>
                        <div style={{ fontWeight: 700, color: 'var(--machine-calm-1)' }}>{team.name}</div>
                        <div className="machine-calm-machine-id">Team #{team.id}</div>
                      </div>
                    </div>
                  </td>
                  <td style={{ color: 'var(--text-2)', fontSize: 12 }}>{team.description || '--'}</td>
                  <td><span className="badge badge-blue" style={{ color: 'var(--machine-calm-1)', borderColor: 'color-mix(in srgb, var(--machine-calm-1) 18%, transparent)', background: 'color-mix(in srgb, var(--machine-calm-1) 10%, transparent)' }}>{team.machine_count || 0}</span></td>
                  <td><span className="badge badge-green">{team.active_now || 0} live</span></td>
                  <td style={{ fontSize: 12, color: 'var(--text-3)' }}>
                    {team.created_at ? new Date(team.created_at).toLocaleDateString() : '--'}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => navigate(`/teams/${team.id}`)}>
                        Open
                      </button>
                      <button className="btn btn-ghost btn-sm machine-calm-btn" onClick={() => startEdit(team)} disabled={saving}>
                        Edit
                      </button>
                      <button className="btn btn-danger btn-sm" onClick={() => removeTeam(team)} disabled={saving}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </PageStateView>
      </div>

      {editing && (
        <div className="card machine-calm-card" style={{ marginTop: 12 }}>
          <div className="card-header" style={{ marginBottom: 10 }}>
            <div>
              <div className="card-title">Edit Team</div>
              <div className="stat-sub">Update the display name or adjust the purpose text.</div>
            </div>
          </div>
          <div className="team-form-grid team-form-grid-edit">
            <input className="input-field machine-calm-search" value={editName} onChange={(e) => setEditName(e.target.value)} />
            <input
              className="input-field machine-calm-search"
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
            />
            <button className="btn btn-primary machine-calm-primary" onClick={saveEdit} disabled={saving}>Save</button>
            <button className="btn btn-ghost machine-calm-btn" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      )}

      {total > DEFAULT_LIMIT && (
        <div className="machine-calm-pagination" style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--text-3)' }}>
            Showing {pageStart}-{pageEnd} of {total}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn btn-ghost btn-sm machine-calm-btn" disabled={offset === 0} onClick={() => setOffset(0)}>{'<<'}</button>
            <button
              className="btn btn-ghost btn-sm machine-calm-btn"
              disabled={offset === 0}
              onClick={() => setOffset((v) => Math.max(0, v - DEFAULT_LIMIT))}
            >
              {'<'}
            </button>
            <button
              className="btn btn-ghost btn-sm machine-calm-btn"
              disabled={offset + DEFAULT_LIMIT >= total}
              onClick={() => setOffset((v) => v + DEFAULT_LIMIT)}
            >
              {'>'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
