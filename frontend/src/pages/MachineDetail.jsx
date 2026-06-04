import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useApi, useWsContext, useWsListener } from '../hooks/useAuth'
import { useIceServers } from '../hooks/useIceServers'
import { SESSION_MODES, useWebRtcSession } from '../features/sessions/sessionShared'
import { RealtimeStatusBanner } from '../components/ui/RealtimeStatusBanner'
import { exportCsv } from '../utils/csv'
import {
  AppIcon,
  AverageHoursIcon,
  ChartBarIcon,
  ChartPieIcon,
  DomainIcon,
  MachinesIcon,
  NetworkIcon,
  TimeIcon,
  ChartLineIcon,
} from '../components/ui/OverviewIcons'
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'

const fmt = (s) => {
  if (!s) return '0m'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h ? `${h}h ${m}m` : `${m}m`
}

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

const fmtTs = (ts) => (ts ? new Date(ts).toLocaleString() : '--')
const calmChartColors = ['#5c8a92', '#7aa39b', '#b6926c', '#8b95b5', '#6b8bb6', '#8ba79a']
const fmtCount = (value) => Number(value || 0).toLocaleString()
const fmtPct = (value) => `${Math.round(Number(value || 0) * 100)}%`

const safeHealth = (value) => {
  if (!value) return {}
  if (typeof value === 'string') {
    try {
      return JSON.parse(value)
    } catch {
      return {}
    }
  }
  return typeof value === 'object' ? value : {}
}

const fmtBytes = (bytes) => {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function TTip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip machine-calm-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color || p.fill, fontWeight: 600, fontSize: 12, marginTop: 2 }}>
          {p.name}: {p.value}
        </div>
      ))}
    </div>
  )
}

