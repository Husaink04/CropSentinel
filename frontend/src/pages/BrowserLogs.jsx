import { useMemo, useState } from 'react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { exportCsv } from '../utils/csv'
import { useActivityFeed, useActivityMachines } from '../features/activity/activityShared'
import { ActivityDrawer, ActivityToolbar } from '../features/activity/activityUi'
import { PageStateView } from '../components/ui/PageState'
import { DomainIcon } from '../components/ui/OverviewIcons'

const fmt = (s) => { if (!s) return '0m'; const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60); return h ? `${h}h ${m}m` : `${m}m` }
const fmtTs = (ts) => (ts ? new Date(ts).toLocaleString() : '—')

const CAT_STYLE = {
  productive:   { color: 'var(--green)', bg: 'var(--green-dim)', label: 'Productive' },
  unproductive: { color: 'var(--red)', bg: 'var(--red-dim)', label: 'Unproductive' },
  neutral:      { color: 'var(--text-3)', bg: 'var(--bg-4)', label: 'Neutral' },
}

const DONUT_COLORS = { productive: '#0FC97D', unproductive: '#F04343', neutral: '#64748B' }
const PALETTE = ['#3B7BF8', '#0FC97D', '#F5A623', '#F04343', '#8B5CF6', '#22D3EE', '#EC4899', '#84CC16']

const todayStr = () => new Date().toISOString().slice(0, 10)

