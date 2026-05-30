import { useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
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
import { exportCsv } from '../utils/csv'
import { useActivityFeed, useActivityMachines } from '../features/activity/activityShared'
import { ActivityDrawer, ActivityToolbar } from '../features/activity/activityUi'
import { PageStateView } from '../components/ui/PageState'
import { NetworkIcon } from '../components/ui/OverviewIcons'

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
const fmtBytes = (bytes) => {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function TooltipCard({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      {label && <div className="chart-tooltip-label">{label}</div>}
      {payload.map((item, index) => (
        <div key={index} style={{ color: item.color || item.fill || 'var(--text-1)', fontWeight: 600, fontSize: 12, marginTop: 2 }}>
          {item.name}: {typeof item.value === 'number' ? fmtBytes(item.value) : item.value}
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

export default function NetworkLogs() {
  const { machines, selectedId: selMachine, setSelectedId: setSelMachine } = useActivityMachines({ defaultMode: 'all' })
  const [search, setSearch] = useState('')
  const [date, setDate] = useState('')
  const [page, setPage] = useState(0)
  const [selectedRow, setSelectedRow] = useState(null)
  const [detailTab, setDetailTab] = useState('ports')
  const PAGE_SIZE = 30

  const { items: logs, total, stats, loading, refreshing, error, uiState, refresh } = useActivityFeed({
    endpoint: '/api/activity/network-logs',
    params: { machine_id: selMachine, search, date, limit: PAGE_SIZE, offset: page * PAGE_SIZE },
    realtimeTypes: ['network_update'],
  })

  const latestSnapshots = stats?.latest_by_machine || []

  const allListeningPorts = useMemo(() => {
    const map = new Map()
    latestSnapshots.forEach((snapshot) => {
      ;(snapshot.listening_ports || []).forEach((port) => {
        const key = `${port.port}:${port.protocol}:${port.process || ''}`
        const current = map.get(key)
        if (current) current.machines += 1
        else map.set(key, { ...port, machines: 1 })
      })
    })
    return Array.from(map.values()).sort((a, b) => Number(a.port || 0) - Number(b.port || 0))
  }, [latestSnapshots])

  const topPortsData = useMemo(() => {
    const counts = new Map()
    latestSnapshots.forEach((snapshot) => {
      ;(snapshot.listening_ports || []).forEach((port) => {
        const label = `${port.port} (${port.process || '?'})`
        counts.set(label, (counts.get(label) || 0) + 1)
      })
    })
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([name, value]) => ({ name, value }))
  }, [latestSnapshots])

  const topHostsData = useMemo(() => {
    const counts = new Map()
    latestSnapshots.forEach((snapshot) => {
      ;(snapshot.connections || []).forEach((conn) => {
        const name = conn.domain || conn.remote_ip || 'unknown'
        counts.set(name, (counts.get(name) || 0) + 1)
      })
    })
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name, value]) => ({ name: name.length > 26 ? `${name.slice(0, 23)}...` : name, value, full: name }))
  }, [latestSnapshots])

  const protocolPieData = useMemo(() => {
    const counts = new Map()
    latestSnapshots.forEach((snapshot) => {
      ;(snapshot.connections || []).forEach((conn) => {
        const key = String(conn.protocol || 'tcp').toUpperCase()
        counts.set(key, (counts.get(key) || 0) + 1)
      })
      ;(snapshot.listening_ports || []).forEach((port) => {
        const key = String(port.protocol || 'tcp').toUpperCase()
        counts.set(key, (counts.get(key) || 0) + 1)
      })
    })
    return Array.from(counts.entries()).map(([name, value], index) => ({
      name,
      value,
      fill: PALETTE[index % PALETTE.length],
    }))
  }, [latestSnapshots])

  const bandwidthData = useMemo(() => (
    [...logs]
      .reverse()
      .slice(-20)
      .map((item) => ({
        time: new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        sent: item.bytes_sent || 0,
        recv: item.bytes_recv || 0,
      }))
  ), [logs])

  const totals = useMemo(() => ({
    openPorts: latestSnapshots.reduce((sum, row) => sum + Number(row.listen_count || 0), 0),
    activeConnections: latestSnapshots.reduce((sum, row) => sum + Number(row.conn_count || 0), 0),
    sent: logs.reduce((sum, row) => sum + Number(row.bytes_sent || 0), 0),
    recv: logs.reduce((sum, row) => sum + Number(row.bytes_recv || 0), 0),
  }), [latestSnapshots, logs])

  const totalPages = Math.max(1, Math.ceil((total || 0) / PAGE_SIZE))
  const canClear = Boolean(selMachine || search || date)

  return (
    <div className="fade-in analytics-shell">
      <div className="page-header machine-calm-header analytics-hero">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <NetworkIcon size={24} />
          </div>
          <div>
            <h2 className="page-title">Network Activity</h2>
            <p className="page-subtitle">Unified network investigation view for ports, connections, and bandwidth.</p>
          </div>
        </div>
      </div>

      <div className="grid-4" style={{ marginBottom: 20 }}>
        <div className="analytics-kpi"><KpiCard label="OPEN PORTS" value={totals.openPorts} sub="Current listening endpoints" color="var(--brand)" /></div>
        <div className="analytics-kpi"><KpiCard label="ACTIVE CONNECTIONS" value={totals.activeConnections} sub="Established sessions" color="var(--green)" /></div>
        <div className="analytics-kpi"><KpiCard label="DATA SENT" value={fmtBytes(totals.sent)} sub="Current page window" color="var(--amber)" /></div>
        <div className="analytics-kpi"><KpiCard label="DATA RECEIVED" value={fmtBytes(totals.recv)} sub="Current page window" color="var(--purple)" /></div>
      </div>

      <div className="grid-2" style={{ marginBottom: 20 }}>
        <div className="card machine-calm-card analytics-card">
          <div className="card-header">
            <span className="card-title">Top Listening Ports</span>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>by process</span>
          </div>
          {topPortsData.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={topPortsData} layout="vertical" margin={{ left: 8, right: 8, top: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TooltipCard />} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {topPortsData.map((_, index) => <Cell key={index} fill={PALETTE[index % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ textAlign: 'center', padding: 36, color: 'var(--text-3)' }}>No port data</div>
          )}
        </div>

        <div className="card machine-calm-card analytics-card">
          <div className="card-header">
            <span className="card-title">Bandwidth Trend</span>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>recent snapshots</span>
          </div>
          {bandwidthData.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={bandwidthData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" vertical={false} />
                <XAxis dataKey="time" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TooltipCard />} />
                <Area type="monotone" dataKey="sent" name="Sent" fill="#F5A62333" stroke="#F5A623" strokeWidth={2} />
                <Area type="monotone" dataKey="recv" name="Received" fill="#3B7BF833" stroke="#3B7BF8" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ textAlign: 'center', padding: 36, color: 'var(--text-3)' }}>No bandwidth data</div>
          )}
        </div>
      </div>

        <div className="grid-2" style={{ marginBottom: 20 }}>
        <div className="card machine-calm-card analytics-card">
          <div className="card-header">
            <span className="card-title">Top Remote Hosts</span>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>active connections</span>
          </div>
          {topHostsData.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={topHostsData} barSize={18}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 9 }} axisLine={false} tickLine={false} interval={0} angle={-18} textAnchor="end" height={52} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<TooltipCard />} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {topHostsData.map((_, index) => <Cell key={index} fill={PALETTE[index % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ textAlign: 'center', padding: 36, color: 'var(--text-3)' }}>No remote host data</div>
          )}
        </div>

        <div className="card machine-calm-card analytics-card">
          <div className="card-header">
            <span className="card-title">Protocol Mix</span>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>current network surface</span>
          </div>
          {protocolPieData.length ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <ResponsiveContainer width="50%" height={200}>
                <PieChart>
                  <Pie data={protocolPieData} cx="50%" cy="50%" innerRadius={46} outerRadius={74} dataKey="value" stroke="none" paddingAngle={2}>
                    {protocolPieData.map((item, index) => <Cell key={index} fill={item.fill} />)}
                  </Pie>
                  <Tooltip content={<TooltipCard />} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {protocolPieData.map((item, index) => (
                  <div key={index} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: item.fill, flexShrink: 0 }} />
                    <span style={{ flex: 1, color: 'var(--text-2)' }}>{item.name}</span>
                    <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11 }}>{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: 36, color: 'var(--text-3)' }}>No protocol data</div>
          )}
        </div>
      </div>

      <ActivityToolbar
        machines={machines}
        selectedId={selMachine}
        onMachineChange={(value) => { setSelMachine(value); setPage(0) }}
        search={search}
        onSearchChange={(value) => { setSearch(value); setPage(0) }}
        searchPlaceholder="Search port, process, domain..."
        date={date}
        onDateChange={(value) => { setDate(value); setPage(0) }}
        rightActions={(
          <>
            <button className="btn btn-ghost btn-sm" onClick={() => refresh()}>
              {refreshing ? <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} /> : 'Refresh'}
            </button>
            <button
              className="btn btn-outline btn-sm"
              disabled={!logs.length}
              onClick={() => exportCsv(`network_logs_${selMachine || 'all'}.csv`, logs, [
                { key: 'timestamp', label: 'Timestamp' },
                { key: 'hostname', label: 'Machine' },
                { key: 'machine_id', label: 'Machine ID' },
                { key: 'listen_count', label: 'Open Ports' },
                { key: 'conn_count', label: 'Connections' },
                { key: 'bytes_sent', label: 'Bytes Sent' },
                { key: 'bytes_recv', label: 'Bytes Received' },
                { key: 'listening_ports', label: 'Listening Ports', value: (row) => JSON.stringify(row.listening_ports || []) },
                { key: 'connections', label: 'Connections', value: (row) => JSON.stringify(row.connections || []) },
              ])}
            >
              CSV
            </button>
          </>
        )}
        onClear={() => { setSelMachine(''); setSearch(''); setDate(''); setPage(0) }}
        clearable={canClear}
      />

      {error && (
        <div style={{ marginBottom: 16 }}>
          <div className="ui-inline-banner ui-inline-banner-warning" role="status">
            <div className="ui-inline-banner-copy">
              <strong>Partial data</strong>
              <span>Network activity is showing cached data because the latest fetch failed.</span>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => refresh()}>Retry</button>
          </div>
        </div>
      )}

      <PageStateView
        state={uiState}
        title="No network snapshots found"
        message="Select a machine and search window."
        onRetry={refresh}
      >
        <div className="card machine-calm-card analytics-card">
          <div className="card-header" style={{ marginBottom: 12 }}>
            <span className="card-title">Network Snapshots</span>
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
                  <th style={{ textAlign: 'center' }}>Open Ports</th>
                  <th style={{ textAlign: 'center' }}>Connections</th>
                  <th style={{ textAlign: 'right' }}>Sent</th>
                  <th style={{ textAlign: 'right' }}>Received</th>
                  <th style={{ width: 44 }} />
                </tr>
              </thead>
              <tbody>
                {logs.map((row) => (
                  <tr key={row.id} onClick={() => { setSelectedRow(row); setDetailTab('ports') }} style={{ cursor: 'pointer' }}>
                    <td className="mono" style={{ fontSize: 12 }}>{fmtAgo(row.timestamp)}</td>
                    <td><span className="badge badge-gray">{row.hostname || row.machine_id?.slice(0, 10)}</span></td>
                    <td style={{ textAlign: 'center' }}><span className="mono" style={{ color: 'var(--brand)', fontWeight: 700 }}>{row.listen_count || 0}</span></td>
                    <td style={{ textAlign: 'center' }}><span className="mono" style={{ color: 'var(--green)', fontWeight: 700 }}>{row.conn_count || 0}</span></td>
                    <td className="mono" style={{ textAlign: 'right', fontSize: 12 }}>{fmtBytes(row.bytes_sent || 0)}</td>
                    <td className="mono" style={{ textAlign: 'right', fontSize: 12 }}>{fmtBytes(row.bytes_recv || 0)}</td>
                    <td style={{ textAlign: 'center', color: 'var(--text-3)' }}>{'>'}</td>
                  </tr>
                ))}
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
        title={selectedRow?.hostname || selectedRow?.machine_id || 'Network snapshot'}
        subtitle={selectedRow?.timestamp}
        badges={[
          { label: `${selectedRow?.listen_count || 0} ports` },
          { label: `${selectedRow?.conn_count || 0} connections` },
        ]}
        onClose={() => setSelectedRow(null)}
      >
        {selectedRow && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className={`btn btn-sm ${detailTab === 'ports' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setDetailTab('ports')}>Ports ({(selectedRow.listening_ports || []).length})</button>
              <button className={`btn btn-sm ${detailTab === 'conns' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setDetailTab('conns')}>Connections ({(selectedRow.connections || []).length})</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '10px 16px', fontSize: 13 }}>
              <DetailRow label="Time" value={fmtTs(selectedRow.timestamp)} />
              <DetailRow label="Machine" value={selectedRow.hostname || selectedRow.machine_id} />
              <DetailRow label="Open Ports" value={selectedRow.listen_count} />
              <DetailRow label="Connections" value={selectedRow.conn_count} />
              <DetailRow label="Bytes Sent" value={fmtBytes(selectedRow.bytes_sent || 0)} />
              <DetailRow label="Bytes Received" value={fmtBytes(selectedRow.bytes_recv || 0)} />
            </div>
            {detailTab === 'ports' ? (
              (selectedRow.listening_ports || []).length ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Port</th>
                        <th>Protocol</th>
                        <th>Process</th>
                        <th>PID</th>
                        <th>Bind Address</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(selectedRow.listening_ports || []).map((port, index) => (
                        <tr key={index}>
                          <td className="mono" style={{ color: 'var(--brand)', fontWeight: 700 }}>{port.port}</td>
                          <td style={{ textTransform: 'uppercase', fontSize: 11 }}>{port.protocol}</td>
                          <td>{port.process || '-'}</td>
                          <td className="mono" style={{ fontSize: 12, color: 'var(--text-3)' }}>{port.pid || '-'}</td>
                          <td className="mono" style={{ fontSize: 12 }}>{port.address || '0.0.0.0'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div style={{ color: 'var(--text-3)' }}>No listening ports in this snapshot.</div>
            ) : (
              (selectedRow.connections || []).length ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Domain / IP</th>
                        <th>Remote Port</th>
                        <th>Local Port</th>
                        <th>Protocol</th>
                        <th>Process</th>
                        <th>PID</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(selectedRow.connections || []).map((conn, index) => (
                        <tr key={index}>
                          <td>{conn.domain || conn.remote_ip || '-'}</td>
                          <td className="mono" style={{ fontSize: 12 }}>{conn.remote_port || '-'}</td>
                          <td className="mono" style={{ fontSize: 12 }}>{conn.local_port || '-'}</td>
                          <td style={{ textTransform: 'uppercase', fontSize: 11 }}>{conn.protocol || 'tcp'}</td>
                          <td>{conn.process || '-'}</td>
                          <td className="mono" style={{ fontSize: 12, color: 'var(--text-3)' }}>{conn.pid || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div style={{ color: 'var(--text-3)' }}>No active connections in this snapshot.</div>
            )}
          </div>
        )}
      </ActivityDrawer>
    </div>
  )
}