function DetailMetricCard({ icon: Icon, label, value, subtext, tone = 'brand' }) {
  return (
    <div className={`stat-card machine-calm-card machine-calm-stat machine-calm-tone-${tone}`}>
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

const TABS = [
  { id: 'overview', label: 'Overview', icon: ChartPieIcon },
  { id: 'apps', label: 'Applications', icon: AppIcon },
  { id: 'browser', label: 'Browser', icon: DomainIcon },
  { id: 'productivity', label: 'Productivity', icon: AverageHoursIcon },
  { id: 'live', label: 'Live View', icon: ChartLineIcon },
  { id: 'remote', label: 'Remote Control', icon: NetworkIcon },
  { id: 'dlp', label: 'DLP Events', icon: AppIcon },
  { id: 'phishing', label: 'Phishing', icon: DomainIcon },
  { id: 'files', label: 'File Logs', icon: AppIcon },
  { id: 'network', label: 'Network Logs', icon: NetworkIcon },
  { id: 'diagnostics', label: 'Diagnostics', icon: NetworkIcon },
]

export default function MachineDetail() {
  const { machineId } = useParams()
  const { get, post } = useApi()
  const navigate = useNavigate()
  const iceServers = useIceServers()
  const { send: wsSend } = useWsContext()

  const [machine, setMachine] = useState(null)
  const [analytics, setAnalytics] = useState(null)
  const [browser, setBrowser] = useState([])
  const [tab, setTab] = useState('overview')
  const [loading, setLoading] = useState(true)

  // Productivity
  const [productivity, setProductivity] = useState(null)
  const [prodStartDate, setProdStartDate] = useState('')
  const [prodEndDate, setProdEndDate] = useState('')
  const [prodLoading, setProdLoading] = useState(false)

  // DLP
  const [dlpData, setDlpData] = useState([])
  const [dlpTotal, setDlpTotal] = useState(0)
  const [dlpLoading, setDlpLoading] = useState(false)
  const [dlpPage, setDlpPage] = useState(0)

  // Phishing
  const [phishingData, setPhishingData] = useState([])
  const [phishingTotal, setPhishingTotal] = useState(0)
  const [phishingLoading, setPhishingLoading] = useState(false)
  const [phishingPage, setPhishingPage] = useState(0)

  // File Logs
  const [fileLogsData, setFileLogsData] = useState([])
  const [fileLogsTotal, setFileLogsTotal] = useState(0)
  const [fileLogsLoading, setFileLogsLoading] = useState(false)
  const [fileLogsPage, setFileLogsPage] = useState(0)

  // Network Logs
  const [networkLogsData, setNetworkLogsData] = useState([])
  const [networkLogsTotal, setNetworkLogsTotal] = useState(0)
  const [networkLogsLoading, setNetworkLogsLoading] = useState(false)
  const [networkLogsPage, setNetworkLogsPage] = useState(0)

  // WebRTC Live View
  const [liveActivity, setLiveActivity] = useState([])
  const {
    mode: liveMode,
    errorMsg: liveErrorMsg,
    jpegSrc: liveJpegSrc,
    jpegTs: liveJpegTs,
    liveJpeg: liveLiveJpeg,
    setLiveJpeg: setLiveLiveJpeg,
    startSession: startLiveSession,
    endSession: endLiveSession,
    requestScreenshot: requestLiveScreenshot,
    videoRef: liveVideoRef,
    realtimeStatus: liveRealtimeStatus,
  } = useWebRtcSession({
    sessionKind: 'live',
    selectedId: machineId,
    selectedRef: { current: machineId },
    wsSend,
    useWsListener,
    iceServers,
    offerTimeoutMs: 14000,
    jpegPollMs: 8000,
    beforeStart: (mId, sessionKind) => post(`/api/sessions/machines/${mId}/start`, { session_kind: sessionKind }),
    onMachinePresenceChange: () => {},
    onAfterEnd: () => { setLiveActivity([]) },
    onMessage: (msg, ctx) => {
      const { type, machine_id } = msg
      if (machine_id !== ctx.currentId) return false
      if (type === 'app_update' || type === 'browser_update') {
        setLiveActivity((items) => [
          { ...msg, ts: new Date().toLocaleTimeString() },
          ...items,
        ].slice(0, 40))
        return true
      }
      return false
    },
  })

  // WebRTC Remote Control
  const [cmdLog, setCmdLog] = useState([])
  const [inputOn, setInputOn] = useState(false)
  const [kbMode, setKbMode] = useState('raw')
  const [dcState, setDcState] = useState('closed')
  const [hasAudio, setHasAudio] = useState(false)
  const [audioMuted, setAudioMuted] = useState(false)
  const [showPaste, setShowPaste] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [showFilePanel, setShowFilePanel] = useState(false)
  const [transfers, setTransfers] = useState([])
  const [dragOver, setDragOver] = useState(false)

  const dcRef = useRef(null)
  const ftDcRef = useRef(null)
  const containerRef = useRef(null)
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)
  const inputBuf = useRef([])
  const flushRaf = useRef(null)
  const scrollRaf = useRef(null)
  const scrollAcc = useRef({ dy: 0, dx: 0, x: 0, y: 0 })
  const heldBtns = useRef(new Set())
  const heldKeys = useRef(new Set())
  const lastMove = useRef(0)
  const inputOnRef = useRef(false)
  const kbModeRef = useRef('raw')
  const ftReceive = useRef({})
  const pendingFiles = useRef({})

  useEffect(() => { inputOnRef.current = inputOn }, [inputOn])
  useEffect(() => { kbModeRef.current = kbMode }, [kbMode])

  const addLog = (type, action, detail = '') => {
    setCmdLog(prev => [{ ts: new Date().toLocaleTimeString(), type, action, detail }, ...prev].slice(0, 50))
  }

  const {
    mode: remoteMode,
    errorMsg: remoteErrorMsg,
    jpegSrc: remoteJpegSrc,
    startSession: startRemoteSession,
    endSession: endRemoteSession,
    videoRef: remoteVideoRef,
    audioRef: remoteAudioRef,
    realtimeStatus: remoteRealtimeStatus,
  } = useWebRtcSession({
    sessionKind: 'remote',
    selectedId: machineId,
    selectedRef: { current: machineId },
    wsSend,
    useWsListener,
    iceServers,
    offerTimeoutMs: 14000,
    jpegPollMs: 8000,
    beforeStart: (mId, sessionKind) => post(`/api/sessions/machines/${mId}/start`, { session_kind: sessionKind }),
    onMachinePresenceChange: () => {},
    onAfterEnd: () => {
      cancelAnimationFrame(scrollRaf.current)
      cancelAnimationFrame(flushRaf.current)
      heldBtns.current.forEach(btn => {
        try { dcRef.current?.send(JSON.stringify({ type: 'mouseup', button: btn, x: 0, y: 0 })) } catch {}
      })
      heldBtns.current.clear()
      heldKeys.current.forEach(code => {
        try { dcRef.current?.send(JSON.stringify({ type: 'keyup', code, key: '' })) } catch {}
      })
      heldKeys.current.clear()
      if (dcRef.current) { try { dcRef.current.close() } catch {} dcRef.current = null }
      if (ftDcRef.current) { try { ftDcRef.current.close() } catch {} ftDcRef.current = null }
      if (remoteAudioRef.current) remoteAudioRef.current.srcObject = null
      setInputOn(false)
      setDcState('closed')
      setHasAudio(false)
      setTransfers([])
      setShowFilePanel(false)
    },
    configurePeerConnection: ({ pc, setModeSync: setSessionMode }) => {
      pc.ondatachannel = (event) => {
        const dc = event.channel
        if (dc.label === 'input') {
          dcRef.current = dc
          dc.onopen = () => { setDcState('open'); addLog('info', 'channel', 'Input channel open') }
          dc.onclose = () => { setDcState('closed'); addLog('info', 'channel', 'Channel closed') }
          dc.onerror = () => { setDcState('error'); addLog('error', 'channel', 'Channel error') }
        } else if (dc.label === 'filetransfer') {
          ftDcRef.current = dc
          dc.binaryType = 'arraybuffer'
          dc.onopen = () => addLog('info', 'file', 'File transfer channel open')
          dc.onclose = () => { ftDcRef.current = null }
          dc.onmessage = (e) => {
            const data = e.data
            if (data instanceof ArrayBuffer) {
              const view = new Uint8Array(data)
              const id = new TextDecoder().decode(view.slice(0, 36))
              const chunk = view.slice(36)
              const rx = ftReceive.current[id]
              if (!rx) return
              rx.chunks.push(chunk)
              rx.received += chunk.length
              const progress = Math.min(100, Math.round((rx.received / rx.size) * 100))
              setTransfers(prev => prev.map(t => t.id === id ? { ...t, progress, status: 'receiving' } : t))
            } else {
              try {
                const msg = JSON.parse(data)
                if (msg.type === 'file_offer') {
                  const { id, name, size } = msg
                  ftReceive.current[id] = { chunks: [], name, size, received: 0 }
                  setTransfers(prev => [...prev, { id, name, size, dir: 'down', progress: 0, status: 'receiving' }])
                  setShowFilePanel(true)
                  ftDcRef.current?.send(JSON.stringify({ type: 'file_accept', id }))
                } else if (msg.type === 'file_complete') {
                  const { id } = msg
                  const rx = ftReceive.current[id]
                  if (!rx) return
                  const blob = new Blob(rx.chunks)
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url; a.download = rx.name; a.click()
                  URL.revokeObjectURL(url)
                  delete ftReceive.current[id]
                  setTransfers(prev => prev.map(t => t.id === id ? { ...t, progress: 100, status: 'done' } : t))
                  addLog('info', 'file', `Received: ${rx.name}`)
                } else if (msg.type === 'file_accept') {
                  const file = pendingFiles.current[msg.id]
                  if (!file) return
                  delete pendingFiles.current[msg.id]
                  setTransfers(prev => prev.map(t => t.id === msg.id ? { ...t, status: 'sending' } : t))
                  let offset = 0
                  const total = file.size
                  const hashBuf = []
                  const sendNext = () => {
                    if (offset >= total) {
                      const allChunks = new Blob(hashBuf)
                      allChunks.arrayBuffer().then(buf => {
                        crypto.subtle.digest('SHA-256', buf).then(hash => {
                          const hex = Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('')
                          ftDcRef.current?.send(JSON.stringify({ type: 'file_complete', id: msg.id, sha256: hex }))
                        })
                      })
                      return
                    }
                    if (ftDcRef.current?.bufferedAmount > 1048576) {
                      setTimeout(sendNext, 50)
                      return
                    }
                    const end = Math.min(offset + 16384, total)
                    const slice = file.slice(offset, end)
                    slice.arrayBuffer().then(buf => {
                      const chunk = new Uint8Array(buf)
                      hashBuf.push(new Blob([chunk]))
                      const idBytes = new TextEncoder().encode(msg.id)
                      const frame = new Uint8Array(36 + chunk.length)
                      frame.set(idBytes, 0)
                      frame.set(chunk, 36)
                      ftDcRef.current?.send(frame.buffer)
                      offset = end
                      const progress = Math.round((offset / total) * 100)
                      setTransfers(prev => prev.map(t => t.id === msg.id ? { ...t, progress, status: 'sending' } : t))
                      setTimeout(sendNext, 0)
                    })
                  }
                  sendNext()
                } else if (msg.type === 'file_reject') {
                  setTransfers(prev => prev.map(t => t.id === msg.id ? { ...t, status: 'rejected' } : t))
                } else if (msg.type === 'file_ack') {
                  setTransfers(prev => prev.map(t => t.id === msg.id ? { ...t, progress: 100, status: 'done' } : t))
                }
              } catch {}
            }
          }
        }
      }

      return {
        onTrack: (event) => {
          if (event.track.kind === 'video') {
            if (remoteVideoRef.current) {
              remoteVideoRef.current.srcObject = event.streams?.[0] || new MediaStream([event.track])
              remoteVideoRef.current.play().catch(() => {})
              setSessionMode(SESSION_MODES.CONNECTED)
            }
            return
          }
          if (event.track.kind === 'audio') {
            setHasAudio(true)
            if (remoteAudioRef.current) {
              remoteAudioRef.current.srcObject = new MediaStream([event.track])
              remoteAudioRef.current.play().catch(() => {})
            }
          }
        }
      }
    }
  })

  const sendFileToAgent = async (file) => {
    const dc = ftDcRef.current
    if (!dc || dc.readyState !== 'open') {
      addLog('error', 'file', 'File transfer channel not open')
      return
    }
    const id = crypto.randomUUID()
    pendingFiles.current[id] = file
    setTransfers(prev => [...prev, { id, name: file.name, size: file.size, dir: 'up', progress: 0, status: 'pending' }])
    setShowFilePanel(true)
    dc.send(JSON.stringify({ type: 'file_offer', id, name: file.name, size: file.size }))
  }

  const sendEvt = (payload) => {
    const dc = dcRef.current
    if (!dc || dc.readyState !== 'open') return
    inputBuf.current.push(payload)
    if (!flushRaf.current) {
      flushRaf.current = requestAnimationFrame(() => {
        flushRaf.current = null
        const buf = inputBuf.current.splice(0, 50)
        if (!buf.length) return
        const dc2 = dcRef.current
        if (!dc2 || dc2.readyState !== 'open') return
        buf.forEach(ev => { try { dc2.send(JSON.stringify(ev)) } catch {} })
      })
    }
  }

  const toScreen = (clientX, clientY) => {
    const vid = remoteVideoRef.current
    if (!vid) return { x: 0, y: 0 }
    const rect = vid.getBoundingClientRect()
    const natW = vid.videoWidth || rect.width
    const natH = vid.videoHeight || rect.height
    const scale = Math.min(rect.width / natW, rect.height / natH)
    const ox = (rect.width - natW * scale) / 2
    const oy = (rect.height - natH * scale) / 2
    const clampVal = (val, min, max) => Math.min(Math.max(val, min), max)
    return {
      x: Math.round(clampVal((clientX - rect.left - ox) / scale, 0, natW)),
      y: Math.round(clampVal((clientY - rect.top - oy) / scale, 0, natH)),
    }
  }

  const onPointerDown = (e) => {
    if (!inputOn) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    heldBtns.current.add(e.button)
    sendEvt({ type: 'mousedown', button: e.button, ...toScreen(e.clientX, e.clientY) })
    if (kbMode === 'raw') containerRef.current?.focus({ preventScroll: true })
    else textareaRef.current?.focus({ preventScroll: true })
  }

  const onPointerUp = (e) => {
    if (!inputOn) return
    try { e.currentTarget.releasePointerCapture(e.pointerId) } catch {}
    heldBtns.current.delete(e.button)
    sendEvt({ type: 'mouseup', button: e.button, ...toScreen(e.clientX, e.clientY) })
  }

  const onPointerMove = (e) => {
    if (!inputOn) return
    const now = Date.now()
    if (now - lastMove.current < 20) return
    lastMove.current = now
    try { dcRef.current?.send(JSON.stringify({ type: 'mousemove', ...toScreen(e.clientX, e.clientY) })) } catch {}
  }

  const onPointerLeave = () => {
    if (inputOn) {
      heldBtns.current.forEach(btn => {
        try { dcRef.current?.send(JSON.stringify({ type: 'mouseup', button: btn, x: 0, y: 0 })) } catch {}
      })
      heldBtns.current.clear()
    }
  }

  const onDblClick = (e) => {
    if (!inputOn) return
    sendEvt({ type: 'dblclick', button: e.button, ...toScreen(e.clientX, e.clientY) })
  }

  const onWheel = (e) => {
    if (!inputOn) return
    e.preventDefault()
    scrollAcc.current.dy += e.deltaY
    scrollAcc.current.dx += e.deltaX
    const pos = toScreen(e.clientX, e.clientY)
    scrollAcc.current.x = pos.x
    scrollAcc.current.y = pos.y
    if (!scrollRaf.current) {
      scrollRaf.current = requestAnimationFrame(() => {
        scrollRaf.current = null
        const { dy, dx, x, y } = scrollAcc.current
        scrollAcc.current = { dy: 0, dx: 0, x: 0, y: 0 }
        const vy = Math.round(dy / 100)
        const vx = Math.round(dx / 100)
        if (vy !== 0) {
          try { dcRef.current?.send(JSON.stringify({ type: 'scroll', dir: vy > 0 ? 'down' : 'up', amount: Math.abs(vy), x, y })) } catch {}
        }
        if (vx !== 0) {
          try { dcRef.current?.send(JSON.stringify({ type: 'scroll', dir: vx > 0 ? 'right' : 'left', amount: Math.abs(vx), x, y })) } catch {}
        }
      })
    }
  }

  const onRawKeyDown = (e) => {
    if (!inputOn || kbMode !== 'raw') return
    e.preventDefault()
    e.stopPropagation()
    const code = e.code
    if (!code) return
    heldKeys.current.add(code)
    sendEvt({
      type: 'keydown', code, key: e.key,
      ctrl: e.ctrlKey, shift: e.shiftKey, alt: e.altKey, meta: e.metaKey,
    })
  }

  const onRawKeyUp = (e) => {
    if (!inputOn || kbMode !== 'raw') return
    e.preventDefault()
    e.stopPropagation()
    const code = e.code
    if (!code) return
    heldKeys.current.delete(code)
    try { dcRef.current?.send(JSON.stringify({ type: 'keyup', code, key: e.key })) } catch {}
  }

  const onTextareaInput = (e) => {
    if (!inputOn) return
    const text = e.target.value
    if (!text) return
    sendEvt({ type: 'text', text })
    e.target.value = ''
  }

  const onTextareaKeyDown = (e) => {
    if (!inputOn) return
    const cmd = {
      'Enter': 'enter', 'Backspace': 'backspace', 'Delete': 'delete', 'Tab': 'tab',
      'Escape': 'escape', 'ArrowUp': 'up', 'ArrowDown': 'down', 'ArrowLeft': 'left',
      'ArrowRight': 'right', 'Home': 'home', 'End': 'end', 'PageUp': 'pageup', 'PageDown': 'pagedown'
    }[e.key]
    if (cmd) {
      e.preventDefault()
      sendEvt({ type: 'command', action: cmd })
    }
  }

  const onFileDrop = (e) => {
    e.preventDefault(); setDragOver(false)
    const files = e.dataTransfer?.files
    if (files) Array.from(files).forEach(f => sendFileToAgent(f))
  }

  const onFileSelect = (e) => {
    const files = e.target?.files
    if (files) Array.from(files).forEach(f => sendFileToAgent(f))
    e.target.value = ''
  }

  const toggleInput = (on) => {
    setInputOn(on)
    if (!on) {
      heldBtns.current.forEach(btn => {
        try { dcRef.current?.send(JSON.stringify({ type: 'mouseup', button: btn, x: 0, y: 0 })) } catch {}
      })
      heldBtns.current.clear()
      heldKeys.current.forEach(code => {
        try { dcRef.current?.send(JSON.stringify({ type: 'keyup', code, key: '' })) } catch {}
      })
      heldKeys.current.clear()
    }
    else if (kbMode === 'raw') setTimeout(() => containerRef.current?.focus({ preventScroll: true }), 50)
    else setTimeout(() => textareaRef.current?.focus({ preventScroll: true }), 50)
  }

  const sendPasteText = () => {
    if (!pasteText.trim()) return
    sendEvt({ type: 'text', text: pasteText })
    setPasteText(''); setShowPaste(false)
    if (kbMode === 'raw') containerRef.current?.focus({ preventScroll: true })
    else textareaRef.current?.focus({ preventScroll: true })
  }

  const pushClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText()
      sendEvt({ type: 'text', text })
      addLog('info', 'clipboard', `${text.length} chars`)
    } catch { addLog('error', 'clipboard', 'Permission denied') }
  }

  const handleTabChange = (nextTab) => {
    if (tab === 'live') endLiveSession()
    if (tab === 'remote') endRemoteSession()
    setTab(nextTab)
  }

  // Load Machine Base Metadata
  useEffect(() => {
    Promise.all([
      get(`/api/machines/${machineId}`),
      get(`/api/analytics/machine/${machineId}`),
      get(`/api/analytics/browser/${machineId}?limit=50`),
    ])
      .then(([m, a, b]) => {
        setMachine(m)
        setAnalytics(a)
        setBrowser(Array.isArray(b) ? b : [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [get, machineId])

  // Heartbeat Polling
  useEffect(() => {
    const timer = setInterval(() => {
      get(`/api/machines/${machineId}`)
        .then((fresh) => setMachine((current) => (current ? { ...current, ...fresh } : fresh)))
        .catch(() => {})
    }, 15000)
    return () => clearInterval(timer)
  }, [get, machineId])

  // Lazy Fetch Productivity Data
  useEffect(() => {
    if (tab === 'productivity' && !productivity) {
      setProdLoading(true)
      const qs = (prodStartDate || prodEndDate) ? `?start_date=${prodStartDate}&end_date=${prodEndDate}` : ''
      get(`/api/productivity/machines/${machineId}${qs}`)
        .then(setProductivity)
        .catch(() => {})
        .finally(() => setProdLoading(false))
    }
  }, [tab, get, machineId, prodStartDate, prodEndDate, productivity])

  // Lazy Fetch DLP Events
  useEffect(() => {
    if (tab === 'dlp') {
      setDlpLoading(true)
      get(`/api/dlp/events?machine_id=${machineId}&limit=10&offset=${dlpPage * 10}`)
        .then(res => {
          setDlpData(res.events || [])
          setDlpTotal(res.total || 0)
        })
        .catch(() => {})
        .finally(() => setDlpLoading(false))
    }
  }, [tab, get, machineId, dlpPage])

  // Lazy Fetch Phishing Alerts
  useEffect(() => {
    if (tab === 'phishing') {
      setPhishingLoading(true)
      get(`/api/phishing/events?machine_id=${machineId}&limit=10&offset=${phishingPage * 10}`)
        .then(res => {
          setPhishingData(res.events || [])
          setPhishingTotal(res.total || 0)
        })
        .catch(() => {})
        .finally(() => phishingLoading(false))
    }
  }, [tab, get, machineId, phishingPage])

  // Lazy Fetch File Logs
  useEffect(() => {
    if (tab === 'files') {
      setFileLogsLoading(true)
      get(`/api/files?machine_id=${machineId}&limit=10&offset=${fileLogsPage * 10}`)
        .then(res => {
          setFileLogsData(res.files || [])
          setFileLogsTotal(res.total || 0)
        })
        .catch(() => {})
        .finally(() => setFileLogsLoading(false))
    }
  }, [tab, get, machineId, fileLogsPage])

  // Lazy Fetch Network Logs
  useEffect(() => {
    if (tab === 'network') {
      setNetworkLogsLoading(true)
      get(`/api/network?machine_id=${machineId}&limit=10&offset=${networkLogsPage * 10}`)
        .then(res => {
          setNetworkLogsData(res.logs || [])
          setNetworkLogsTotal(res.total || 0)
        })
        .catch(() => {})
        .finally(() => setNetworkLogsLoading(false))
    }
  }, [tab, get, machineId, networkLogsPage])

  const downloadReport = () => {
    get(`/api/reports/generate/${machineId}`)
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `CropSentinel_${machine?.hostname}.pdf`
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch(() => {})
  }

  if (loading) {
    return <div className="loading-center"><div className="spinner" style={{ width: 32, height: 32 }} /></div>
  }
  if (!machine) {
    return <div className="loading-center" style={{ color: 'var(--red)' }}>Machine not found</div>
  }

  const appUsage = analytics?.app_usage || []
  const appPie = appUsage.slice(0, 6).map((a) => ({ name: a.app_name, value: a.total_seconds }))
  const hourly = Array.from({ length: 24 }, (_, h) => {
    const hour = String(h).padStart(2, '0')
    const row = (analytics?.hourly_activity || []).find((entry) => entry.hour === hour)
    return { hour: `${hour}:00`, mins: Math.round((row?.total_seconds || 0) / 60) }
  })
  const topApp = appUsage[0]
  const consentLabel = machine.consent_given ? 'Granted' : 'Pending'
  const badgeClass = machine.online ? 'badge-green' : 'badge-gray'
  const health = safeHealth(machine.agent_health)
  const queueHealth = safeHealth(health.queue)
  const runtimeHealth = safeHealth(health.runtime)
  const policyHealth = safeHealth(health.policy)
  const selfThrottleHealth = safeHealth(health.self_throttle)

  // Productivity Derived Stats
  const prodSummary = productivity?.summary || {}
  const prodComponents = productivity?.score_components || {}
  const prodBreakdown = productivity?.classification_breakdown || []
  const prodHourly = (productivity?.hourly_distribution || []).map((row) => ({
    hour: `${row.hour}:00`,
    productive: Math.round((row.productive || 0) / 60),
    supportive: Math.round((row.supportive || 0) / 60),
    distracting: Math.round((row.distracting || 0) / 60),
    neutral: Math.round((row.neutral || 0) / 60),
  }))
  const prodScore = Number(prodSummary.productivity_score || 0)
  const prodConfidence = Number(prodSummary.score_confidence || 0)
  const prodGaugeBg = `conic-gradient(${scoreColor(prodScore)} ${prodScore * 3.6}deg, var(--bg-4) 0deg)`

  return (
    <div className="fade-in machine-calm-shell">
      <div className="machine-calm-hero">
        <button
          onClick={() => navigate('/machines')}
          className="machine-calm-back"
        >
          Back to Machines
        </button>

        <div className="page-header machine-calm-header" style={{ marginBottom: 0 }}>
          <div className="machine-calm-title-wrap">
            <div className="machine-calm-avatar">
              <MachinesIcon size={24} />
            </div>
            <div>
              <div className="machine-calm-title-row">
                <div className="mono machine-calm-title">{machine.hostname}</div>
                <span className={`badge ${badgeClass}`}>
                  {machine.online ? 'Online' : 'Offline'}
                </span>
              </div>
              <div className="page-subtitle machine-calm-subtitle">
                {machine.username || 'Unknown user'} · {machine.ip_address || 'No IP'} · {machine.os || 'Unknown OS'}
              </div>
            </div>
          </div>

          <div className="page-actions">
            <button className="btn btn-primary btn-sm machine-calm-primary" onClick={downloadReport}>
              PDF Report
            </button>
          </div>
        </div>
      </div>

      <div className="grid-4" style={{ marginBottom: 20 }}>
        <DetailMetricCard
          icon={TimeIcon}
          label="Active Time"
          value={fmt(analytics?.total_active_seconds || 0)}
          subtext={`${analytics?.browser_visits || 0} browser visits`}
          tone="brand"
        />
        <DetailMetricCard
          icon={AppIcon}
          label="Top App"
          value={topApp?.app_name || '--'}
          subtext={fmt(topApp?.total_seconds || 0)}
          tone="sage"
        />
        <DetailMetricCard
          icon={ChartBarIcon}
          label="CPU / RAM"
          value={`${Math.round(machine.cpu_percent || 0)}% / ${Math.round(machine.memory_percent || 0)}%`}
          subtext="Current resource usage"
          tone="sand"
        />
        <DetailMetricCard
          icon={AverageHoursIcon}
          label="Active App"
          value={machine.active_app || '--'}
          subtext={`Idle ${Math.round((machine.idle_seconds || 0) / 60)}m`}
          tone="slate"
        />
      </div>

      <div className="tab-group machine-calm-tabs" style={{ marginBottom: 20, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {TABS.map((entry) => {
          const Icon = entry.icon
          return (
            <button
              key={entry.id}
              className={`tab-btn${tab === entry.id ? ' active' : ''}`}
              onClick={() => handleTabChange(entry.id)}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', fontSize: 12.5 }}
            >
              <Icon size={14} />
              {entry.label}
            </button>
          )
        })}
      </div>

      {tab === 'overview' && (
        <div className="slide-in" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="grid-2">
            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 16 }}>
                <div>
                  <div className="card-title">App Distribution</div>
                  <div className="stat-sub">A softer breakdown of the most active applications.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap">
                  <ChartPieIcon size={18} />
                </span>
              </div>
              {appPie.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-state-icon"><AppIcon size={34} /></div>
                  <div className="empty-state-title">No app data</div>
                </div>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <ResponsiveContainer width={160} height={160}>
                    <PieChart>
                      <Pie data={appPie} cx="50%" cy="50%" innerRadius={45} outerRadius={72} dataKey="value" stroke="none">
                        {appPie.map((_, i) => <Cell key={i} fill={calmChartColors[i % calmChartColors.length]} />)}
                      </Pie>
                      <Tooltip formatter={(v) => fmt(v)} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {appPie.map((d, i) => (
                      <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                        <div style={{ width: 8, height: 8, borderRadius: 999, background: calmChartColors[i % calmChartColors.length], flexShrink: 0 }} />
                        <span style={{ flex: 1, color: 'var(--text-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</span>
                        <span className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>{fmt(d.value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 16 }}>
                <div>
                  <div className="card-title">Hourly Activity</div>
                  <div className="stat-sub">Minutes active through the day.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap">
                  <ChartBarIcon size={18} />
                </span>
              </div>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={hourly} barSize={8} margin={{ left: -20, right: 4, top: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="hour" tick={{ fontSize: 9 }} interval={3} tickFormatter={(v) => v.slice(0, 2)} />
                  <YAxis tick={{ fontSize: 9 }} unit="m" />
                  <Tooltip content={<TTip />} />
                  <Bar dataKey="mins" name="Minutes" fill="#6b8bb6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card machine-calm-card">
            <div className="card-header" style={{ marginBottom: 16 }}>
              <div>
                <div className="card-title">Machine Details</div>
                <div className="stat-sub">Key enrollment and connectivity metadata.</div>
              </div>
              <span className="stat-icon-wrap machine-calm-icon-wrap">
                <NetworkIcon size={18} />
              </span>
            </div>
            <div className="machine-calm-detail-grid">
              {[
                ['Machine ID', machine.machine_id ? `${machine.machine_id.slice(0, 20)}...` : '--', true],
                ['Hostname', machine.hostname || '--', true],
                ['Username', machine.username || '--', false],
                ['OS', `${machine.os || '--'} ${machine.os_version || ''}`.trim(), false],
                ['IP Address', machine.ip_address || '--', true],
                ['MAC Address', machine.mac_address || '--', true],
                ['Agent Version', machine.agent_version || '--', false],
                ['First Seen', fmtTs(machine.first_seen), false],
                ['Last Seen', fmtTs(machine.last_seen), false],
                ['Consent', consentLabel, false],
              ].map(([k, v, mono]) => (
                <div key={k} className="machine-calm-detail-item">
                  <div className="machine-calm-detail-label">{k}</div>
                  <div className={mono ? 'mono machine-calm-detail-value' : 'machine-calm-detail-value'}>{v}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === 'apps' && (
        <div className="slide-in">
          {!appUsage.length ? (
            <div className="empty-state machine-calm-card">
              <div className="empty-state-icon"><AppIcon size={34} /></div>
              <div className="empty-state-title">No app data</div>
            </div>
          ) : (
            <div className="card machine-calm-card" style={{ padding: 0, overflow: 'hidden' }}>
              <table className="data-table machine-calm-table">
                <thead>
                  <tr><th>#</th><th>App</th><th>Time</th><th>Sessions</th><th>Share</th></tr>
                </thead>
                <tbody>
                  {appUsage.map((a, i) => {
                    const maxS = appUsage[0]?.total_seconds || 1
                    const pct = Math.round((a.total_seconds / maxS) * 100)
                    return (
                      <tr key={`${a.app_name}-${i}`}>
                        <td style={{ color: 'var(--text-3)', fontSize: 12 }}>{i + 1}</td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{ width: 8, height: 8, borderRadius: 999, background: calmChartColors[i % calmChartColors.length], flexShrink: 0 }} />
                            <span style={{ fontSize: 12, fontWeight: 600 }}>{a.app_name}</span>
                          </div>
                        </td>
                        <td className="mono" style={{ fontSize: 12, color: '#5c8a92', fontWeight: 600 }}>{fmt(a.total_seconds)}</td>
                        <td style={{ fontSize: 12, color: 'var(--text-2)' }}>{a.sessions}</td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div className="machine-calm-meter">
                              <div style={{ width: `${pct}%`, height: '100%', background: calmChartColors[i % calmChartColors.length], borderRadius: 999 }} />
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
          )}
        </div>
      )}

      {tab === 'browser' && (
        <div className="slide-in">
          {!browser.length ? (
            <div className="empty-state machine-calm-card">
              <div className="empty-state-icon"><DomainIcon size={34} /></div>
              <div className="empty-state-title">No browser history</div>
            </div>
          ) : (
            <div className="card machine-calm-card" style={{ padding: 0, overflow: 'hidden' }}>
              <table className="data-table machine-calm-table">
                <thead><tr><th>Time</th><th>Browser</th><th>Domain</th><th>Title</th><th>Duration</th></tr></thead>
                <tbody>
                  {browser.map((r, i) => (
                    <tr key={`${r.timestamp}-${i}`}>
                      <td className="mono" style={{ fontSize: 11, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>
                        {new Date(r.timestamp).toLocaleString()}
                      </td>
                      <td><span className="badge badge-blue" style={{ fontSize: 10 }}>{r.browser}</span></td>
                      <td className="mono" style={{ fontSize: 12, color: '#5c8a92' }}>{r.domain}</td>
                      <td style={{ fontSize: 12, color: 'var(--text-2)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <a href={r.url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }} title={r.url}>
                          {r.title || r.url || '--'}
                        </a>
                      </td>
                      <td className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>
                        {fmt(r.duration_seconds)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'productivity' && (
        <div className="slide-in">
          {prodLoading && <div className="loading-center"><div className="spinner" style={{ width: 28, height: 28 }} /></div>}
          {!prodLoading && !productivity && (
            <div className="empty-state machine-calm-card">No productivity data found</div>
          )}
          {!prodLoading && productivity && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {prodConfidence < 60 && (
                <div className="card" style={{ border: '1px solid rgba(245,166,35,.25)', color: 'var(--warning)', padding: 12 }}>
                  Score confidence is reduced because rule coverage or telemetry depth is limited for this time window.
                </div>
              )}
              <div className="grid-2">
                <div className="card machine-calm-card" style={{ display: 'grid', placeItems: 'center', minHeight: 240 }}>
                  <div style={{ display: 'grid', placeItems: 'center', gap: 10 }}>
                    <div style={{ width: 150, height: 150, borderRadius: 150, background: prodGaugeBg, display: 'grid', placeItems: 'center' }}>
                      <div style={{ width: 110, height: 110, borderRadius: 110, background: 'var(--bg-2)', display: 'grid', placeItems: 'center' }}>
                        <div style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: 32, fontWeight: 800 }}>{prodScore}</div>
                          <div style={{ fontSize: 10, color: 'var(--text-3)' }}>{prodConfidence}% confidence</div>
                        </div>
                      </div>
                    </div>
                    <div style={{ fontWeight: 700, fontSize: 13.5 }}>Productivity Score</div>
                  </div>
                </div>

                <div className="card machine-calm-card" style={{ padding: '16px 20px' }}>
                  <div style={{ fontWeight: 700, marginBottom: 12, fontSize: 13.5 }}>Category Breakdown</div>
                  <div style={{ display: 'grid', gap: 8, fontSize: 12 }}>
                    {[
                      ['Active Time', prodSummary.active_time_seconds],
                      ['Idle Time', prodSummary.idle_time_seconds],
                      ['Focus Time', prodSummary.focus_time_seconds],
                      ['Productive', prodComponents.productive_time_seconds],
                      ['Supportive', prodComponents.supportive_time_seconds],
                      ['Distracting', prodComponents.distracting_time_seconds],
                    ].map(([label, value]) => (
                      <div key={label} style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-0)', paddingBottom: 6 }}>
                        <span>{label}</span>
                        <strong className="mono">{fmtDuration(value)}</strong>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="grid-2">
                <div className="card machine-calm-card" style={{ padding: '16px 20px' }}>
                  <div style={{ fontWeight: 700, marginBottom: 12, fontSize: 13.5 }}>Productivity Findings</div>
                  {!productivity.findings?.length ? (
                    <div style={{ color: 'var(--text-3)', fontSize: 12 }}>No findings in this window</div>
                  ) : (
                    <div style={{ display: 'grid', gap: 10 }}>
                      {productivity.findings.map((finding, idx) => (
                        <div key={idx} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 10 }}>
                          <div style={{ fontSize: 12.5, fontWeight: 700 }}>{finding.title}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>{finding.description}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="card machine-calm-card" style={{ padding: '16px 20px' }}>
                  <div style={{ fontWeight: 700, marginBottom: 12, fontSize: 13.5 }}>Trend Analysis</div>
                  <div style={{ display: 'grid', gap: 8, fontSize: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-0)', paddingBottom: 6 }}>
                      <span>Direction</span>
                      <strong style={{ textTransform: 'capitalize', color: 'var(--brand)' }}>{productivity.trend?.direction || 'flat'}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-0)', paddingBottom: 6 }}>
                      <span>Score Delta</span>
                      <strong className="mono">{productivity.trend?.score_delta || 0}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-0)', paddingBottom: 6 }}>
                      <span>Focus Delta</span>
                      <strong className="mono">{fmtDuration(productivity.trend?.focus_delta_seconds || 0)}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: 6 }}>
                      <span>Workload Intensity</span>
                      <strong className="mono">{prodSummary.workload_intensity_score || 0}</strong>
                    </div>
                  </div>
                </div>
              </div>

              <div className="grid-2">
                <div className="card machine-calm-card" style={{ padding: '16px 20px' }}>
                  <div style={{ fontWeight: 700, marginBottom: 12, fontSize: 13.5 }}>Hourly Distribution</div>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={prodHourly} margin={{ top: 4, right: 8, bottom: 4, left: -22 }}>
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

                <div className="card machine-calm-card" style={{ padding: '16px 20px' }}>
                  <div style={{ fontWeight: 700, marginBottom: 12, fontSize: 13.5 }}>Rule Policy Coverage</div>
                  <div style={{ display: 'grid', gap: 10 }}>
                    {prodBreakdown.map((item) => (
                      <div key={item.category} style={{ display: 'grid', gap: 4 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
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
                    <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 8 }}>
                      Policy version {productivity.meta?.policy_version || 1} · {productivity.meta?.window_seconds || 0} second window
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'live' && (
        <div className="slide-in">
          <div className="session-main">
            <div className="session-topbar machine-calm-card" style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '10px 14px', marginBottom: 12 }}>
              <span className="mono" style={{ fontSize: 13, fontWeight: 700 }}>Live View Session</span>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                {![SESSION_MODES.CONNECTED, SESSION_MODES.JPEG, SESSION_MODES.UNSTABLE].includes(liveMode) && liveMode !== SESSION_MODES.REQUESTING && (
                  <button className="btn btn-primary btn-sm machine-calm-primary" onClick={startLiveSession}>Connect</button>
                )}
                {[SESSION_MODES.CONNECTED, SESSION_MODES.JPEG, SESSION_MODES.UNSTABLE].includes(liveMode) && (
                  <button className="btn btn-outline btn-sm machine-calm-btn" onClick={endLiveSession}>Disconnect</button>
                )}
                {liveMode === SESSION_MODES.REQUESTING && (
                  <button className="btn btn-outline btn-sm machine-calm-btn" disabled>
                    <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} /> Connecting...
                  </button>
                )}
              </div>
            </div>

            <RealtimeStatusBanner
              status={liveRealtimeStatus}
              message={liveErrorMsg}
              onRetry={startLiveSession}
            />

            <div className="session-viewer machine-calm-card" style={{ height: 400, background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
              <video
                ref={liveVideoRef}
                autoPlay
                playsInline
                muted
                style={{
                  maxWidth: '100%', maxHeight: '100%', objectFit: 'contain',
                  display: (liveMode === SESSION_MODES.CONNECTED || liveMode === SESSION_MODES.UNSTABLE) ? 'block' : 'none',
                }}
              />
              {liveMode === SESSION_MODES.JPEG && liveJpegSrc && (
                <img
                  src={`data:image/jpeg;base64,${liveJpegSrc}`}
                  alt="screen"
                  style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                />
              )}
              {liveMode === SESSION_MODES.IDLE && (
                <div style={{ color: 'var(--text-3)', textAlign: 'center' }}>
                  <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-2)' }}>P2P Streaming Engine Ready</div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>Click Connect to initiate direct screen capture feed</div>
                </div>
              )}
              {liveMode === SESSION_MODES.REQUESTING && (
                <div style={{ color: 'var(--text-3)', textAlign: 'center' }}>
                  <div className="spinner" style={{ width: 24, height: 24, borderWidth: 2, margin: '0 auto 12px' }} />
                  <div style={{ fontSize: 13 }}>Negotiating WebRTC Tunnel...</div>
                </div>
              )}
            </div>

            <div className="session-feed machine-calm-card" style={{ marginTop: 12, padding: '12px 16px' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', marginBottom: 8 }}>Live Session Activity Feed</div>
              <div style={{ maxHeight: 150, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
                {liveActivity.length === 0 ? (
                  <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Waiting for activity events...</div>
                ) : liveActivity.map((entry, index) => (
                  <div key={index} style={{ display: 'flex', gap: 10, fontSize: 12, alignItems: 'center' }}>
                    <span className="mono" style={{ fontSize: 10, color: 'var(--text-3)' }}>{entry.ts}</span>
                    <span className={`badge ${entry.type === 'app_update' ? 'badge-blue' : 'badge-amber'}`} style={{ fontSize: 9 }}>
                      {entry.type === 'app_update' ? 'APP' : 'WEB'}
                    </span>
                    <span style={{ color: 'var(--text-2)' }}>{entry.type === 'app_update' ? entry.data?.app_name : entry.data?.domain}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'remote' && (
        <div className="slide-in">
          <div className="session-main">
            <div className="session-topbar machine-calm-card" style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '8px 14px', marginBottom: 12, flexWrap: 'wrap' }}>
              <span className="mono" style={{ fontSize: 13, fontWeight: 700 }}>Remote Interactive Control</span>
              {remoteMode === SESSION_MODES.CONNECTED && (
                <>
                  <button className="btn btn-outline btn-sm machine-calm-btn" onClick={() => setKbMode(m => m === 'raw' ? 'text' : 'raw')} style={{ fontSize: 11, minHeight: 'auto', padding: '4px 8px' }}>
                    Mode: {kbMode === 'raw' ? 'Raw Keys' : 'Text IME'}
                  </button>
                  <button className="btn btn-outline btn-sm machine-calm-btn" onClick={pushClipboard} disabled={dcState !== 'open'} style={{ fontSize: 11, minHeight: 'auto', padding: '4px 8px' }}>
                    Push Clip
                  </button>
                  <button className={`btn btn-sm ${showPaste ? 'btn-primary machine-calm-primary' : 'btn-outline btn-sm machine-calm-btn'}`} onClick={() => setShowPaste(p => !p)} style={{ fontSize: 11, minHeight: 'auto', padding: '4px 8px' }}>
                    Type Text
                  </button>
                  <button className={`btn btn-sm ${showFilePanel ? 'btn-primary machine-calm-primary' : 'btn-outline btn-sm machine-calm-btn'}`} onClick={() => setShowFilePanel(p => !p)} style={{ fontSize: 11, minHeight: 'auto', padding: '4px 8px' }}>
                    Files
                  </button>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11.5, cursor: 'pointer', userSelect: 'none', color: inputOn ? 'var(--purple)' : 'var(--text-3)' }}>
                    <input type="checkbox" checked={inputOn} onChange={e => toggleInput(e.target.checked)} />
                    Input Enable
                  </label>
                </>
              )}
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                {![SESSION_MODES.CONNECTED, SESSION_MODES.JPEG, SESSION_MODES.UNSTABLE].includes(remoteMode) && remoteMode !== SESSION_MODES.REQUESTING && (
                  <button className="btn btn-primary btn-sm machine-calm-primary" onClick={startRemoteSession}>Connect</button>
                )}
                {[SESSION_MODES.CONNECTED, SESSION_MODES.JPEG, SESSION_MODES.UNSTABLE].includes(remoteMode) && (
                  <button className="btn btn-outline btn-sm machine-calm-btn" onClick={endRemoteSession}>Disconnect</button>
                )}
                {remoteMode === SESSION_MODES.REQUESTING && (
                  <button className="btn btn-outline btn-sm machine-calm-btn" disabled>
                    <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} /> Connecting...
                  </button>
                )}
              </div>
            </div>

            {showPaste && remoteMode === SESSION_MODES.CONNECTED && (
              <div className="machine-calm-card" style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '8px 14px', marginBottom: 12 }}>
                <input className="input-field" style={{ flex: 1, height: 32, fontSize: 12 }} value={pasteText} onChange={e => setPasteText(e.target.value)} placeholder="Type characters to send..." />
                <button className="btn btn-primary btn-sm machine-calm-primary" onClick={sendPasteText} disabled={!pasteText.trim() || dcState !== 'open'} style={{ minHeight: 'auto', padding: '4px 10px' }}>Send</button>
              </div>
            )}

            {showFilePanel && remoteMode === SESSION_MODES.CONNECTED && (
              <div className="machine-calm-card" style={{ padding: '12px 14px', marginBottom: 12 }}>
                <div onDragOver={e => { e.preventDefault(); setDragOver(true) }} onDragLeave={() => setDragOver(false)} onDrop={onFileDrop} onClick={() => fileInputRef.current?.click()} style={{ border: '2px dashed var(--border-1)', padding: 14, textAlign: 'center', cursor: 'pointer', background: dragOver ? 'var(--brand-subtle)' : 'transparent', borderRadius: 8 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Drag files here or click to upload</div>
                  <input ref={fileInputRef} type="file" multiple onChange={onFileSelect} style={{ display: 'none' }} />
                </div>
                {transfers.length > 0 && (
                  <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {transfers.map(t => (
                      <div key={t.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, background: 'var(--surface-3)', padding: '4px 8px', borderRadius: 4 }}>
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 200 }}>{t.name}</span>
                        <span>{t.progress}% · {t.status}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            <RealtimeStatusBanner
              status={remoteRealtimeStatus}
              message={remoteErrorMsg}
              onRetry={startRemoteSession}
            />

            <div
              ref={containerRef}
              tabIndex={0}
              className="session-viewer machine-calm-card"
              style={{
                height: 400, background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative', outline: 'none',
                cursor: (inputOn && dcState === 'open') ? 'crosshair' : 'default',
              }}
              onPointerDown={onPointerDown}
              onPointerUp={onPointerUp}
              onPointerMove={onPointerMove}
              onPointerLeave={onPointerLeave}
              onDoubleClick={onDblClick}
              onWheel={onWheel}
              onKeyDown={onRawKeyDown}
              onKeyUp={onRawKeyUp}
            >
              {kbMode === 'text' && (
                <textarea
                  ref={textareaRef}
                  defaultValue=""
                  autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
                  onInput={onTextareaInput}
                  onKeyDown={onTextareaKeyDown}
                  style={{ position: 'absolute', left: '-9999px', top: 0, width: 1, height: 1, opacity: 0 }}
                />
              )}
              <audio ref={remoteAudioRef} autoPlay style={{ display: 'none' }} />
              <video
                ref={remoteVideoRef}
                autoPlay
                playsInline
                muted
                style={{
                  maxWidth: '100%', maxHeight: '100%', objectFit: 'contain',
                  display: remoteMode === SESSION_MODES.CONNECTED ? 'block' : 'none',
                }}
              />
              {remoteMode === SESSION_MODES.JPEG && remoteJpegSrc && (
                <img
                  src={`data:image/jpeg;base64,${remoteJpegSrc}`}
                  alt="screen"
                  style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                />
              )}
              {remoteMode === SESSION_MODES.IDLE && (
                <div style={{ color: 'var(--text-3)', textAlign: 'center' }}>
                  <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-2)' }}>Remote Access Controller Ready</div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>Click Connect to initiate direct keyboard, mouse, and audio relay control</div>
                </div>
              )}
            </div>

            <div className="session-feed machine-calm-card" style={{ marginTop: 12, padding: '12px 16px' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', marginBottom: 8 }}>Session Command Console</div>
              <div style={{ maxHeight: 150, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
                {cmdLog.length === 0 ? (
                  <div style={{ fontSize: 12, color: 'var(--text-3)' }}>No actions logged yet</div>
                ) : cmdLog.map((e, i) => (
                  <div key={i} style={{ fontSize: 11.5, display: 'flex', gap: 6 }}>
                    <span className="mono" style={{ color: 'var(--text-3)' }}>{e.ts}</span>
                    <span style={{ fontWeight: 700, color: e.type === 'error' ? 'var(--danger)' : 'var(--success)' }}>{e.action}</span>
                    <span style={{ color: 'var(--text-2)' }}>{e.detail}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'dlp' && (
        <div className="slide-in">
          {dlpLoading && <div className="loading-center"><div className="spinner" style={{ width: 28, height: 28 }} /></div>}
          {!dlpLoading && !dlpData.length && (
            <div className="empty-state machine-calm-card">No DLP events logged for this machine.</div>
          )}
          {!dlpLoading && dlpData.length > 0 && (
            <div className="card machine-calm-card" style={{ padding: 0, overflow: 'hidden' }}>
              <table className="data-table machine-calm-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Risk</th>
                    <th>Rule Name</th>
                    <th>Destination</th>
                    <th>Action</th>
                    <th>File Path</th>
                  </tr>
                </thead>
                <tbody>
                  {dlpData.map((e) => (
                    <tr key={e.id}>
                      <td className="mono" style={{ fontSize: 11.5, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{new Date(e.timestamp).toLocaleString()}</td>
                      <td>
                        <span className={`badge ${e.risk_level === 'high' || e.risk_level === 'critical' ? 'badge-red' : 'badge-amber'}`} style={{ textTransform: 'uppercase', fontSize: 10 }}>
                          {e.risk_level}
                        </span>
                      </td>
                      <td style={{ fontWeight: 600, fontSize: 12 }}>{e.policy_rule_name || 'DLP Incident'}</td>
                      <td><span className="badge badge-gray">{e.destination_type || 'Endpoint'}</span></td>
                      <td><span style={{ fontWeight: 600, color: e.policy_action === 'block' ? 'var(--red)' : 'var(--brand)' }}>{e.policy_action || 'Logged'}</span></td>
                      <td className="mono" style={{ fontSize: 11.5, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={e.file_path}>{e.file_path || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ padding: 14, borderTop: '1px solid var(--border-0)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-3)' }}>Showing {dlpPage * 10 + 1}-{Math.min((dlpPage + 1) * 10, dlpTotal)} of {dlpTotal}</span>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <button className="btn btn-ghost btn-sm" disabled={dlpPage === 0} onClick={() => setDlpPage(p => p - 1)}>Prev</button>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--text-3)' }}>{dlpPage + 1} / {Math.ceil(dlpTotal / 10)}</span>
                    <button className="btn btn-ghost btn-sm" disabled={dlpPage >= Math.ceil(dlpTotal / 10) - 1} onClick={() => setDlpPage(p => p + 1)}>Next</button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'phishing' && (
        <div className="slide-in">
          {phishingLoading && <div className="loading-center"><div className="spinner" style={{ width: 28, height: 28 }} /></div>}
          {!phishingLoading && !phishingData.length && (
            <div className="empty-state machine-calm-card">No phishing events logged for this machine.</div>
          )}
          {!phishingLoading && phishingData.length > 0 && (
            <div className="card machine-calm-card" style={{ padding: 0, overflow: 'hidden' }}>
              <table className="data-table machine-calm-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Domain</th>
                    <th>Channel</th>
                    <th>URL</th>
                    <th>Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {phishingData.map((e) => (
                    <tr key={e.id}>
                      <td className="mono" style={{ fontSize: 11.5, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{new Date(e.timestamp).toLocaleString()}</td>
                      <td className="mono" style={{ fontSize: 12, fontWeight: 600, color: 'var(--red)' }}>{e.domain}</td>
                      <td><span className="badge badge-blue">{e.channel || 'Browser'}</span></td>
                      <td className="mono" style={{ fontSize: 11, maxWidth: 350, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={e.url}>{e.url}</td>
                      <td>
                        <span className="badge badge-red" style={{ fontSize: 10, fontWeight: 700 }}>
                          {e.verdict || 'SUSPICIOUS'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ padding: 14, borderTop: '1px solid var(--border-0)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-3)' }}>Showing {phishingPage * 10 + 1}-{Math.min((phishingPage + 1) * 10, phishingTotal)} of {phishingTotal}</span>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <button className="btn btn-ghost btn-sm" disabled={phishingPage === 0} onClick={() => setPhishingPage(p => p - 1)}>Prev</button>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--text-3)' }}>{phishingPage + 1} / {Math.ceil(phishingTotal / 10)}</span>
                    <button className="btn btn-ghost btn-sm" disabled={phishingPage >= Math.ceil(phishingTotal / 10) - 1} onClick={() => setPhishingPage(p => p + 1)}>Next</button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'files' && (
        <div className="slide-in">
          {fileLogsLoading && <div className="loading-center"><div className="spinner" style={{ width: 28, height: 28 }} /></div>}
          {!fileLogsLoading && !fileLogsData.length && (
            <div className="empty-state machine-calm-card">No file activity logged for this machine.</div>
          )}
          {!fileLogsLoading && fileLogsData.length > 0 && (
            <div className="card machine-calm-card" style={{ padding: 0, overflow: 'hidden' }}>
              <table className="data-table machine-calm-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Action</th>
                    <th>File Name</th>
                    <th>Size</th>
                    <th>Enterprise Label</th>
                  </tr>
                </thead>
                <tbody>
                  {fileLogsData.map((e) => (
                    <tr key={e.id}>
                      <td className="mono" style={{ fontSize: 11.5, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{new Date(e.timestamp).toLocaleString()}</td>
                      <td>
                        <span className={`badge ${e.action === 'create' ? 'badge-green' : e.action === 'delete' ? 'badge-red' : 'badge-amber'}`} style={{ fontSize: 11, textTransform: 'uppercase' }}>
                          {e.action}
                        </span>
                      </td>
                      <td style={{ fontWeight: 600, fontSize: 12 }}>
                        <div>{e.file_name}</div>
                        <div style={{ fontSize: 10.5, color: 'var(--text-3)', fontWeight: 400, marginTop: 2 }} className="mono">{e.file_path}</div>
                      </td>
                      <td className="mono" style={{ fontSize: 11.5 }}>{fmtBytes(e.file_size)}</td>
                      <td>
                        <span className={`badge ${e.enterprise_label ? 'badge-blue' : 'badge-gray'}`} style={{ fontSize: 10 }}>
                          {e.enterprise_label || 'Unlabeled'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ padding: 14, borderTop: '1px solid var(--border-0)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-3)' }}>Showing {fileLogsPage * 10 + 1}-{Math.min((fileLogsPage + 1) * 10, fileLogsTotal)} of {fileLogsTotal}</span>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <button className="btn btn-ghost btn-sm" disabled={fileLogsPage === 0} onClick={() => setFileLogsPage(p => p - 1)}>Prev</button>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--text-3)' }}>{fileLogsPage + 1} / {Math.ceil(fileLogsTotal / 10)}</span>
                    <button className="btn btn-ghost btn-sm" disabled={fileLogsPage >= Math.ceil(fileLogsTotal / 10) - 1} onClick={() => setFileLogsPage(p => p + 1)}>Next</button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'network' && (
        <div className="slide-in">
          {networkLogsLoading && <div className="loading-center"><div className="spinner" style={{ width: 28, height: 28 }} /></div>}
          {!networkLogsLoading && !networkLogsData.length && (
            <div className="empty-state machine-calm-card">No network activity logged for this machine.</div>
          )}
          {!networkLogsLoading && networkLogsData.length > 0 && (
            <div className="card machine-calm-card" style={{ padding: 0, overflow: 'hidden' }}>
              <table className="data-table machine-calm-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Open Ports</th>
                    <th>Connections</th>
                    <th>Sent</th>
                    <th>Received</th>
                  </tr>
                </thead>
                <tbody>
                  {networkLogsData.map((e) => (
                    <tr key={e.id}>
                      <td className="mono" style={{ fontSize: 11.5, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{new Date(e.timestamp).toLocaleString()}</td>
                      <td className="mono" style={{ color: 'var(--brand)', fontWeight: 700 }}>{e.listen_count || 0}</td>
                      <td className="mono" style={{ color: 'var(--success)', fontWeight: 700 }}>{e.conn_count || 0}</td>
                      <td className="mono">{fmtBytes(e.bytes_sent)}</td>
                      <td className="mono">{fmtBytes(e.bytes_recv)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ padding: 14, borderTop: '1px solid var(--border-0)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-3)' }}>Showing {networkLogsPage * 10 + 1}-{Math.min((networkLogsPage + 1) * 10, networkLogsTotal)} of {networkLogsTotal}</span>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <button className="btn btn-ghost btn-sm" disabled={networkLogsPage === 0} onClick={() => setNetworkLogsPage(p => p - 1)}>Prev</button>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--text-3)' }}>{networkLogsPage + 1} / {Math.ceil(networkLogsTotal / 10)}</span>
                    <button className="btn btn-ghost btn-sm" disabled={networkLogsPage >= Math.ceil(networkLogsTotal / 10) - 1} onClick={() => setNetworkLogsPage(p => p + 1)}>Next</button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'diagnostics' && (
        <div className="slide-in" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="grid-4">
            <DetailMetricCard
              icon={NetworkIcon}
              label="Queue Depth"
              value={fmtCount(queueHealth.queue_depth)}
              subtext={`${fmtCount(queueHealth.buffer_size)} buffered locally`}
              tone="brand"
            />
            <DetailMetricCard
              icon={ChartBarIcon}
              label="WS ACK Pending"
              value={fmtCount(queueHealth.ws_ack_pending)}
              subtext={health.ws_connected ? 'WebSocket transport live' : 'HTTP fallback or disconnected'}
              tone="sage"
            />
            <DetailMetricCard
              icon={TimeIcon}
              label="Retry / Error"
              value={`${fmtPct(queueHealth.retry_rate || 0)} / ${fmtPct(queueHealth.error_rate || 0)}`}
              subtext={`${fmtCount(queueHealth.ack_timeouts)} ACK timeouts`}
              tone="sand"
            />
            <DetailMetricCard
              icon={AverageHoursIcon}
              label="Self-Throttle"
              value={selfThrottleHealth.active ? 'Active' : 'Idle'}
              subtext={selfThrottleHealth.reason || `Sync every ${fmtCount(queueHealth.sync_interval_s)}s`}
              tone="slate"
            />
          </div>

          <div className="grid-2">
            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 16 }}>
                <div>
                  <div className="card-title">Queue Diagnostics</div>
                  <div className="stat-sub">Offline queue depth, retries, and delivery health from the agent heartbeat.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap">
                  <NetworkIcon size={18} />
                </span>
              </div>
              <div className="machine-calm-detail-grid">
                {[
                  ['Queue Depth', fmtCount(queueHealth.queue_depth), true],
                  ['Buffer Size', fmtCount(queueHealth.buffer_size), true],
                  ['ACK Pending', fmtCount(queueHealth.ws_ack_pending), true],
                  ['Backpressure', queueHealth.backpressure ? 'true' : 'false', false],
                  ['Sync Interval', `${fmtCount(queueHealth.sync_interval_s)} sec`, false],
                  ['Enqueued', fmtCount(queueHealth.enqueued), true],
                  ['Sent', fmtCount(queueHealth.sent), true],
                  ['Failed', fmtCount(queueHealth.failed), true],
                  ['Retried', fmtCount(queueHealth.retried), true],
                  ['Dropped', fmtCount(queueHealth.dropped), true],
                  ['WS Sent', fmtCount(queueHealth.ws_sent), true],
                  ['HTTP Sent', fmtCount(queueHealth.http_sent), true],
                  ['ACK Timeouts', fmtCount(queueHealth.ack_timeouts), true],
                  ['Partial Failures', fmtCount(queueHealth.partial_failures), true],
                ].map(([k, v, mono]) => (
                  <div key={k} className="machine-calm-detail-item">
                    <div className="machine-calm-detail-label">{k}</div>
                    <div className={mono ? 'mono machine-calm-detail-value' : 'machine-calm-detail-value'}>{v}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card machine-calm-card">
              <div className="card-header" style={{ marginBottom: 16 }}>
                <div>
                  <div className="card-title">Runtime Cadence</div>
                  <div className="stat-sub">The active performance profile currently applied on the endpoint.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap">
                  <TimeIcon size={18} />
                </span>
              </div>
              <div className="machine-calm-detail-grid">
                {[
                  ['Screenshot Interval', `${fmtCount(runtimeHealth.screenshot_interval_seconds)} sec`, false],
                  ['Browser Sync', `${fmtCount(runtimeHealth.browser_sync_interval_seconds)} sec`, false],
                  ['Heartbeat', `${fmtCount(runtimeHealth.heartbeat_interval_seconds)} sec`, false],
                  ['App Tracker', `${fmtCount(runtimeHealth.app_tracker_interval_seconds)} sec`, false],
                  ['Network Tracker', `${fmtCount(runtimeHealth.network_interval_seconds)} sec`, false],
                  ['USB Tracker', `${fmtCount(runtimeHealth.usb_interval_seconds)} sec`, false],
                  ['Print Tracker', `${fmtCount(runtimeHealth.print_interval_seconds)} sec`, false],
                  ['File Fast Sweep', `${fmtCount(runtimeHealth.file_cache_fast_sweep_seconds)} sec`, false],
                  ['File Recursive Sweep', `${fmtCount(runtimeHealth.file_cache_recursive_sweep_seconds)} sec`, false],
                  ['File Sweeper Enabled', runtimeHealth.file_cache_sweeper_enabled ? 'true' : 'false', false],
                  ['Configured Screenshot', `${fmtCount(runtimeHealth.configured_screenshot_interval_seconds)} sec`, false],
                  ['Configured Browser Sync', `${fmtCount(runtimeHealth.configured_browser_sync_interval_seconds)} sec`, false],
                  ['Configured Heartbeat', `${fmtCount(runtimeHealth.configured_heartbeat_interval_seconds)} sec`, false],
                  ['WebSocket Connected', health.ws_connected ? 'true' : 'false', false],
                  ['DLP Policy Version', fmtCount(policyHealth.dlp_policy_version), true],
                  ['Phishing Policy Version', fmtCount(policyHealth.phishing_policy_version), true],
                ].map(([k, v, mono]) => (
                  <div key={k} className="machine-calm-detail-item">
                    <div className="machine-calm-detail-label">{k}</div>
                    <div className={mono ? 'mono machine-calm-detail-value' : 'machine-calm-detail-value'}>{v}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card machine-calm-card" style={{ gridColumn: 'span 2' }}>
              <div className="card-header" style={{ marginBottom: 16 }}>
                <div>
                  <div className="card-title">Throttle Policy</div>
                  <div className="stat-sub">Automatic protection thresholds that temporarily slow expensive collectors on stressed endpoints.</div>
                </div>
                <span className="stat-icon-wrap machine-calm-icon-wrap">
                  <AverageHoursIcon size={18} />
                </span>
              </div>
              <div className="machine-calm-detail-grid">
                {[
                  ['Enabled', selfThrottleHealth.enabled ? 'true' : 'false', false],
                  ['Active', selfThrottleHealth.active ? 'true' : 'false', false],
                  ['Reason', selfThrottleHealth.reason || '--', false],
                  ['CPU Threshold', `${fmtCount(selfThrottleHealth.cpu_percent_threshold)}%`, false],
                  ['Memory Threshold', `${fmtCount(selfThrottleHealth.memory_percent_threshold)}%`, false],
                  ['Queue Threshold', fmtCount(selfThrottleHealth.queue_depth_threshold), true],
                  ['Multiplier', `${Number(selfThrottleHealth.interval_multiplier || 0).toFixed(1)}x`, false],
                  ['Cooldown', `${fmtCount(selfThrottleHealth.cooldown_seconds)} sec`, false],
                ].map(([k, v, mono]) => (
                  <div key={k} className="machine-calm-detail-item">
                    <div className="machine-calm-detail-label">{k}</div>
                    <div className={mono ? 'mono machine-calm-detail-value' : 'machine-calm-detail-value'}>{v}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
