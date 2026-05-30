import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useApi } from '../hooks/useAuth'

const fmtDuration = (s) => {
  const v = Number(s || 0)
  const h = Math.floor(v / 3600)
  const m = Math.floor((v % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

const scoreColor = (value) => (
  value >= 75 ? 'var(--success)' : value >= 50 ? 'var(--warning)' : 'var(--danger)'
)

function TTip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map((item, index) => (
        <div key={index} style={{ color: item.color || item.fill, fontWeight: 600, fontSize: 12 }}>
          {item.name}: {typeof item.value === 'number' ? Math.round(item.value) : item.value}
        </div>
      ))}
    </div>
  )
}

export default function MachineProductivity() {
  const { machineId } = useParams()
  const { get } = useApi()
  const navigate = useNavigate()

  const [data, setData] = useState(null)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const query = useMemo(() => {
    const params = new URLSearchParams()
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    return params.toString()
  }, [startDate, endDate])

  useEffect(() => {
    setLoading(true)
    setError('')
    const qs = query ? `?${query}` : ''
    get(`/api/productivity/machines/${machineId}${qs}`)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [get, machineId, query])

  if (loading) {
    return <div className="loading-center"><div className="spinner" style={{ width: 30, height: 30 }} /></div>
  }
  if (error) {
    return <div className="loading-center" style={{ color: 'var(--red)' }}>{error}</div>
  }
  if (!data) {
    return <div className="loading-center">No productivity data found</div>
  }

  const summary = data.summary || {}
  const components = data.score_components || {}
  const breakdown = data.classification_breakdown || []
  const hourly = (data.hourly_distribution || []).map((row) => ({
    hour: `${row.hour}:00`,
    productive: Math.round((row.productive || 0) / 60),
    supportive: Math.round((row.supportive || 0) / 60),
    distracting: Math.round((row.distracting || 0) / 60),
    neutral: Math.round((row.neutral || 0) / 60),
  }))
  const score = Number(summary.productivity_score || 0)
  const confidence = Number(summary.score_confidence || 0)
  const gaugeBg = `conic-gradient(${scoreColor(score)} ${score * 3.6}deg, var(--bg-4) 0deg)`

  return (
    <div className="fade-in">
      <div style={{ marginBottom: 14 }}>
        <button
          onClick={() => navigate(-1)}
          style={{ background: 'none', border: 'none', color: 'var(--text-3)', cursor: 'pointer', padding: 0 }}
        >
          Back
        </button>
      </div>

      <div className="page-header">
        <div>
          <div className="page-title">{summary.hostname || machineId}</div>
          <div className="page-subtitle">{summary.username || 'Unknown user'} · {machineId}</div>
        </div>
        <div className="page-actions" style={{ display: 'flex', gap: 8 }}>
          <input type="date" className="input-field" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          <input type="date" className="input-field" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </div>
      </div>

      {confidence < 60 && (
        <div className="card" style={{ marginBottom: 14, border: '1px solid rgba(245,166,35,.25)', color: 'var(--warning)' }}>
          Score confidence is reduced because rule coverage or telemetry depth is limited for this time window.
        </div>
      )}

      <div className="grid-2" style={{ marginBottom: 14 }}>
        <div className="card" style={{ display: 'grid', placeItems: 'center', minHeight: 260 }}>
          <div style={{ display: 'grid', placeItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 180,
                height: 180,
                borderRadius: 180,
                background: gaugeBg,
                display: 'grid',
                placeItems: 'center',
              }}
            >
              <div
                style={{
                  width: 130,
                  height: 130,
                  borderRadius: 130,
                  background: 'var(--bg-2)',
                  display: 'grid',
                  placeItems: 'center',
                }}
              >
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 38, fontWeight: 800 }}>{score}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-3)' }}>{confidence}% confidence</div>
                </div>
              </div>
            </div>
            <div style={{ fontWeight: 700 }}>Productivity Score</div>
          </div>
        </div>

        <div className="card">
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Breakdown</div>
          <div style={{ display: 'grid', gap: 8, fontSize: 13 }}>
            {[
              ['Active Time', summary.active_time_seconds],
              ['Idle Time', summary.idle_time_seconds],
              ['Focus Time', summary.focus_time_seconds],
              ['Productive', components.productive_time_seconds],
              ['Supportive', components.supportive_time_seconds],
              ['Distracting', components.distracting_time_seconds],
            ].map(([label, value]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>{label}</span>
                <strong>{fmtDuration(value)}</strong>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid-2" style={{ marginBottom: 14 }}>
        <div className="card">
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Findings</div>
          {!data.findings?.length ? (
            <div style={{ color: 'var(--text-3)' }}>No findings in this window</div>
          ) : (
            <div style={{ display: 'grid', gap: 10 }}>
              {data.findings.map((finding, idx) => (
                <div key={idx} style={{ border: '1px solid var(--border)', borderRadius: 12, padding: 12 }}>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{finding.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>{finding.description}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Trend</div>
          <div style={{ display: 'grid', gap: 8, fontSize: 13 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Direction</span>
              <strong>{data.trend?.direction || 'flat'}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Score Delta</span>
              <strong>{data.trend?.score_delta || 0}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Focus Delta</span>
              <strong>{fmtDuration(data.trend?.focus_delta_seconds || 0)}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Workload Intensity</span>
              <strong>{summary.workload_intensity_score || 0}</strong>
            </div>
          </div>
        </div>
      </div>

      <div className="grid-2" style={{ marginBottom: 14 }}>
        <div className="card">
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Top Applications</div>
          {(data.top_apps || []).length === 0 ? (
            <div className="empty-state" style={{ minHeight: 120 }}>
              <div className="empty-state-title">No app usage in selected range</div>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Application</th>
                  <th>Category</th>
                  <th>Usage</th>
                </tr>
              </thead>
              <tbody>
                {data.top_apps.map((app) => (
                  <tr key={app.app_name}>
                    <td>{app.app_name || 'Unknown'}</td>
                    <td>{app.category}</td>
                    <td>{fmtDuration(app.total_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Top Domains</div>
          {(data.top_domains || []).length === 0 ? (
            <div className="empty-state" style={{ minHeight: 120 }}>
              <div className="empty-state-title">No browser activity in selected range</div>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Category</th>
                  <th>Usage</th>
                </tr>
              </thead>
              <tbody>
                {data.top_domains.map((domain) => (
                  <tr key={domain.domain}>
                    <td>{domain.domain || 'Unknown'}</td>
                    <td>{domain.category}</td>
                    <td>{fmtDuration(domain.total_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Hourly Activity</div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={hourly} margin={{ top: 4, right: 8, bottom: 4, left: -18 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="hour" tick={{ fontSize: 9 }} interval={3} />
              <YAxis tick={{ fontSize: 9 }} unit="m" />
              <Tooltip content={<TTip />} />
              <Bar dataKey="productive" stackId="a" fill="var(--success)" name="Productive" />
              <Bar dataKey="supportive" stackId="a" fill="var(--brand)" name="Supportive" />
              <Bar dataKey="neutral" stackId="a" fill="var(--text-3)" name="Neutral" />
              <Bar dataKey="distracting" stackId="a" fill="var(--danger)" name="Distracting" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Rule Coverage</div>
          <div style={{ display: 'grid', gap: 10 }}>
            {breakdown.map((item) => (
              <div key={item.category} style={{ display: 'grid', gap: 4 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                  <span style={{ textTransform: 'capitalize' }}>{item.category}</span>
                  <span>{Math.round((item.share || 0) * 100)}% · {fmtDuration(item.seconds)}</span>
                </div>
                <div style={{ height: 6, background: 'var(--border-0)', borderRadius: 999 }}>
                  <div
                    style={{
                      width: `${Math.round((item.share || 0) * 100)}%`,
                      height: '100%',
                      background: item.category === 'productive' ? 'var(--success)' : item.category === 'supportive' ? 'var(--brand)' : item.category === 'distracting' ? 'var(--danger)' : 'var(--text-3)',
                      borderRadius: 999,
                    }}
                  />
                </div>
              </div>
            ))}
            <div style={{ fontSize: 12, color: 'var(--text-3)' }}>
              Policy version {data.meta?.policy_version || 1} · {data.meta?.window_seconds || 0} second window
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
