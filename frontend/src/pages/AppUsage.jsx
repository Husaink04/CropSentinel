import { useMemo, useState } from 'react'
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { exportCsv } from '../utils/csv'
import { useActivityFeed, useActivityMachines } from '../features/activity/activityShared'
import { ActivityDrawer, ActivityToolbar } from '../features/activity/activityUi'
import { PageStateView } from '../components/ui/PageState'
import { AppIcon } from '../components/ui/OverviewIcons'

const PALETTE = ['#3B7BF8', '#0FC97D', '#F5A623', '#F04343', '#8B5CF6', '#22D3EE', '#EC4899', '#84CC16']
const fmt = (s) => { if (!s) return '0m'; const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? `${h}h ${m}m` : `${m}m` }

const CAT_STYLE = {
  productive: { color: 'var(--green)', bg: 'var(--green-dim)', label: 'Productive' },
  neutral: { color: 'var(--text-3)', bg: 'var(--bg-4)', label: 'Neutral' },
}

const DONUT_COLORS = { productive: '#0FC97D', neutral: '#64748B' }
const todayStr = () => new Date().toISOString().slice(0, 10)

function TTip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map((p, i) => <div key={i} style={{ color: p.fill || p.color, fontWeight: 600, fontSize: 12, marginTop: 2 }}>{p.name}: {p.value}</div>)}
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

