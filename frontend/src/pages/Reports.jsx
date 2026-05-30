import { useState, useEffect } from 'react'
import { useApi } from '../hooks/useAuth'
import { ReportsIcon } from '../components/ui/OverviewIcons'

export default function Reports() {
  const { get } = useApi()
  const [machines, setMachines] = useState([])
  const [selId, setSelId] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [loading, setLoading] = useState(false)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    get('/api/machines').then((items) => {
      setMachines(items)
      if (items.length > 0) setSelId(items[0].machine_id)
    }).catch(() => {})
  }, [])

  const selectedMachine = machines.find((machine) => machine.machine_id === selId)

  const notify = (msg, type = 'green') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), type === 'red' ? 3500 : 3000)
  }

  const generate = async () => {
    if (!selId) {
      notify('Select a machine', 'red')
      return
    }

    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (start) params.set('start_date', start)
      if (end) params.set('end_date', end)
      const blob = await get(`/api/reports/generate/${selId}?${params}`)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `CropSentinel_Report_${new Date().toISOString().slice(0, 10)}.pdf`
      anchor.click()
      URL.revokeObjectURL(url)
      notify('Report downloaded')
    } catch (error) {
      notify(error.message, 'red')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fade-in control-shell">
      <div className="page-header machine-calm-header analytics-hero control-hero">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <ReportsIcon size={24} />
          </div>
          <div>
            <div className="page-title">Reports</div>
            <div className="page-subtitle">Generate a PDF summary for one machine and a chosen reporting window.</div>
          </div>
        </div>
      </div>

      <div className="grid-3">
        <div className="stat-card machine-calm-card machine-calm-stat control-stat">
          <div className="stat-label">Machines Available</div>
          <div className="stat-value" style={{ color: 'var(--brand)' }}>{machines.length}</div>
          <div className="stat-sub">Sources ready for export</div>
        </div>
        <div className="stat-card machine-calm-card machine-calm-stat control-stat">
          <div className="stat-label">Selected Machine</div>
          <div className="stat-value" style={{ color: 'var(--green)', fontSize: 24 }}>{selectedMachine?.hostname || 'None'}</div>
          <div className="stat-sub">{selectedMachine?.username || 'Choose a device to export'}</div>
        </div>
        <div className="stat-card machine-calm-card machine-calm-stat control-stat">
          <div className="stat-label">Date Range</div>
          <div className="stat-value" style={{ color: 'var(--amber)', fontSize: 24 }}>{start || end ? 'Custom' : 'All time'}</div>
          <div className="stat-sub">Blank dates export the full history</div>
        </div>
      </div>

      <div className="card machine-calm-card control-card" style={{ maxWidth: 760, display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div className="card-header" style={{ alignItems: 'flex-start' }}>
          <div>
            <div className="card-title">Report Builder</div>
            <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text-3)' }}>
              Select a machine, narrow the date range if needed, and download a PDF snapshot.
            </div>
          </div>
        </div>

        <div className="form-group">
          <label className="form-label">Machine</label>
          <select className="input-field machine-calm-search control-field" value={selId} onChange={(e) => setSelId(e.target.value)}>
            <option value="">Select machine...</option>
            {machines.map((machine) => (
              <option key={machine.machine_id} value={machine.machine_id}>
                {machine.hostname} | {machine.username || '-'}
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div className="form-group">
            <label className="form-label">Start Date</label>
            <input type="date" className="input-field machine-calm-search control-field" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">End Date</label>
            <input type="date" className="input-field machine-calm-search control-field" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
        </div>

        <div className="control-banner">
          The generated PDF includes application usage, browser activity, productivity score signals, and top destinations for the selected
          machine. Leave both dates blank to export the full available history.
        </div>

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <button className="btn btn-primary" onClick={generate} disabled={loading || !selId} style={{ padding: '10px 22px' }}>
            {loading ? <><span className="spinner" style={{ width: 13, height: 13 }} /> Generating...</> : 'Generate PDF report'}
          </button>
          {selectedMachine && (
            <span className="control-chip">
              Exporting for {selectedMachine.hostname}
            </span>
          )}
        </div>
      </div>

      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: 20,
            right: 20,
            zIndex: 9999,
            background: 'var(--bg-3)',
            border: `1px solid ${toast.type === 'red' ? 'rgba(239,68,68,.3)' : 'rgba(16,185,129,.3)'}`,
            color: toast.type === 'red' ? 'var(--red)' : 'var(--green)',
            padding: '11px 18px',
            borderRadius: 12,
            fontSize: 13,
            fontWeight: 500,
            boxShadow: 'var(--shadow-lg)',
          }}
        >
          {toast.msg}
        </div>
      )}
    </div>
  )
}
