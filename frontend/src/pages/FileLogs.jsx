import { useCallback, useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useApi, useAuth } from '../hooks/useAuth'
import { exportCsv } from '../utils/csv'
import { useActivityFeed, useActivityMachines } from '../features/activity/activityShared'
import { ActivityDrawer, ActivityToolbar } from '../features/activity/activityUi'
import { PageStateView } from '../components/ui/PageState'
import { FileIcon } from '../components/ui/OverviewIcons'

const ACTION_META = {
  create: { color: 'var(--green)', bg: 'var(--green-dim)', label: 'Created', hex: '#0FC97D' },
  delete: { color: 'var(--red)', bg: 'var(--red-dim)', label: 'Deleted', hex: '#F04343' },
  modify: { color: 'var(--amber)', bg: 'var(--amber-dim)', label: 'Modified', hex: '#F5A623' },
  move: { color: 'var(--brand)', bg: 'var(--brand-dim)', label: 'Moved', hex: '#3B7BF8' },
}

const PALETTE = ['#3B7BF8', '#0FC97D', '#F5A623', '#F04343', '#8B5CF6', '#22D3EE', '#EC4899', '#84CC16']

const fmtTs = (ts) => (ts ? new Date(ts).toLocaleString() : '-')
const fmtAgo = (ts) => {
  if (!ts) return '-'
  const seconds = Math.floor((Date.now() - new Date(ts)) / 1000)
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return new Date(ts).toLocaleDateString()
}
const fmtSize = (bytes) => {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}
const labelTone = (label = '') => {
  const value = String(label).toLowerCase()
  if (value.includes('high')) return { color: 'var(--red)', bg: 'var(--red-dim)' }
  if (value.includes('confidential') || value.includes('restricted')) return { color: 'var(--amber)', bg: 'var(--amber-dim)' }
  if (value.includes('internal')) return { color: 'var(--brand)', bg: 'var(--brand-dim)' }
  return { color: 'var(--text-3)', bg: 'var(--surface-3)' }
}

function TooltipCard({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      {label && <div className="chart-tooltip-label">{label}</div>}
      {payload.map((item, index) => (
        <div key={index} style={{ color: item.color || item.fill || 'var(--text-1)', fontWeight: 600, fontSize: 12, marginTop: 2 }}>
          {item.name}: {item.value}
        </div>
      ))}
    </div>
  )
}

function KpiCard({ label, value, sub, color }) {
  return (
    <div className="stat-card machine-calm-card machine-calm-stat analytics-kpi stagger">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ color }}>{value}</div>
      <div className="stat-sub">{sub}</div>
    </div>
  )
}

function DetailRow({ label, value }) {
  return (
    <>
      <span style={{ color: 'var(--text-3)', fontWeight: 600, fontSize: 11, textTransform: 'uppercase' }}>{label}</span>
      <span style={{ color: 'var(--text-2)', wordBreak: 'break-word' }}>{value || '—'}</span>
    </>
  )
}