export default function AppUsage() {
  const { machines, selectedId: selId, setSelectedId: setSelId } = useActivityMachines({ defaultMode: 'first' })
  const [date, setDate] = useState(todayStr)
  const [catFilter, setCatFilter] = useState('')
  const [selectedRow, setSelectedRow] = useState(null)

  const { items: apps, loading, refreshing, error, uiState, refresh } = useActivityFeed({
    endpoint: '/api/activity/app-usage',
    params: { machine_id: selId, date, limit: 200, offset: 0 },
    realtimeTypes: ['app_update'],
    enabled: Boolean(selId),
  })

  const filtered = catFilter ? apps.filter((a) => a.category === catFilter) : apps
  const chartData = filtered.slice(0, 15).map((a) => ({ name: a.app_name.slice(0, 14), secs: a.total_seconds }))
  const totalSecs = filtered.reduce((sum, a) => sum + a.total_seconds, 0)

  const donutData = useMemo(() => {
    const prodSecs = apps.filter((a) => a.category === 'productive').reduce((sum, a) => sum + a.total_seconds, 0)
    const neutSecs = apps.filter((a) => a.category === 'neutral').reduce((sum, a) => sum + a.total_seconds, 0)
    return [
      { name: 'Productive', value: prodSecs, fill: DONUT_COLORS.productive },
      { name: 'Neutral', value: neutSecs, fill: DONUT_COLORS.neutral },
    ].filter((item) => item.value > 0)
  }, [apps])

  const topProd = useMemo(() => apps.filter((a) => a.category === 'productive').slice(0, 5), [apps])
  const topNeut = useMemo(() => apps.filter((a) => a.category === 'neutral').slice(0, 5), [apps])
  const canClear = Boolean(selId || date !== todayStr() || catFilter)

  return (
    <div className="fade-in analytics-shell">
      <div className="page-header machine-calm-header analytics-hero">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <AppIcon size={24} />
          </div>
          <div>
            <div className="page-title">App Usage</div>
            <div className="page-subtitle">Unified application view with productivity split and row-level detail.</div>
          </div>
        </div>
      </div>

      <ActivityToolbar
        machines={machines}
        selectedId={selId}
        onMachineChange={setSelId}
        date={date}
        onDateChange={setDate}
        extraFilters={(
          <select className="input-field" style={{ maxWidth: 150, fontSize: 12 }} value={catFilter} onChange={(e) => setCatFilter(e.target.value)}>
            <option value="">All categories</option>
            <option value="productive">Productive</option>
            <option value="neutral">Neutral</option>
          </select>
        )}
        rightActions={(
          <>
            <button className="btn btn-ghost btn-sm" onClick={() => refresh()}>
              {refreshing ? <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} /> : 'Refresh'}
            </button>
            <button
              className="btn btn-outline btn-sm"
              disabled={!filtered.length}
              onClick={() => exportCsv(`app_usage_${selId || 'all'}.csv`, filtered, [
                { key: 'app_name', label: 'Application' },
                { key: 'process_name', label: 'Process' },
                { key: 'sessions', label: 'Sessions' },
                { key: 'total_seconds', label: 'Total Seconds' },
                { key: 'category', label: 'Category' },
              ])}
            >
              CSV
            </button>
          </>
        )}
        onClear={() => { setSelId(''); setDate(todayStr()); setCatFilter('') }}
        clearable={canClear}
      />

      {error && (
        <div style={{ marginBottom: 16 }}>
          <div className="ui-inline-banner ui-inline-banner-warning" role="status">
            <div className="ui-inline-banner-copy">
              <strong>Partial data</strong>
              <span>Application usage is showing cached data because the latest fetch failed.</span>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => refresh()}>Retry</button>
          </div>
        </div>
      )}

      <PageStateView
        state={uiState}
        title="No app data"
        message="Select a machine and date range."
        onRetry={refresh}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="grid-2">
            <div className="card machine-calm-card analytics-card">
              <div className="card-header">
                <span style={{ fontSize: 14, fontWeight: 700 }}>App Usage - Top 8</span>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>minutes</span>
              </div>
              {(() => {
                const top8 = apps.slice(0, 8).map((a) => ({
                  name: a.app_name.length > 13 ? `${a.app_name.slice(0, 13)}...` : a.app_name,
                  minutes: Math.round((a.total_seconds || 0) / 60),
                }))
                return top8.length > 0 ? (
                  <ResponsiveContainer width="100%" height={210}>
                    <BarChart data={top8} barSize={16} margin={{ left: -10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border-0)" vertical={false} />
                      <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                      <Tooltip content={<TTip />} />
                      <Bar dataKey="minutes" radius={[4, 4, 0, 0]}>
                        {top8.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No data</div>
                )
              })()}
            </div>

            <div className="card machine-calm-card analytics-card">
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>Productivity Breakdown</div>
              {donutData.length === 0
                ? <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-3)', fontSize: 13 }}>No data</div>
                : (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <ResponsiveContainer width="50%" height={160}>
                      <PieChart>
                        <Pie data={donutData} cx="50%" cy="50%" innerRadius={40} outerRadius={65} dataKey="value" stroke="none" paddingAngle={3}>
                          {donutData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                        </Pie>
                        <Tooltip content={<TTip />} formatter={(v) => fmt(v)} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {donutData.map((d, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                          <span style={{ width: 10, height: 10, borderRadius: 2, background: d.fill, flexShrink: 0 }} />
                          <span style={{ flex: 1, color: 'var(--text-2)' }}>{d.name}</span>
                          <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>{fmt(d.value)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
            </div>
          </div>

          {(topProd.length > 0 || topNeut.length > 0) && (
            <div className="grid-2">
              <div className="card machine-calm-card analytics-card">
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: '#0FC97D' }}>Top Productive Apps</div>
                {topProd.length === 0
                  ? <div style={{ fontSize: 12, color: 'var(--text-3)' }}>None matched</div>
                  : topProd.map((a, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span style={{ width: 18, fontSize: 11, color: 'var(--text-3)', textAlign: 'right' }}>{i + 1}.</span>
                      <span style={{ flex: 1, fontSize: 12, fontWeight: 600 }}>{a.app_name}</span>
                      <span className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{fmt(a.total_seconds)}</span>
                    </div>
                  ))}
              </div>
              <div className="card machine-calm-card analytics-card">
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: '#64748B' }}>Top Neutral Apps</div>
                {topNeut.length === 0
                  ? <div style={{ fontSize: 12, color: 'var(--text-3)' }}>None</div>
                  : topNeut.map((a, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span style={{ width: 18, fontSize: 11, color: 'var(--text-3)', textAlign: 'right' }}>{i + 1}.</span>
                      <span style={{ flex: 1, fontSize: 12, fontWeight: 600 }}>{a.app_name}</span>
                      <span className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{fmt(a.total_seconds)}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          <div className="card machine-calm-card analytics-card">
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 16 }}>Top 15 Applications</div>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => fmt(v)} />
                <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 11 }} />
                <Tooltip content={<TTip />} formatter={(v) => fmt(v)} />
                <Bar dataKey="secs" name="Time" fill="var(--brand)" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="card machine-calm-card analytics-card" style={{ padding: 0, overflow: 'hidden' }}>
            <table className="data-table">
              <thead><tr><th>#</th><th>Application</th><th>Process</th><th>Sessions</th><th>Total Time</th><th>Category</th><th>Share</th></tr></thead>
              <tbody>
                {filtered.map((a, i) => {
                  const pct = totalSecs > 0 ? ((a.total_seconds / totalSecs) * 100).toFixed(1) : 0
                  const cat = CAT_STYLE[a.category] || CAT_STYLE.neutral
                  return (
                    <tr key={a.app_name || i} onClick={() => setSelectedRow({ ...a, share: pct })} style={{ cursor: 'pointer' }}>
                      <td style={{ color: 'var(--text-3)', fontSize: 12 }}>{i + 1}</td>
                      <td className="mono" style={{ fontSize: 12, fontWeight: 600 }}>{a.app_name}</td>
                      <td style={{ fontSize: 11, color: 'var(--text-3)' }}>{a.process_name || '—'}</td>
                      <td style={{ fontSize: 12, color: 'var(--text-2)' }}>{a.sessions}</td>
                      <td className="mono" style={{ fontSize: 12, fontWeight: 700, color: 'var(--brand)' }}>{fmt(a.total_seconds)}</td>
                      <td>
                        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 100, background: cat.bg, color: cat.color }}>
                          {cat.label}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{ width: 60, height: 4, background: 'var(--bg-4)', borderRadius: 2, overflow: 'hidden' }}>
                            <div style={{ width: `${pct}%`, height: '100%', background: 'var(--brand)', borderRadius: 2 }} />
                          </div>
                          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{pct}%</span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </PageStateView>

      <ActivityDrawer
        open={Boolean(selectedRow)}
        title={selectedRow?.app_name || 'Application'}
        subtitle={selectedRow?.process_name || selectedRow?.window_title}
        badges={[
          { label: selectedRow?.category === 'productive' ? 'Productive' : 'Neutral' },
          { label: `${selectedRow?.sessions || 0} sessions` },
        ]}
        onClose={() => setSelectedRow(null)}
      >
        {selectedRow && (
          <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '10px 16px', fontSize: 13 }}>
            <DetailRow label="Application" value={selectedRow.app_name} />
            <DetailRow label="Process" value={selectedRow.process_name} />
            <DetailRow label="Window" value={selectedRow.window_title} />
            <DetailRow label="Sessions" value={selectedRow.sessions} />
            <DetailRow label="Total Time" value={fmt(selectedRow.total_seconds)} />
            <DetailRow label="Category" value={CAT_STYLE[selectedRow.category]?.label || 'Neutral'} />
            <DetailRow label="Share" value={`${selectedRow.share || 0}%`} />
          </div>
        )}
      </ActivityDrawer>
    </div>
  )
}
