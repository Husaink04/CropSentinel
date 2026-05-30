/**
 * CropSentinel — Per-machine Activity Timeline
 * ════════════════════════════════════════════
 * Ops wanted a scrollable chronological view of a single machine's day —
 * not just the bar-chart totals the Overview tab shows. This component
 * fetches every per-event feed we have for the selected date and merges
 * them into a single timeline ordered newest-first.
 *
 * Data sources (all existing backend endpoints):
 *   • GET /api/analytics/browser/{machineId}?date=YYYY-MM-DD&limit=500
 *   • GET /api/screenshots/{machineId}?date=YYYY-MM-DD&limit=200
 *   • GET /api/files?machine_id=…&date=YYYY-MM-DD&limit=500
 *   • GET /api/network?machine_id=…&date=YYYY-MM-DD&limit=200
 *   • GET /api/dlp/events?machine_id=…&date_from=…&date_to=…&limit=200
 *
 * App usage is deliberately excluded — that endpoint aggregates per-app
 * totals with no per-session timestamps, so it wouldn't make sense on a
 * minute-by-minute chronological view.
 *
 * The date picker defaults to today; arrow buttons step ±1 day. A toggle
 * row lets the user hide any source without re-fetching. An empty day
 * shows a friendly empty state instead of a blank view.
 */

import { useState, useEffect, useMemo } from 'react'
import { useApi } from '../hooks/useAuth'

