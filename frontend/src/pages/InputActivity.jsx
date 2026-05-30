import { useState, useEffect } from 'react'
import { useApi } from '../hooks/useAuth'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { InputIcon } from '../components/ui/OverviewIcons'

function TTip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.fill, fontWeight: 600, fontSize: 12, marginTop: 2 }}>{p.name}: {p.value}</div>
      ))}
    </div>
  )
}

export default function InputActivity() {
  const { get } = useApi()
  const [machines, setMachines] = useState([])
  const [selId, setSelId] = useState('')
  const [rows, setRows] = useState([])
  const [date, setDate] = useState('')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    get('/api/machines').then(ms => {
      setMachines(ms)
      if (ms.length > 0) setSelId(ms[0].machine_id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selId) return
    setLoading(true)
    const q = new URLSearchParams()
    if (date) q.set('date', date)
    if (search.trim()) q.set('search', search.trim())
    const qs = q.toString()
    get(`/api/analytics/input/${selId}${qs ? `?${qs}` : ''}`)
      .then(setRows)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [selId, date, search])

  const chartData = rows.slice(0, 20).map((r, i) => ({
    name: `#${rows.length - i}`,
    keys: r.key_event_count || 0,
    clicks: r.mouse_click_count || 0,
  }))
  const totalKeys = rows.reduce((s, r) => s + (r.key_event_count || 0), 0)

  return (
    <div className="fade-in analytics-shell">
      <div className="page-header machine-calm-header analytics-hero">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <InputIcon size={24} />
          </div>
          <div>
            <div className="page-title">Input Activity</div>
            <div className="page-subtitle">Keyboard and mouse activity buckets with process and window context.</div>
          </div>
        </div>
      </div>

      <div className="analytics-note" style={{ marginBottom: 16, fontSize: 12 }}>
        <strong>Tier B (Windows & macOS):</strong> the agent records keycode n-gram fingerprints, counts, and foreground window context,
        but not readable keystroke text. macOS requires Accessibility permission for input capture, and employees should be notified under
        your monitoring policy.
      </div>

      <div className="filter-bar analytics-filter-panel machine-calm-card" style={{ marginBottom: 20, flexWrap: 'wrap', gap: 10 }}>
        <select className="input-field machine-calm-search" style={{ maxWidth: 220, fontSize: 12 }} value={selId} onChange={e => setSelId(e.target.value)}>
          {machines.map(m => <option key={m.machine_id} value={m.machine_id}>{m.hostname}</option>)}
        </select>
        <input type="date" className="input-field machine-calm-search" style={{ maxWidth: 160, fontSize: 12 }} value={date} onChange={e => setDate(e.target.value)} />
        <input type="search" className="input-field machine-calm-search" style={{ maxWidth: 200, fontSize: 12 }} placeholder="Filter process or title..." value={search} onChange={e => setSearch(e.target.value)} />
        {date && <button type="button" className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setDate('')}>Clear date</button>}
      </div>

      {loading ? (
        <div className="loading-center"><div className="spinner" style={{ width: 24, height: 24 }} /></div>
      ) : rows.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon"><InputIcon size={28} /></div>
          <div className="empty-state-title">No input buckets</div>
          <div className="empty-state-sub">Enable tracking in Settings and choose a machine with an online Windows or macOS agent.</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="card machine-calm-card analytics-card">
            <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 4 }}>Key events (visible rows)</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--brand)', fontFamily: 'JetBrains Mono, monospace' }}>{totalKeys}</div>
          </div>
          <div className="card machine-calm-card analytics-card">
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 16 }}>Recent buckets (keys vs clicks)</div>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={chartData} margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip content={<TTip />} />
                <Bar dataKey="keys" name="Key events" fill="var(--brand)" radius={[3, 3, 0, 0]} />
                <Bar dataKey="clicks" name="Mouse clicks" fill="var(--success)" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="card machine-calm-card analytics-card" style={{ padding: 0, overflow: 'hidden' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>End (UTC)</th>
                  <th>Process</th>
                  <th>Window</th>
                  <th>Keys</th>
                  <th>Clicks</th>
                  <th>Scrolls</th>
                  <th>N-gram hashes</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.id}>
                    <td className="mono" style={{ fontSize: 11 }}>{r.bucket_end?.slice(0, 19) || r.timestamp?.slice(0, 19) || '-'}</td>
                    <td style={{ fontSize: 12, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.process_name}>{r.process_name || '-'}</td>
                    <td style={{ fontSize: 11, color: 'var(--text-3)', maxWidth: 220 }} title={r.window_title}>{(r.window_title || '-').slice(0, 48)}</td>
                    <td className="mono" style={{ fontSize: 12 }}>{r.key_event_count ?? 0}</td>
                    <td className="mono" style={{ fontSize: 12 }}>{r.mouse_click_count ?? 0}</td>
                    <td className="mono" style={{ fontSize: 12 }}>{r.mouse_scroll_count ?? 0}</td>
                    <td className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{Array.isArray(r.pattern_hashes) ? r.pattern_hashes.length : 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