export default function FileLogs() {
  const { get, del: apiDel } = useApi()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const { machines, selectedId: selMachine, setSelectedId: setSelMachine } = useActivityMachines({ defaultMode: 'all' })
  const [action, setAction] = useState('')
  const [search, setSearch] = useState('')
  const [date, setDate] = useState('')
  const [page, setPage] = useState(0)
  const [selectedRow, setSelectedRow] = useState(null)
  const [showVault, setShowVault] = useState(false)
  const [vaultItems, setVaultItems] = useState([])
  const [vaultTotal, setVaultTotal] = useState(0)
  const [vaultSearch, setVaultSearch] = useState('')
  const [vaultPage, setVaultPage] = useState(0)
  const [vaultLoading, setVaultLoading] = useState(false)
  const PAGE_SIZE = 50

  const { items: logs, total, stats, loading, refreshing, error, uiState, refresh } = useActivityFeed({
    endpoint: '/api/activity/file-logs',
    params: { machine_id: selMachine, action, search, date, limit: PAGE_SIZE, offset: page * PAGE_SIZE },
    realtimeTypes: ['file_update'],
  })

  const fetchVault = useCallback(() => {
    if (!isAdmin) return Promise.resolve()
    setVaultLoading(true)
    const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(vaultPage * PAGE_SIZE) })
    if (selMachine) query.set('machine_id', selMachine)
    if (vaultSearch) query.set('search', vaultSearch)
    return get(`/api/files/vault?${query}`)
      .then((result) => {
        setVaultItems(result.backups || [])
        setVaultTotal(result.total || 0)
      })
      .catch(() => {
        setVaultItems([])
        setVaultTotal(0)
      })
      .finally(() => setVaultLoading(false))
  }, [PAGE_SIZE, get, isAdmin, selMachine, vaultPage, vaultSearch])

  useEffect(() => {
    if (showVault) {
      fetchVault().catch(() => {})
    }
  }, [fetchVault, showVault])

  const downloadBackup = useCallback(async (id) => {
    try {
      const backup = await get(`/api/files/vault/${id}`)
      if (!backup?.file_data) return
      const binary = atob(backup.file_data)
      const bytes = new Uint8Array(binary.length)
      for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
      const blob = new Blob([bytes])
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = backup.file_name || 'backup'
      anchor.click()
      URL.revokeObjectURL(url)
    } catch {}
  }, [get])

  const deleteBackup = useCallback(async (id) => {
    if (!window.confirm('Delete this backup permanently?')) return
    try {
      await apiDel(`/api/files/vault/${id}`)
      await fetchVault()
    } catch {}
  }, [apiDel, fetchVault])

  const actionPieData = useMemo(() => (
    (stats?.by_action || []).map((row) => ({
      name: ACTION_META[row.action]?.label || row.action,
      value: row.cnt,
      fill: ACTION_META[row.action]?.hex || '#64748B',
    }))
  ), [stats])

  const extBarData = useMemo(() => {
    const counts = new Map()
    logs.forEach((item) => {
      let ext = item.file_ext || ''
      if (!ext || ext.length > 10 || /^\.\d+$/.test(ext)) ext = item.is_directory ? 'folder' : 'other'
      counts.set(ext, (counts.get(ext) || 0) + 1)
    })
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name, value]) => ({ name, value }))
  }, [logs])

  const summary = {
    total: stats?.total ?? 0,
    last24h: stats?.last_24h ?? 0,
    created: stats?.by_action?.find((row) => row.action === 'create')?.cnt ?? 0,
    deleted: stats?.by_action?.find((row) => row.action === 'delete')?.cnt ?? 0,
  }
  const totalPages = Math.max(1, Math.ceil((total || 0) / PAGE_SIZE))
  const vaultPages = Math.max(1, Math.ceil((vaultTotal || 0) / PAGE_SIZE))
  const canClear = Boolean(selMachine || action || search || date)

  return (
    <div className="fade-in analytics-shell">
      <div className="page-header machine-calm-header analytics-hero">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <FileIcon size={24} />
          </div>
          <div>
            <div className="page-title">File Activity</div>
            <div className="page-subtitle">Unified file investigation view with recoverability and vault status.</div>
          </div>
        </div>
      </div>

      <div className="grid-4" style={{ marginBottom: 20 }}>
        <div className="analytics-kpi"><KpiCard label="TOTAL EVENTS" value={summary.total.toLocaleString()} sub="All recorded file operations" color="var(--brand)" /></div>
        <div className="analytics-kpi"><KpiCard label="LAST 24 HOURS" value={summary.last24h.toLocaleString()} sub="Recent activity" color="var(--green)" /></div>
        <div className="analytics-kpi"><KpiCard label="FILES CREATED" value={summary.created.toLocaleString()} sub="New files and folders" color="var(--amber)" /></div>
        <div className="analytics-kpi"><KpiCard label="FILES DELETED" value={summary.deleted.toLocaleString()} sub={isAdmin ? 'Correlate with vault coverage' : 'Deleted events'} color="var(--red)" /></div>
      </div>

      <div className="grid-2" style={{ marginBottom: 20 }}>
        <div className="card machine-calm-card analytics-card">
          <div className="card-header">
            <span className="card-title">Action Breakdown</span>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>by event type</span>
          </div>
          {actionPieData.length ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <ResponsiveContainer width="50%" height={200}>
                <PieChart>
                  <Pie data={actionPieData} cx="50%" cy="50%" innerRadius={46} outerRadius={74} dataKey="value" stroke="none" paddingAngle={2}>
                    {actionPieData.map((item, index) => <Cell key={index} fill={item.fill} />)}
                  </Pie>
                  <Tooltip content={<TooltipCard />} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {actionPieData.map((item, index) => (
                  <div key={index} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: item.fill, flexShrink: 0 }} />
                    <span style={{ flex: 1, color: 'var(--text-2)' }}>{item.name}</span>
                    <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11 }}>{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: 36, color: 'var(--text-3)' }}>No file activity yet</div>
          )}
        </div>

        <div className="card machine-calm-card analytics-card">
          <div className="card-header">
            <span className="card-title">Top File Types</span>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>current page</span>
          </div>
          {extBarData.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={extBarData} barSize={18}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TooltipCard />} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {extBarData.map((_, index) => <Cell key={index} fill={PALETTE[index % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ textAlign: 'center', padding: 36, color: 'var(--text-3)' }}>No extension data</div>
          )}
        </div>
      </div>

      {showVault && isAdmin && (
        <div className="card machine-calm-card analytics-card" style={{ marginBottom: 20 }}>
          <div className="card-header" style={{ marginBottom: 12 }}>
            <span className="card-title">Secret Vault</span>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input className="input-field" placeholder="Search vault..." value={vaultSearch} onChange={(e) => { setVaultSearch(e.target.value); setVaultPage(0) }} style={{ width: 220, fontSize: 12 }} />
              <button className="btn btn-ghost btn-sm" onClick={() => fetchVault()}>Refresh</button>
            </div>
          </div>

          {vaultLoading ? (
            <div style={{ textAlign: 'center', padding: 32 }}><span className="spinner" style={{ width: 24, height: 24, borderWidth: 2 }} /></div>
          ) : vaultItems.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-3)' }}>
              Vault is empty. Only deleted files captured before removal are recoverable. Oversized or excluded files are not stored.
            </div>
          ) : (
            <>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Machine</th>
                      <th>User</th>
                      <th>File</th>
                      <th>Original Path</th>
                      <th>Size</th>
                      <th style={{ width: 90 }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {vaultItems.map((item) => (
                      <tr key={item.id}>
                        <td className="mono" style={{ fontSize: 12 }}>{fmtAgo(item.timestamp)}</td>
                        <td><span className="badge badge-gray">{item.hostname || item.machine_id?.slice(0, 10)}</span></td>
                        <td>{item.username || '-'}</td>
                        <td>{item.file_name}</td>
                        <td className="mono" style={{ fontSize: 12, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.original_path}>{item.original_path}</td>
                        <td className="mono" style={{ fontSize: 12 }}>{fmtSize(item.file_size)}</td>
                        <td>
                          <div style={{ display: 'flex', gap: 4, justifyContent: 'center' }}>
                            <button className="btn btn-ghost btn-sm" onClick={() => downloadBackup(item.id)}>Download</button>
                            <button className="btn btn-ghost btn-sm" onClick={() => deleteBackup(item.id)} style={{ color: 'var(--red)' }}>Delete</button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {vaultPages > 1 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
                  <span style={{ fontSize: 12, color: 'var(--text-3)' }}>Showing {vaultPage * PAGE_SIZE + 1}-{Math.min((vaultPage + 1) * PAGE_SIZE, vaultTotal)} of {vaultTotal}</span>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <button className="btn btn-ghost btn-sm" disabled={vaultPage === 0} onClick={() => setVaultPage((value) => value - 1)}>Prev</button>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--text-3)' }}>{vaultPage + 1} / {vaultPages}</span>
                    <button className="btn btn-ghost btn-sm" disabled={vaultPage >= vaultPages - 1} onClick={() => setVaultPage((value) => value + 1)}>Next</button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      <ActivityToolbar
        machines={machines}
        selectedId={selMachine}
        onMachineChange={(value) => { setSelMachine(value); setPage(0) }}
        search={search}
        onSearchChange={(value) => { setSearch(value); setPage(0) }}
        searchPlaceholder="Search file name or path..."
        date={date}
        onDateChange={(value) => { setDate(value); setPage(0) }}
        extraFilters={(
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {['', 'create', 'delete', 'modify', 'move'].map((value) => {
              const meta = value ? ACTION_META[value] : null
              const active = action === value
              return (
                <button
                  key={value || 'all'}
                  className={`btn btn-sm ${active ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => { setAction(value); setPage(0) }}
                  style={active && meta ? { background: meta.bg, color: meta.color, borderColor: meta.color } : {}}
                >
                  {value ? meta.label : 'All'}
                </button>
              )
            })}
          </div>
        )}
        rightActions={(
          <>
            <button className="btn btn-ghost btn-sm" onClick={() => refresh()}>
              {refreshing ? <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} /> : 'Refresh'}
            </button>
            {isAdmin && (
              <button className={`btn btn-sm ${showVault ? 'btn-primary' : 'btn-outline'}`} onClick={() => { setShowVault((value) => !value); if (!showVault) fetchVault() }}>
                Secret Vault {vaultTotal > 0 ? `(${vaultTotal})` : ''}
              </button>
            )}
            <button
              className="btn btn-outline btn-sm"
              disabled={!logs.length}
              onClick={() => exportCsv(`file_logs_${selMachine || 'all'}.csv`, logs, [
                { key: 'timestamp', label: 'Timestamp' },
                { key: 'hostname', label: 'Machine' },
                { key: 'machine_id', label: 'Machine ID' },
                { key: 'username', label: 'User' },
                { key: 'action', label: 'Action' },
                { key: 'file_name', label: 'File' },
                { key: 'file_ext', label: 'Extension' },
                { key: 'file_path', label: 'Path' },
                { key: 'destination', label: 'Destination' },
                { key: 'enterprise_label', label: 'Enterprise Label' },
                { key: 'label_source', label: 'Label Source' },
                { key: 'label_reason', label: 'Label Reason' },
                { key: 'file_size', label: 'Size (bytes)' },
                { key: 'is_directory', label: 'Directory' },
                { key: 'backup_available', label: 'Backup Available' },
                { key: 'backup_skip_reason', label: 'Backup Skip Reason' },
              ])}
            >
              CSV
            </button>
          </>
        )}
        onClear={() => { setSelMachine(''); setAction(''); setSearch(''); setDate(''); setPage(0) }}
        clearable={canClear}
      />

      {error && (
        <div style={{ marginBottom: 16 }}>
          <div className="ui-inline-banner ui-inline-banner-warning" role="status">
            <div className="ui-inline-banner-copy">
              <strong>Partial data</strong>
              <span>File activity is showing cached data because the latest fetch failed.</span>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => refresh()}>Retry</button>
          </div>
        </div>
      )}

      <PageStateView
        state={uiState}
        title="No file activity found"
        message="Adjust filters or select another machine."
        onRetry={refresh}
      >
        <div className="card machine-calm-card analytics-card">
          <div className="card-header" style={{ marginBottom: 12 }}>
            <span className="card-title">File Operations</span>
            <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
              {total.toLocaleString()} results
              {loading && <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2, marginLeft: 8 }} />}
            </span>
          </div>

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Machine</th>
                  <th>User</th>
                  <th>Action</th>
                  <th>File</th>
                  <th>Enterprise Label</th>
                  <th>Ext</th>
                  <th>Size</th>
                  <th style={{ width: 44 }} />
                </tr>
              </thead>
              <tbody>
                {logs.map((item, index) => {
                  const id = item.id || `${item.timestamp}-${index}`
                  const meta = ACTION_META[item.action] || { color: 'var(--text-3)', bg: 'var(--surface-3)', label: item.action || 'Event' }
                  return (
                    <tr key={id} onClick={() => setSelectedRow(item)} style={{ cursor: 'pointer' }}>
                      <td className="mono" style={{ fontSize: 12 }}>{fmtAgo(item.timestamp)}</td>
                      <td><span className="badge badge-gray">{item.hostname || item.machine_id?.slice(0, 10)}</span></td>
                      <td>{item.username || '-'}</td>
                      <td>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '3px 10px', borderRadius: 6, background: meta.bg, color: meta.color, fontSize: 12, fontWeight: 600 }}>
                          {meta.label}
                        </span>
                      </td>
                      <td>
                        <div style={{ fontWeight: 500 }}>{item.file_name || '-'}</div>
                        {item.action === 'delete' && (
                          <div style={{ marginTop: 6 }}>
                            <span style={{ display: 'inline-flex', padding: '2px 8px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: item.backup_available ? 'var(--green-dim)' : 'var(--amber-dim)', color: item.backup_available ? 'var(--green)' : 'var(--amber)' }}>
                              {item.backup_available ? 'Backed up' : 'Not recoverable'}
                            </span>
                          </div>
                        )}
                      </td>
                      <td>
                        {item.enterprise_label ? (
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              padding: '3px 10px',
                              borderRadius: 999,
                              fontSize: 11,
                              fontWeight: 700,
                              ...labelTone(item.enterprise_label),
                            }}
                            title={item.label_reason || item.label_source || item.enterprise_label}
                          >
                            {item.enterprise_label}
                          </span>
                        ) : (
                          <span style={{ color: 'var(--text-3)', fontSize: 12 }}>Unlabeled</span>
                        )}
                      </td>
                      <td className="mono" style={{ fontSize: 11 }}>{item.file_ext || '-'}</td>
                      <td className="mono" style={{ fontSize: 12 }}>{fmtSize(item.file_size)}</td>
                      <td style={{ textAlign: 'center', color: 'var(--text-3)' }}>{'>'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14 }}>
              <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
                Showing {page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
              </span>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <button className="btn btn-ghost btn-sm" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>Prev</button>
                <span className="mono" style={{ fontSize: 12, color: 'var(--text-3)' }}>{page + 1} / {totalPages}</span>
                <button className="btn btn-ghost btn-sm" disabled={page >= totalPages - 1} onClick={() => setPage((value) => value + 1)}>Next</button>
              </div>
            </div>
          )}
        </div>
      </PageStateView>

      <ActivityDrawer
        open={Boolean(selectedRow)}
        title={selectedRow?.file_name || 'File activity'}
        subtitle={selectedRow?.file_path}
        badges={[
          { label: ACTION_META[selectedRow?.action]?.label || selectedRow?.action || 'Event' },
          { label: selectedRow?.backup_available ? 'Backed up' : 'Not recoverable' },
        ]}
        onClose={() => setSelectedRow(null)}
      >
        {selectedRow && (
          <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '10px 16px', fontSize: 13 }}>
            <DetailRow label="Full Path" value={selectedRow.file_path} />
            <DetailRow label="Timestamp" value={fmtTs(selectedRow.timestamp)} />
            <DetailRow label="Machine ID" value={selectedRow.machine_id} />
            <DetailRow label="Type" value={selectedRow.is_directory ? 'Directory' : 'File'} />
            <DetailRow label="User" value={selectedRow.username} />
            <DetailRow label="Action" value={ACTION_META[selectedRow.action]?.label || selectedRow.action} />
            <DetailRow label="Enterprise Label" value={selectedRow.enterprise_label || 'Unlabeled'} />
            <DetailRow label="Label Source" value={selectedRow.label_source} />
            <DetailRow label="Label Reason" value={selectedRow.label_reason} />
            <DetailRow label="Vault Status" value={selectedRow.action === 'delete' ? (selectedRow.backup_available ? 'Backed up in Secret Vault' : `Not recoverable${selectedRow.backup_skip_reason ? ` (${selectedRow.backup_skip_reason})` : ''}`) : 'Not applicable'} />
            {selectedRow.action === 'move' && selectedRow.destination && <DetailRow label="Moved To" value={selectedRow.destination} />}
          </div>
        )}
      </ActivityDrawer>
    </div>
  )
}