const todayISO = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const shiftDay = (iso, delta) => {
  const d = new Date(iso + 'T12:00:00')
  d.setDate(d.getDate() + delta)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const fmtTime = (ts) => {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// Group timeline entries by hour-of-day so the view scans fast.
function groupByHour(entries) {
  const map = new Map()
  for (const e of entries) {
    const d = new Date(e.ts)
    const hour = d.getHours()
    if (!map.has(hour)) map.set(hour, [])
    map.get(hour).push(e)
  }
  // Newest hour first.
  return [...map.entries()].sort((a, b) => b[0] - a[0])
}

// Every source the timeline can render. Keys double as toggle IDs and
// as entry `kind` values. Keep order stable — controls the filter-chip
// row order below.
const SOURCES = [
  { key: 'browser',    label: 'Browser'     },
  { key: 'screenshot', label: 'Screenshots' },
  { key: 'file',       label: 'Files'       },
  { key: 'network',    label: 'Network'     },
  { key: 'dlp',        label: 'DLP'         },
]

export default function ActivityTimeline({ machineId }) {
  const { get } = useApi()
  const [date, setDate] = useState(todayISO())
  const [browser, setBrowser] = useState([])
  const [shots, setShots]     = useState([])
  const [files, setFiles]     = useState([])
  const [network, setNetwork] = useState([])
  const [dlp, setDlp]         = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')
  // Source visibility — all on by default. Per-date-range, not per-source
  // (we always fetch everything so toggles feel instant).
  const [enabled, setEnabled] = useState(
    () => Object.fromEntries(SOURCES.map(s => [s.key, true]))
  )

  useEffect(() => {
    if (!machineId) return
    let cancelled = false
    setLoading(true); setError('')
    // DLP takes date_from/date_to instead of a single date.
    const nextISO = shiftDay(date, 1)
    Promise.allSettled([
      get(`/api/analytics/browser/${machineId}?date=${date}&limit=500`),
      get(`/api/screenshots/${machineId}?date=${date}&limit=200`),
      get(`/api/files?machine_id=${machineId}&date=${date}&limit=500`),
      get(`/api/network?machine_id=${machineId}&date=${date}&limit=200`),
      get(`/api/dlp/events?machine_id=${machineId}&date_from=${date}&date_to=${nextISO}&limit=200`),
    ]).then(([b, s, f, n, d]) => {
      if (cancelled) return
      setBrowser(b.status === 'fulfilled' && Array.isArray(b.value) ? b.value : [])
      setShots  (s.status === 'fulfilled' && Array.isArray(s.value) ? s.value : [])
      // /api/files and /api/network return { files|logs, total } wrappers.
      setFiles  (f.status === 'fulfilled' ? (f.value?.files || []) : [])
      setNetwork(n.status === 'fulfilled' ? (n.value?.logs  || []) : [])
      setDlp    (d.status === 'fulfilled' ? (d.value?.events || []) : [])
      const allFailed = [b, s, f, n, d].every(r => r.status === 'rejected')
      if (allFailed) setError('Failed to load timeline')
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [machineId, date, get])

  // Merge every feed into a common shape, newest first. Each entry is
  // tagged with `kind` so TimelineRow can pick a dot colour + chip label
  // and so the source filter can hide it.
  const entries = useMemo(() => {
    const items = []
    for (const b of browser) {
      if (!b.timestamp) continue
      items.push({
        id: `b_${b.id || b.timestamp}_${b.url || ''}`,
        ts: b.timestamp,
        kind: 'browser',
        title: b.title || b.domain || b.url || 'Visit',
        subtitle: b.url || b.domain || '',
        category: b.category || 'neutral',
      })
    }
    for (const s of shots) {
      if (!s.timestamp) continue
      items.push({
        id: `s_${s.id || s.timestamp}`,
        ts: s.timestamp,
        kind: 'screenshot',
        title: s.trigger ? `Screenshot · ${s.trigger}` : 'Screenshot',
        subtitle: s.app_name || '',
        trigger: s.trigger,
      })
    }
    for (const f of files) {
      if (!f.timestamp) continue
      const action = f.action || 'event'
      items.push({
        id: `f_${f.id || f.timestamp}_${f.file_path || ''}`,
        ts: f.timestamp,
        kind: 'file',
        action,
        title: `File ${action} · ${f.file_name || f.file_path || '—'}`,
        subtitle: f.file_path || '',
      })
    }
    for (const n of network) {
      if (!n.timestamp) continue
      items.push({
        id: `n_${n.id || n.timestamp}`,
        ts: n.timestamp,
        kind: 'network',
        title: `Network snapshot · ${n.listen_count || 0} ports · ${n.conn_count || 0} conns`,
        subtitle: n.hostname || '',
      })
    }
    for (const e of dlp) {
      if (!e.timestamp) continue
      items.push({
        id: `d_${e.id || e.timestamp}_${e.file_path || ''}`,
        ts: e.timestamp,
        kind: 'dlp',
        risk: (e.risk_level || e.risk || '').toLowerCase(),
        title: `DLP · ${(e.action_type || 'event').replace(/_/g, ' ')} · ${e.file_name || e.file_path || '—'}`,
        subtitle: e.file_path || '',
      })
    }
    const filtered = items.filter(i => enabled[i.kind])
    return filtered.sort((a, b) => new Date(b.ts) - new Date(a.ts))
  }, [browser, shots, files, network, dlp, enabled])

  const grouped = useMemo(() => groupByHour(entries), [entries])
  const isToday = date === todayISO()

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>

      {/* Header: date nav */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 12, padding: '12px 16px', borderBottom: '1px solid var(--border)',
        flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setDate(d => shiftDay(d, -1))}
            aria-label="Previous day"
          >‹</button>
          <input
            type="date"
            className="input-field"
            value={date}
            max={todayISO()}
            onChange={e => setDate(e.target.value || todayISO())}
            style={{ padding: '6px 10px', fontSize: 13, width: 'auto' }}
          />
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setDate(d => shiftDay(d, 1))}
            disabled={isToday}
            aria-label="Next day"
          >›</button>
          {!isToday && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setDate(todayISO())}
            >Today</button>
          )}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-3)' }}>
          {entries.length} event{entries.length !== 1 ? 's' : ''}
          {' · '}
          {browser.length} page{browser.length !== 1 ? 's' : ''}
          {' · '}
          {shots.length} screenshot{shots.length !== 1 ? 's' : ''}
          {' · '}
          {files.length} file{files.length !== 1 ? 's' : ''}
          {' · '}
          {network.length} net
          {' · '}
          {dlp.length} DLP
        </div>
      </div>

      {/* Source filter chips — click to hide/show a feed without re-fetching. */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: 6,
        padding: '8px 16px', borderBottom: '1px solid var(--border)',
      }}>
        {SOURCES.map(s => {
          const on = enabled[s.key]
          const count =
            s.key === 'browser'    ? browser.length :
            s.key === 'screenshot' ? shots.length   :
            s.key === 'file'       ? files.length   :
            s.key === 'network'    ? network.length :
            /* dlp */                dlp.length
          return (
            <button
              key={s.key}
              onClick={() => setEnabled(e => ({ ...e, [s.key]: !e[s.key] }))}
              style={{
                fontSize: 11, padding: '4px 10px', borderRadius: 999,
                border: '1px solid var(--border)',
                background: on ? 'var(--brand-dim)' : 'transparent',
                color: on ? 'var(--brand)' : 'var(--text-3)',
                cursor: 'pointer', fontWeight: 600,
              }}
              aria-pressed={on}
            >
              {s.label} <span style={{ opacity: 0.6, marginLeft: 4 }}>{count}</span>
            </button>
          )
        })}
      </div>

      {/* Body */}
      {loading ? (
        <div className="loading-center" style={{ padding: 40 }}>
          <div className="spinner" style={{ width: 22, height: 22 }} />
        </div>
      ) : error ? (
        <div className="empty-state" style={{ padding: 40 }}>
          <div className="empty-state-title">{error}</div>
        </div>
      ) : entries.length === 0 ? (
        <div className="empty-state" style={{ padding: 40 }}>
          <div className="empty-state-icon">○</div>
          <div className="empty-state-title">No activity on this day</div>
          <div className="empty-state-sub">Try a different date or check if the agent was running.</div>
        </div>
      ) : (
        <div style={{ maxHeight: 520, overflowY: 'auto' }}>
          {grouped.map(([hour, items]) => (
            <div key={hour}>
              <div style={{
                position: 'sticky', top: 0, zIndex: 1,
                padding: '6px 16px', fontSize: 11, fontWeight: 700,
                textTransform: 'uppercase', letterSpacing: '0.06em',
                color: 'var(--text-3)', background: 'var(--bg-2, rgba(15,23,42,0.85))',
                borderBottom: '1px solid var(--border)',
                backdropFilter: 'blur(8px)',
              }}>
                {String(hour).padStart(2, '0')}:00 — {String(hour + 1).padStart(2, '0')}:00
                <span style={{ marginLeft: 8, color: 'var(--text-3)', fontWeight: 500 }}>
                  ({items.length})
                </span>
              </div>
              {items.map(e => <TimelineRow key={e.id} entry={e} />)}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── One timeline entry ───────────────────────────────────────────────────────
function TimelineRow({ entry }) {
  let dot = 'var(--brand)'
  if (entry.kind === 'screenshot') dot = 'var(--amber)'
  else if (entry.kind === 'browser') {
    dot = entry.category === 'productive'   ? 'var(--green)'
        : entry.category === 'unproductive' ? 'var(--red)'
        : 'var(--brand)'
  }
  else if (entry.kind === 'file') {
    dot = entry.action === 'delete' ? 'var(--red)'
        : entry.action === 'create' ? 'var(--green)'
        : entry.action === 'modify' ? 'var(--amber)'
        : 'var(--brand)'
  }
  else if (entry.kind === 'network') dot = 'var(--purple, #8B5CF6)'
  else if (entry.kind === 'dlp')     dot = entry.risk === 'high' || entry.risk === 'critical'
                                            ? 'var(--red)' : 'var(--amber)'
  const kindStyle = { dot }

  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 12,
      padding: '10px 16px',
      borderBottom: '1px solid var(--border)',
    }}>
      <div style={{
        fontFamily: 'JetBrains Mono, monospace',
        fontSize: 11, color: 'var(--text-3)', width: 64, flexShrink: 0, paddingTop: 2,
      }}>
        {fmtTime(entry.ts)}
      </div>
      <div style={{
        width: 8, height: 8, borderRadius: '50%', background: kindStyle.dot,
        flexShrink: 0, marginTop: 7,
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13, color: 'var(--text-1)', fontWeight: 500,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }} title={entry.title}>
          {entry.title}
        </div>
        {entry.subtitle && (
          <div style={{
            fontSize: 11, color: 'var(--text-3)', marginTop: 2,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }} title={entry.subtitle}>
            {entry.subtitle}
          </div>
        )}
      </div>
    </div>
  )
}