function TTip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0]
  return (
    <div className="chart-tooltip">
      <div style={{ color: d.payload?.fill || 'var(--text-1)', fontWeight: 600, fontSize: 12 }}>
        {d.name}: {d.value}
      </div>
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

export default function BrowserLogs() {
  const { machines, selectedId: selId, setSelectedId: setSelId } = useActivityMachines({ defaultMode: 'first' })
  const [search, setSearch] = useState('')
  const [date, setDate] = useState(todayStr)
  const [catFilter, setCatFilter] = useState('')
  const [selectedRow, setSelectedRow] = useState(null)

  const { items: logs, loading, refreshing, error, uiState, refresh } = useActivityFeed({
    endpoint: '/api/activity/browser-logs',
    params: { machine_id: selId, search, date, limit: 200, offset: 0 },
    realtimeTypes: ['browser_update'],
    enabled: Boolean(selId),
  })

  const filtered = catFilter ? logs.filter((l) => l.category === catFilter) : logs

  const visitDonut = useMemo(() => {
    const counts = { productive: 0, unproductive: 0, neutral: 0 }
    logs.forEach((l) => { counts[l.category || 'neutral'] += 1 })
    return [
      { name: 'Productive', value: counts.productive, fill: DONUT_COLORS.productive },
      { name: 'Unproductive', value: counts.unproductive, fill: DONUT_COLORS.unproductive },
      { name: 'Neutral', value: counts.neutral, fill: DONUT_COLORS.neutral },
    ].filter((item) => item.value > 0)
  }, [logs])

  const topDomainsData = useMemo(() => {
    const map = {}
    logs.forEach((l) => {
      const d = (l.domain || 'unknown').replace('www.', '')
      map[d] = (map[d] || 0) + 1
    })
    return Object.entries(map)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([name, value]) => ({ name, value }))
  }, [logs])

  const topByCategory = useMemo(() => {
    const map = {}
    logs.forEach((l) => {
      const d = l.domain || 'unknown'
      const c = l.category || 'neutral'
      const key = `${c}::${d}`
      if (!map[key]) map[key] = { domain: d, category: c, count: 0, secs: 0 }
      map[key].count += 1
      map[key].secs += (l.duration_seconds || 0)
    })
    const all = Object.values(map)
    return {
      productive: all.filter((d) => d.category === 'productive').sort((a, b) => b.count - a.count).slice(0, 5),
      unproductive: all.filter((d) => d.category === 'unproductive').sort((a, b) => b.count - a.count).slice(0, 5),
    }
  }, [logs])

  const canClear = Boolean(selId || search || date !== todayStr() || catFilter)

  return (
    <div className="fade-in analytics-shell">
      <div className="page-header machine-calm-header analytics-hero">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <DomainIcon size={24} />
          </div>
          <div>
            <div className="page-title">Browser Logs</div>
            <div className="page-subtitle">Unified browsing view with machine filters, categories, and row-level detail.</div>
          </div>
        </div>
      </div>

      <ActivityToolbar
        machines={machines}
        selectedId={selId}
        onMachineChange={setSelId}
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="Search URL, title, domain..."
        date={date}
        onDateChange={setDate}
        extraFilters={(
          <select className="input-field" style={{ maxWidth: 150, fontSize: 12 }} value={catFilter} onChange={(e) => setCatFilter(e.target.value)}>
            <option value="">All categories</option>
            <option value="productive">Productive</option>
            <option value="unproductive">Unproductive</option>
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
              onClick={() => exportCsv(`browser_logs_${selId || 'all'}.csv`, filtered, [
                { key: 'timestamp', label: 'Timestamp' },
                { key: 'browser', label: 'Browser' },
                { key: 'domain', label: 'Domain' },
                { key: 'url', label: 'URL' },
                { key: 'title', label: 'Title' },
                { key: 'duration_seconds', label: 'Duration (s)' },
                { key: 'category', label: 'Category' },
              ])}
            >
              CSV
            </button>
          </>
        )}
        onClear={() => { setSelId(''); setSearch(''); setDate(todayStr()); setCatFilter('') }}
        clearable={canClear}
      />

      {error && (
        <div style={{ marginBottom: 16 }}>
          <div className="ui-inline-banner ui-inline-banner-warning" role="status">
            <div className="ui-inline-banner-copy">
              <strong>Partial data</strong>
              <span>Browser logs are showing cached data because the latest fetch failed.</span>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => refresh()}>Retry</button>
          </div>
        </div>
      )}

      <PageStateView
        state={uiState}
        title="No browser history"
        message="Select a machine and date range."
        onRetry={refresh}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="grid-2">
            <div className="card machine-calm-card analytics-card">
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>Visits by Category</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <ResponsiveContainer width="50%" height={170}>
                  <PieChart>
                    <Pie data={visitDonut} cx="50%" cy="50%" innerRadius={40} outerRadius={65} dataKey="value" stroke="none" paddingAngle={3}>
                      {visitDonut.map((d, i) => <Cell key={i} fill={d.fill} />)}
                    </Pie>
                    <Tooltip content={<TTip />} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {visitDonut.map((d, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                      <span style={{ width: 10, height: 10, borderRadius: 2, background: d.fill, flexShrink: 0 }} />
                      <span style={{ flex: 1, color: 'var(--text-2)' }}>{d.name}</span>
                      <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>{d.value} visits</span>
                    </div>
                  ))}
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>
                    {logs.length} total visits
                  </div>
                </div>
              </div>
            </div>

            <div className="card machine-calm-card analytics-card">
              <div className="card-header">
                <span style={{ fontSize: 14, fontWeight: 700 }}>Top Domains</span>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>visits</span>
              </div>
              {topDomainsData.length === 0
                ? <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-3)', fontSize: 13 }}>No data</div>
                : (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <ResponsiveContainer width="50%" height={200}>
                      <PieChart>
                        <Pie data={topDomainsData} cx="50%" cy="50%" innerRadius={48} outerRadius={78} dataKey="value" stroke="none" paddingAngle={2}>
                          {topDomainsData.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                        </Pie>
                        <Tooltip content={<TTip />} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {topDomainsData.map((d, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                          <span style={{ width: 8, height: 8, borderRadius: 2, background: PALETTE[i % PALETTE.length], flexShrink: 0 }} />
                          <span className="truncate" style={{ flex: 1, color: 'var(--text-2)' }}>{d.name}</span>
                          <span className="mono" style={{ color: 'var(--text-3)', fontSize: 11 }}>{d.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
            </div>
          </div>

          {(topByCategory.productive.length > 0 || topByCategory.unproductive.length > 0) && (
            <div className="grid-2">
              <div className="card machine-calm-card analytics-card">
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: '#0FC97D' }}>Top Productive Domains</div>
                {topByCategory.productive.length === 0
                  ? <div style={{ fontSize: 12, color: 'var(--text-3)' }}>None matched</div>
                  : topByCategory.productive.map((d, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span style={{ width: 18, fontSize: 11, color: 'var(--text-3)', textAlign: 'right' }}>{i + 1}.</span>
                      <span className="mono" style={{ flex: 1, fontSize: 12, fontWeight: 600 }}>{d.domain}</span>
                      <span className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{d.count} visits</span>
                    </div>
                  ))}
              </div>
              <div className="card machine-calm-card analytics-card">
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: '#F04343' }}>Top Unproductive Domains</div>
                {topByCategory.unproductive.length === 0
                  ? <div style={{ fontSize: 12, color: 'var(--text-3)' }}>None matched</div>
                  : topByCategory.unproductive.map((d, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span style={{ width: 18, fontSize: 11, color: 'var(--text-3)', textAlign: 'right' }}>{i + 1}.</span>
                      <span className="mono" style={{ flex: 1, fontSize: 12, fontWeight: 600 }}>{d.domain}</span>
                      <span className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{d.count} visits</span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          <div className="card machine-calm-card analytics-card" style={{ padding: 0, overflow: 'hidden' }}>
            <table className="data-table">
              <thead><tr><th>Time</th><th>Browser</th><th>Domain</th><th>Title</th><th>Duration</th><th>Category</th></tr></thead>
              <tbody>
                {filtered.map((l) => {
                  const cat = CAT_STYLE[l.category] || CAT_STYLE.neutral
                  return (
                    <tr key={l.id || `${l.timestamp}-${l.url}`} onClick={() => setSelectedRow(l)} style={{ cursor: 'pointer' }}>
                      <td className="mono" style={{ fontSize: 11, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{fmtTs(l.timestamp)}</td>
                      <td style={{ fontSize: 11 }}><span className="badge badge-gray">{l.browser || '—'}</span></td>
                      <td className="mono" style={{ fontSize: 12, color: 'var(--brand)' }}>{l.domain || '—'}</td>
                      <td style={{ fontSize: 12, color: 'var(--text-2)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <a href={l.url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }} onClick={(e) => e.stopPropagation()} title={l.url}>
                          {l.title || l.url || '—'}
                        </a>
                      </td>
                      <td className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{fmt(l.duration_seconds)}</td>
                      <td>
                        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 100, background: cat.bg, color: cat.color }}>
                          {cat.label}
                        </span>
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
        title={selectedRow?.title || selectedRow?.domain || 'Browser visit'}
        subtitle={selectedRow?.url || selectedRow?.domain}
        badges={[
          { label: selectedRow?.browser || 'Browser' },
          { label: CAT_STYLE[selectedRow?.category]?.label || 'Neutral' },
        ]}
        onClose={() => setSelectedRow(null)}
        footer={selectedRow?.url ? (
          <a className="btn btn-primary btn-sm" href={selectedRow.url} target="_blank" rel="noopener noreferrer">
            Open URL
          </a>
        ) : null}
      >
        {selectedRow && (
          <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '10px 16px', fontSize: 13 }}>
            <DetailRow label="Time" value={fmtTs(selectedRow.timestamp)} />
            <DetailRow label="Domain" value={selectedRow.domain} />
            <DetailRow label="URL" value={selectedRow.url} />
            <DetailRow label="Title" value={selectedRow.title} />
            <DetailRow label="Duration" value={fmt(selectedRow.duration_seconds)} />
            <DetailRow label="Category" value={CAT_STYLE[selectedRow.category]?.label || 'Neutral'} />
            <DetailRow label="Browser" value={selectedRow.browser} />
          </div>
        )}
      </ActivityDrawer>
    </div>
  )
}
