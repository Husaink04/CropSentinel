/**
 * CropSentinel — Remote Access  v5.0
 * ═══════════════════════════════
 * AnyDesk-like remote desktop with:
 *   • Raw keyboard (keydown/keyup) + legacy text mode toggle
 *   • Remote audio streaming (WebRTC audio track)
 *   • Bidirectional file transfer (DataChannel)
 *   • Full mouse + scroll control
 *   • System commands (REST)
 *   • JPEG fallback when WebRTC unavailable
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi, useAuth, useWsListener, useWsContext } from '../hooks/useAuth'
import { useIceServers } from '../hooks/useIceServers'
import { usePageContext } from '../hooks/usePageContext'
import { RealtimeStatusBanner } from '../components/ui/RealtimeStatusBanner'
import { MachinesIcon, AverageHoursIcon } from '../components/ui/OverviewIcons'
import { SESSION_MODES, mapRealtimeStatus, useSessionMachineDirectory, useWebRtcSession } from '../features/sessions/sessionShared'

const API_BASE       = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
const RTC_TIMEOUT_MS = 14_000
const JPEG_POLL_MS   = 8_000
const MOVE_THROTTLE  = 33
const FILE_CHUNK     = 65536   // 64 KB file transfer chunks

// ── SVG Icons ─────────────────────────────────────────────────────────────────
const IC = {
  lock:      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>,
  msg:       <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
  globe:     <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>,
  volOff:    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>,
  volOn:     <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>,
  sleep:     <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>,
  logout:    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>,
  clipboard: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/></svg>,
  keyboard:  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><line x1="6" y1="8" x2="6" y2="8"/><line x1="10" y1="8" x2="10" y2="8"/><line x1="14" y1="8" x2="14" y2="8"/><line x1="18" y1="8" x2="18" y2="8"/><line x1="6" y1="12" x2="6" y2="12"/><line x1="10" y1="12" x2="10" y2="12"/><line x1="14" y1="12" x2="14" y2="12"/><line x1="18" y1="12" x2="18" y2="12"/><line x1="8" y1="16" x2="16" y2="16"/></svg>,
  fullscreen:<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>,
  minimize:  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></svg>,
  play:      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="5 3 19 12 5 21 5 3"/></svg>,
  stop:      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>,
  x:         <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  upload:    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>,
  download:  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="8 17 12 21 16 17"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.88 18.09A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.29"/></svg>,
  file:      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>,
  audio:     <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>,
  audioOff:  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>,
  cad:       <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>,
}

// ── System actions (REST) ─────────────────────────────────────────────────────
const SYS_ACTIONS = [
  { id:'lock_screen',  icon:IC.lock,   label:'Lock' },
  { id:'show_message', icon:IC.msg,    label:'Message',  needsInput:true, ph:'Message…' },
  { id:'open_url',     icon:IC.globe,  label:'Open URL', needsInput:true, ph:'https://…' },
  { id:'mute_audio',   icon:IC.volOff, label:'Mute' },
  { id:'unmute_audio', icon:IC.volOn,  label:'Unmute' },
  { id:'sleep',        icon:IC.sleep,  label:'Sleep' },
  { id:'logout_user',  icon:IC.logout, label:'Logout' },
  { id:'ctrl_alt_del', icon:IC.cad,    label:'Ctrl+Alt+Del' },
]

const nowStr  = () => new Date().toLocaleTimeString('en-US',{ hour12:false })
const clamp   = (v,lo,hi) => Math.max(lo, Math.min(hi,v))
const fmtSize = (b) => b < 1024 ? `${b} B` : b < 1048576 ? `${(b/1024).toFixed(1)} KB` : `${(b/1048576).toFixed(1)} MB`

function Pill({ label, color, pulse }) {
  return (
    <span style={{ display:'inline-flex',alignItems:'center',gap:5,padding:'3px 10px',
      borderRadius:100,fontSize:11,fontWeight:700,
      background:`${color}18`,border:`1px solid ${color}38`,color }}>
      {pulse && <span style={{ width:6,height:6,borderRadius:'50%',background:color,
        animation:'pulse 2s infinite',flexShrink:0 }} />}
      {label}
    </span>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

export default function RemoteAccess() {
  const { token }          = useAuth()
  const { get, post }      = useApi()
  const { send: wsSend }   = useWsContext()
  const { setPageContext, clearPageContext } = usePageContext()
  const [searchParams] = useSearchParams()
  const iceServers         = useIceServers()

  const {
    machines,
    selectedId,
    setSelectedId,
    refreshMachines,
    selectedRef,
  } = useSessionMachineDirectory(get, {
    initialSelectedId: searchParams.get('machine') || null,
    onlineOnly: false,
    pollMs: 0,
  })

  // ── State ──
  const [machine,      setMachine]      = useState(null)
  const [inputOn,      setInputOn]      = useState(false)
  const [dcState,      setDcState]      = useState('closed')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [pendingAct,   setPendingAct]   = useState(null)
  const [inputVal,     setInputVal]     = useState('')
  const [sending,      setSending]      = useState(false)
  const [cmdLog,       setCmdLog]       = useState([])
  const [pasteText,    setPasteText]    = useState('')
  const [showPaste,    setShowPaste]    = useState(false)
  // Keyboard mode: 'raw' (keydown/keyup) or 'text' (legacy textarea)
  const [kbMode,       setKbMode]       = useState('raw')
  // Audio
  const [audioMuted,   setAudioMuted]   = useState(false)
  const [hasAudio,     setHasAudio]     = useState(false)
  // File transfer
  const [showFilePanel,setShowFilePanel]= useState(false)
  const [transfers,    setTransfers]    = useState([])   // { id, name, size, dir, progress, speed, status }
  const [dragOver,     setDragOver]     = useState(false)

  // ── Refs ──
  const inputOnRef    = useRef(false)
  const dcRef         = useRef(null)       // input DataChannel
  const ftDcRef       = useRef(null)       // file transfer DataChannel
  const audioRef      = useRef(null)
  const containerRef  = useRef(null)
  const textareaRef   = useRef(null)
  const heldBtns      = useRef(new Set())
  const heldKeys      = useRef(new Set())  // raw keyboard held keys
  const lastMove      = useRef(0)
  const scrollAcc     = useRef({ dy:0, dx:0, x:0, y:0 })
  const scrollRaf     = useRef(null)
  const inputBuf      = useRef([])
  const flushRaf      = useRef(null)
  const kbModeRef     = useRef('raw')
  const fileInputRef  = useRef(null)
  // File transfer receive state
  const ftReceive     = useRef({})         // { [id]: { chunks:[], name, size, received } }

  useEffect(() => { inputOnRef.current  = inputOn   }, [inputOn])
  useEffect(() => { kbModeRef.current   = kbMode    }, [kbMode])

  // ── Machine details ──
  useEffect(() => {
    if (!selectedId) return
    fetch(`${API_BASE}/api/machines/${selectedId}`,{ headers:{ Authorization:`Bearer ${token}` } })
      .then(r=>r.json()).then(setMachine).catch(()=>{})
  }, [selectedId, token])
  useEffect(() => {
    const label = selectedId ? `Machine ${selectedId.slice(0, 8)}` : 'No machine selected'
    setPageContext('Remote Session', label)
    return () => clearPageContext()
  }, [selectedId, setPageContext, clearPageContext])

  // ── Fullscreen ──
  useEffect(() => {
    const fn = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', fn)
    return () => document.removeEventListener('fullscreenchange', fn)
  }, [])

  // ── Focus textarea when input turns on (text mode) ──
  useEffect(() => {
    if (inputOn && kbMode === 'text') {
      setTimeout(() => textareaRef.current?.focus(), 50)
    }
  }, [inputOn, kbMode])

  // ── Audio mute toggle ──
  useEffect(() => {
    if (audioRef.current) audioRef.current.muted = audioMuted
  }, [audioMuted])

  const addLog = useCallback((type, action, detail='') =>
    setCmdLog((items) => [{ type, action, detail, ts: nowStr() }, ...items].slice(0, 60)),
  [])

  const {
    mode,
    errorMsg,
    setErrorMsg,
    rtcStats,
    jpegSrc,
    startSession,
    endSession,
    requestScreenshot,
    setModeSync,
    sessionRef,
    pcRef,
    videoRef,
    realtimeStatus,
  } = useWebRtcSession({
    sessionKind: 'remote',
    selectedId,
    selectedRef,
    wsSend,
    useWsListener,
    iceServers,
    offerTimeoutMs: RTC_TIMEOUT_MS,
    jpegPollMs: JPEG_POLL_MS,
    beforeStart: (machineId, sessionKind) => post(`/api/sessions/machines/${machineId}/start`, { session_kind: sessionKind }),
    onMachinePresenceChange: (msg) => {
      refreshMachines().catch(() => {})
      if (msg.type === 'machine_offline' && msg.machine_id === selectedRef.current) {
        setMachine((item) => (item ? { ...item, online: false } : item))
      }
    },
    onAfterEnd: () => {
      cancelAnimationFrame(scrollRaf.current)
      cancelAnimationFrame(flushRaf.current)
      releaseAll()
      releaseAllKeys()
      if (dcRef.current) { try { dcRef.current.close() } catch {} dcRef.current = null }
      if (ftDcRef.current) { try { ftDcRef.current.close() } catch {} ftDcRef.current = null }
      if (audioRef.current) audioRef.current.srcObject = null
      setInputOn(false)
      setDcState('closed')
      setHasAudio(false)
      setTransfers([])
      setShowFilePanel(false)
    },
    configurePeerConnection: ({ pc, setModeSync: setSessionMode }) => {
      const setupDC = (dc) => {
        dcRef.current = dc
        dc.onopen = () => { setDcState('open'); addLog('info', 'channel', 'Input channel open') }
        dc.onclose = () => { setDcState('closed'); addLog('info', 'channel', 'Channel closed') }
        dc.onerror = () => { setDcState('error'); addLog('error', 'channel', 'Channel error') }
      }

      const setupFTDC = (dc) => {
        ftDcRef.current = dc
        dc.binaryType = 'arraybuffer'
        dc.onopen = () => addLog('info', 'file', 'File transfer channel open')
        dc.onclose = () => { ftDcRef.current = null }
        dc.onmessage = (event) => handleFileMessage(event.data)
      }

      pc.ondatachannel = (event) => {
        if (event.channel.label === 'input') setupDC(event.channel)
        else if (event.channel.label === 'filetransfer') setupFTDC(event.channel)
      }

        return {
          onTrack: (event) => {
            if (event.track.kind === 'video') {
              if (videoRef.current) {
                videoRef.current.srcObject = event.streams?.[0] || new MediaStream([event.track])
                videoRef.current.play().catch(() => {})
                setSessionMode(SESSION_MODES.CONNECTED)
              }
              return
            }
            if (event.track.kind === 'audio') {
              setHasAudio(true)
              if (audioRef.current) {
                const stream = new MediaStream([event.track])
                audioRef.current.srcObject = stream
                audioRef.current.play().catch(() => {})
              }
            }
        },
      }
    },
    onMessage: (msg, ctx) => {
      if (msg.machine_id !== ctx.currentId) return false
      if (msg.type === 'remote_result') {
        addLog('result', msg.action, msg.detail || 'OK')
        return true
      }
      if (msg.type === 'machine_online' && ctx.modeRef.current === SESSION_MODES.UNSTABLE) {
        ctx.setModeSync(SESSION_MODES.IDLE)
        ctx.setErrorMsg('Machine reconnected. Click Connect to resume.')
      }
      return false
    },
  })

  const selectMachine = (id) => {
    if (id === selectedRef.current) return
    endSession()
    setSelectedId(id)
    setErrorMsg('')
    setCmdLog([])
  }

  // ══════════════════════════════════════════
  // DATACHANNEL SEND
  // ══════════════════════════════════════════

  const sendEvt = (payload) => {
    const dc = dcRef.current
    if (!dc || dc.readyState!=='open') return
    inputBuf.current.push(payload)
    if (!flushRaf.current) {
      flushRaf.current = requestAnimationFrame(() => {
        flushRaf.current = null
        const buf = inputBuf.current.splice(0, 50)
        if (!buf.length) return
        const dc2 = dcRef.current
        if (!dc2 || dc2.readyState!=='open') return
        buf.forEach(ev => {
          try { dc2.send(JSON.stringify(ev)) } catch {}
        })
      })
    }
  }

  const sendEvtDirect = (payload) => {
    const dc = dcRef.current
    if (!dc || dc.readyState!=='open') return
    try { dc.send(JSON.stringify(payload)) } catch {}
  }

  // ── Release held mouse buttons ──
  const releaseAll = () => {
    heldBtns.current.forEach(btn =>
      sendEvtDirect({ type:'mouseup', button:btn, x:0, y:0 })
    )
    heldBtns.current.clear()
  }

  // ── Release held keyboard keys ──
  const releaseAllKeys = () => {
    heldKeys.current.forEach(code =>
      sendEvtDirect({ type:'keyup', code, key:'' })
    )
    heldKeys.current.clear()
  }

  // ── Coordinate mapping ──
  const toScreen = (clientX, clientY) => {
    const vid = videoRef.current
    if (!vid) return { x:0, y:0 }
    const rect  = vid.getBoundingClientRect()
    const natW  = vid.videoWidth  || rect.width
    const natH  = vid.videoHeight || rect.height
    const scale = Math.min(rect.width/natW, rect.height/natH)
    const ox = (rect.width  - natW*scale) / 2
    const oy = (rect.height - natH*scale) / 2
    return {
      x: Math.round(clamp((clientX-rect.left-ox)/scale, 0, natW)),
      y: Math.round(clamp((clientY-rect.top -oy)/scale, 0, natH)),
    }
  }

  // ══════════════════════════════════════════
  // MOUSE EVENTS
  // ══════════════════════════════════════════

  const onPointerDown = (e) => {
    if (!inputOn) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    heldBtns.current.add(e.button)
    sendEvt({ type:'mousedown', button:e.button, ...toScreen(e.clientX, e.clientY) })
    // Focus container for raw keyboard, or textarea for text mode
    if (kbModeRef.current === 'raw') containerRef.current?.focus({ preventScroll:true })
    else textareaRef.current?.focus({ preventScroll:true })
  }

  const onPointerUp = (e) => {
    if (!inputOn) return
    try { e.currentTarget.releasePointerCapture(e.pointerId) } catch {}
    heldBtns.current.delete(e.button)
    sendEvt({ type:'mouseup', button:e.button, ...toScreen(e.clientX, e.clientY) })
  }

  const onPointerMove = (e) => {
    if (!inputOn) return
    const now = Date.now()
    if (now - lastMove.current < MOVE_THROTTLE) return
    lastMove.current = now
    sendEvtDirect({ type:'mousemove', ...toScreen(e.clientX, e.clientY) })
  }

  const onPointerLeave = () => { if (inputOn) releaseAll() }

  const onDblClick = (e) => {
    if (!inputOn) return
    sendEvt({ type:'dblclick', button:e.button, ...toScreen(e.clientX, e.clientY) })
  }

  // ── Scroll ──
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
        scrollAcc.current = { dy:0, dx:0, x:0, y:0 }
        const vy = Math.round(dy / 100)
        const vx = Math.round(dx / 100)
        if (vy !== 0) sendEvtDirect({ type:'scroll', dir: vy>0?'down':'up', amount:Math.abs(vy), x, y })
        if (vx !== 0) sendEvtDirect({ type:'scroll', dir: vx>0?'right':'left', amount:Math.abs(vx), x, y })
      })
    }
  }

  // ══════════════════════════════════════════
  // KEYBOARD — RAW MODE (keydown/keyup)
  // ══════════════════════════════════════════

  const onRawKeyDown = (e) => {
    if (!inputOnRef.current || kbModeRef.current !== 'raw') return
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
    if (!inputOnRef.current || kbModeRef.current !== 'raw') return
    e.preventDefault()
    e.stopPropagation()
    const code = e.code
    if (!code) return
    heldKeys.current.delete(code)
    sendEvt({ type: 'keyup', code, key: e.key })
  }

  // ══════════════════════════════════════════
  // KEYBOARD — TEXT MODE (legacy textarea)
  // ══════════════════════════════════════════

  // Special-key → command name (text mode only)
  const SPECIAL_KEY_COMMANDS = {
    'Enter':'enter','Backspace':'backspace','Delete':'delete','Tab':'tab',
    'Escape':'escape','ArrowUp':'up','ArrowDown':'down','ArrowLeft':'left',
    'ArrowRight':'right','Home':'home','End':'end','PageUp':'pageup',
    'PageDown':'pagedown','Insert':'insert',
    'F1':'f1','F2':'f2','F3':'f3','F4':'f4','F5':'f5','F6':'f6',
    'F7':'f7','F8':'f8','F9':'f9','F10':'f10','F11':'f11','F12':'f12',
    'PrintScreen':'printscreen','ScrollLock':'scrolllock','Pause':'pause',
    'CapsLock':'capslock','NumLock':'numlock',
  }

  const SHORTCUT_ACTIONS = {
    'a':'selectall','c':'copy','v':'paste','x':'cut',
    'z':'undo','y':'redo','Z':'redo',
    's':'save','p':'print','f':'find',
    'w':'closewindow','t':'newtab','n':'newwindow',
    'r':'reload','l':'focusbar','d':'bookmark',
  }

  const onTextareaInput = (e) => {
    if (!inputOnRef.current) return
    const text = e.target.value
    if (!text) return
    sendEvt({ type:'text', text })
    e.target.value = ''
  }

  const onTextareaKeyDown = (e) => {
    if (!inputOnRef.current) return
    if (e.ctrlKey || e.metaKey) {
      const action = SHORTCUT_ACTIONS[e.key] || SHORTCUT_ACTIONS[e.key?.toLowerCase()]
      if (action) { e.preventDefault(); sendEvt({ type:'shortcut', action }); return }
    }
    if (e.altKey && e.key.length === 1) {
      e.preventDefault(); sendEvt({ type:'shortcut', action:'alt_'+e.key.toLowerCase() }); return
    }
    const cmd = SPECIAL_KEY_COMMANDS[e.key]
    if (cmd) { e.preventDefault(); sendEvt({ type:'command', action:cmd }) }
  }

  const onTextareaKeyUp = () => {}

  // ══════════════════════════════════════════
  // FILE TRANSFER
  // ══════════════════════════════════════════

  const handleFileMessage = (data) => {
    if (data instanceof ArrayBuffer) {
      // Binary chunk: first 36 bytes = transfer ID (ASCII UUID), rest = chunk data
      const view = new Uint8Array(data)
      const id   = new TextDecoder().decode(view.slice(0, 36))
      const chunk = view.slice(36)
      const rx = ftReceive.current[id]
      if (!rx) return
      rx.chunks.push(chunk)
      rx.received += chunk.length
      const progress = Math.min(100, Math.round((rx.received / rx.size) * 100))
      setTransfers(prev => prev.map(t => t.id===id ? { ...t, progress, status:'receiving' } : t))
    } else {
      // JSON control message
      try {
        const msg = JSON.parse(data)
        if (msg.type === 'file_offer') {
          // Agent wants to send a file to admin
          const { id, name, size } = msg
          ftReceive.current[id] = { chunks:[], name, size, received:0 }
          setTransfers(prev => [...prev, { id, name, size, dir:'down', progress:0, speed:'', status:'receiving' }])
          setShowFilePanel(true)
          // Auto-accept
          ftDcRef.current?.send(JSON.stringify({ type:'file_accept', id }))
        } else if (msg.type === 'file_complete') {
          // Agent finished sending
          const { id, sha256 } = msg
          const rx = ftReceive.current[id]
          if (!rx) return
          const blob = new Blob(rx.chunks)
          const url  = URL.createObjectURL(blob)
          const a    = document.createElement('a')
          a.href = url; a.download = rx.name; a.click()
          URL.revokeObjectURL(url)
          delete ftReceive.current[id]
          setTransfers(prev => prev.map(t => t.id===id ? { ...t, progress:100, status:'done' } : t))
          addLog('info','file',`Received: ${rx.name}`)
        } else if (msg.type === 'file_accept') {
          // Agent accepted our file — start sending chunks
          sendFileChunks(msg.id)
        } else if (msg.type === 'file_reject') {
          setTransfers(prev => prev.map(t => t.id===msg.id ? { ...t, status:'rejected' } : t))
        } else if (msg.type === 'file_ack') {
          setTransfers(prev => prev.map(t => t.id===msg.id ? { ...t, progress:100, status:'done' } : t))
        }
      } catch {}
    }
  }

  // Pending files to send (queued after file_offer sent, awaiting file_accept)
  const pendingFiles = useRef({})

  const sendFileToAgent = async (file) => {
    const dc = ftDcRef.current
    if (!dc || dc.readyState !== 'open') {
      addLog('error','file','File transfer channel not open')
      return
    }
    const id = crypto.randomUUID()
    pendingFiles.current[id] = file
    setTransfers(prev => [...prev, { id, name:file.name, size:file.size, dir:'up', progress:0, speed:'', status:'pending' }])
    setShowFilePanel(true)
    dc.send(JSON.stringify({ type:'file_offer', id, name:file.name, size:file.size }))
  }

  const sendFileChunks = async (id) => {
    const file = pendingFiles.current[id]
    if (!file) return
    delete pendingFiles.current[id]
    const dc = ftDcRef.current
    if (!dc || dc.readyState !== 'open') return

    setTransfers(prev => prev.map(t => t.id===id ? { ...t, status:'sending' } : t))

    let offset = 0
    const total = file.size
    const hashBuf = []

    const sendNext = () => {
      if (offset >= total) {
        // Compute SHA-256 and send completion
        const allChunks = new Blob(hashBuf)
        allChunks.arrayBuffer().then(buf => {
          crypto.subtle.digest('SHA-256', buf).then(hash => {
            const hex = Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2,'0')).join('')
            dc.send(JSON.stringify({ type:'file_complete', id, sha256:hex }))
          })
        })
        return
      }

      // Backpressure: wait if buffer is full
      if (dc.bufferedAmount > 1048576) {
        setTimeout(sendNext, 50)
        return
      }

      const end = Math.min(offset + FILE_CHUNK, total)
      const slice = file.slice(offset, end)
      slice.arrayBuffer().then(buf => {
        const chunk = new Uint8Array(buf)
        hashBuf.push(new Blob([chunk]))
        // Build frame: 36-byte ID + chunk
        const idBytes = new TextEncoder().encode(id)
        const frame = new Uint8Array(36 + chunk.length)
        frame.set(idBytes, 0)
        frame.set(chunk, 36)
        dc.send(frame.buffer)

        offset = end
        const progress = Math.round((offset / total) * 100)
        setTransfers(prev => prev.map(t => t.id===id ? { ...t, progress, status:'sending' } : t))

        // Use setTimeout for next chunk to avoid blocking UI
        setTimeout(sendNext, 0)
      })
    }

    sendNext()
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

  // ══════════════════════════════════════════
  // INPUT TOGGLE + MISC
  // ══════════════════════════════════════════

  const toggleInput = (on) => {
    setInputOn(on)
    if (!on) { releaseAll(); releaseAllKeys() }
    else if (kbMode === 'raw') setTimeout(() => containerRef.current?.focus({ preventScroll:true }), 50)
    else setTimeout(() => textareaRef.current?.focus({ preventScroll:true }), 50)
  }

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) containerRef.current?.requestFullscreen?.()
    else document.exitFullscreen?.()
  }

  const sendPasteText = () => {
    if (!pasteText.trim()) return
    sendEvt({ type:'text', text:pasteText })
    addLog('info','type',`${pasteText.length} chars`)
    setPasteText(''); setShowPaste(false)
    if (kbMode === 'raw') containerRef.current?.focus({ preventScroll:true })
    else textareaRef.current?.focus({ preventScroll:true })
  }

  const pushClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText()
      sendEvt({ type:'text', text })
      addLog('info','clipboard',`${text.length} chars`)
    } catch { addLog('error','clipboard','Permission denied') }
  }

  // ── Remote commands ──
  const sendCommand = async (actionId, value='') => {
    setSending(true); addLog('sent',actionId,value)
    try {
      const res = await fetch(`${API_BASE}/api/remote/command`, {
        method:'POST',
        headers:{ 'Content-Type':'application/json', Authorization:`Bearer ${token}` },
        body:JSON.stringify({ machine_id:selectedRef.current, action:actionId, value }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail||'Failed')
      addLog('result',actionId,data.message||'OK')
    } catch(err) { addLog('error',actionId,err.message) }
    finally { setSending(false) }
  }

  const handleAction = (a) => {
    if (a.needsInput) { setPendingAct(a); setInputVal('') }
    else sendCommand(a.id)
  }

  // ── Derived ──
  const isConn = mode==='connected' || mode==='jpeg' || mode==='unstable'
  const sel    = machines.find(m => m.machine_id===selectedId)
  const dcOpen = dcState==='open'

  // ══════════════════════════════════════════
  // RENDER
  // ══════════════════════════════════════════

  return (
    <div className="fade-in machine-calm-shell" style={{ display:'flex', flexDirection:'column', gap:0, height:'100%' }}>
      <div className="page-header machine-calm-header" style={{ marginBottom:16 }}>
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <AverageHoursIcon size={24} />
          </div>
          <div>
            <div className="page-title">Remote Access</div>
            <div className="page-subtitle">
              {machines.filter((item) => item.online).length} machines online
              {mode==='connected' && rtcStats ? ` · ${rtcStats.fps} fps · ${rtcStats.kbps} kbps` : ''}
            </div>
          </div>
        </div>
        <div className="page-actions">
          {!isConn && mode!=='requesting' && sel?.online && (
            <button className="btn btn-primary machine-calm-primary" onClick={startSession} style={{ display:'flex', alignItems:'center', gap:6 }}>
              {IC.play} Connect
            </button>
          )}
          {(isConn||mode==='requesting') && (
            <button className="btn btn-outline machine-calm-btn" onClick={endSession} style={{ display:'flex', alignItems:'center', gap:6 }}>
              {IC.stop} Disconnect
            </button>
          )}
          {isConn && (
            <button className="btn btn-outline machine-calm-btn" onClick={toggleFullscreen} style={{ display:'flex', alignItems:'center', gap:6 }}>
              {isFullscreen ? IC.minimize : IC.fullscreen}
              {isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
            </button>
          )}
        </div>
      </div>

      {/* ── Sidebar ── */}
      <div className="session-layout">
      <div className="session-sidebar" style={{ gap:10 }}>

        {/* Machine list */}
        <div className="machine-calm-card" style={{ overflow:'hidden', maxHeight:280 }}>
          <div style={{ padding:'11px 14px', borderBottom:'1px solid var(--border-0)',
            fontSize:10.5, fontWeight:700, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'1px' }}>
            Machines
          </div>
          <div style={{ overflowY:'auto', maxHeight:230 }}>
            {machines.length===0
              ? <div className="empty-state" style={{ minHeight:140, padding:'24px 14px' }}><div className="empty-state-icon machine-calm-empty-icon"><MachinesIcon size={34} /></div><div className="empty-state-title">No machines</div></div>
              : machines.map(m => (
                <div key={m.machine_id} onClick={() => selectMachine(m.machine_id)} className="session-machine-item" style={{
                  background:selectedId===m.machine_id?'color-mix(in srgb, var(--machine-calm-1) 10%, transparent)':'transparent',
                  borderLeft:`3px solid ${selectedId===m.machine_id?'var(--machine-calm-1)':'transparent'}`,
                }}>
                  <div style={{ display:'flex', alignItems:'center', gap:7, marginBottom:2 }}>
                    <span className={m.online?'dot-online':'dot-offline'} style={{ width:6,height:6 }} />
                    <span className="mono" style={{ fontSize:12,fontWeight:700,
                      color:selectedId===m.machine_id?'var(--machine-calm-1)':'var(--text-1)',
                      overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap' }}>
                      {m.hostname}
                    </span>
                  </div>
                  <div style={{ fontSize:11,color:'var(--text-3)',marginLeft:13 }}>
                    {m.username||m.ip_address}
                  </div>
                </div>
              ))
            }
          </div>
        </div>

        {/* Machine details */}
        {machine && (
          <div className="machine-calm-card" style={{ padding:'12px 14px' }}>
            <div style={{ fontSize:10.5,fontWeight:700,color:'var(--text-3)',
              textTransform:'uppercase',letterSpacing:'1px',marginBottom:9 }}>Details</div>
            {[
              ['OS', `${machine.os} ${machine.os_version||''}`.trim()],
              ['IP', machine.ip_address],
              ['CPU',`${Math.round(machine.cpu_percent||0)}%`],
              ['RAM',`${Math.round(machine.memory_percent||0)}%`],
              ['App',machine.active_app||'—'],
            ].map(([k,v]) => (
              <div key={k} style={{ display:'flex',justifyContent:'space-between',marginBottom:6,fontSize:12 }}>
                <span style={{ color:'var(--text-3)',flexShrink:0 }}>{k}</span>
                <span style={{ color:'var(--text-2)',maxWidth:110,overflow:'hidden',
                  textOverflow:'ellipsis',whiteSpace:'nowrap',textAlign:'right' }}>{v}</span>
              </div>
            ))}
          </div>
        )}

        {/* Log */}
        <div className="session-feed machine-calm-card" style={{ flex:1, minHeight:80, overflow:'hidden' }}>
          <div style={{ fontSize:10.5,fontWeight:700,color:'var(--text-3)',
            textTransform:'uppercase',letterSpacing:'1px',marginBottom:8,
            display:'flex',justifyContent:'space-between',alignItems:'center' }}>
            Log
            {cmdLog.length>0 && (
              <button className="btn btn-ghost btn-sm" onClick={() => setCmdLog([])} style={{ background:'none',border:'none',
                color:'var(--text-3)',cursor:'pointer',fontSize:11, padding:0, minHeight:'auto' }}>clear</button>
            )}
          </div>
          <div style={{ overflowY:'auto',flex:1,display:'flex',flexDirection:'column',gap:3 }}>
            {cmdLog.length===0
              ? <div style={{ fontSize:11,color:'var(--text-3)' }}>No activity</div>
              : cmdLog.map((e,i) => (
                <div key={i} style={{ fontSize:11,display:'flex',gap:5,alignItems:'flex-start' }}>
                  <span className="mono" style={{ color:'var(--text-3)',minWidth:50,fontSize:10,flexShrink:0 }}>{e.ts}</span>
                  <span style={{ fontWeight:700,fontSize:10,flexShrink:0,
                    color:e.type==='error'?'var(--danger)':e.type==='result'?'var(--success)':'var(--machine-calm-1)' }}>
                    {e.type==='sent'?'\u2192':e.type==='result'?'\u2713':'\u2139'}
                  </span>
                  <span style={{ color:'var(--text-2)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap' }}>
                    {e.action}{e.detail?` \u2014 ${e.detail}`:''}
                  </span>
                </div>
              ))
            }
          </div>
        </div>
      </div>

      {/* ── Main panel ── */}
      <div className="session-main">

        {/* Toolbar */}
        <div className="session-topbar machine-calm-card" style={{ padding:'8px 14px' }}>

          <span className="mono" style={{ fontSize:13,fontWeight:700 }}>
            {sel?.hostname||'Select a machine'}
          </span>
          {sel?.online && <span className="dot-online" />}
          {mode==='connected'  && <Pill label="WebRTC LIVE" color="var(--success)" pulse />}
          {mode==='unstable'   && <Pill label="Unstable" color="var(--warning)" pulse />}
          {mode==='jpeg'       && <Pill label="Screenshot" color="var(--warning)" pulse />}
          {mode==='requesting' && <Pill label="Connecting\u2026" color="var(--brand)" pulse />}
          {mode==='error'      && <Pill label="Error" color="var(--danger)" />}
          {inputOn && dcOpen   && <Pill label={`${kbMode==='raw'?'Raw':'Text'} Input ON`} color="var(--purple)" />}
          {hasAudio && <Pill label={audioMuted?'Audio OFF':'Audio ON'} color={audioMuted?'var(--text-3)':'var(--success)'} />}
          {rtcStats && mode==='connected' && (
            <span style={{ fontSize:11,color:'var(--text-3)' }}>
              {rtcStats.fps} fps \u00b7 {rtcStats.kbps} kbps{rtcStats.res?` \u00b7 ${rtcStats.res}`:''}
            </span>
          )}

          <div style={{ marginLeft:'auto',display:'flex',gap:6,alignItems:'center',flexWrap:'wrap' }}>
            {mode==='connected' && (
              <>
                {/* Keyboard mode toggle */}
                <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setKbMode(m => m==='raw'?'text':'raw')}
                  title={kbMode==='raw'?'Switch to Text mode (IME/emoji)':'Switch to Raw mode (all keys)'}
                  style={{ display:'flex',alignItems:'center',gap:5 }}>
                  {IC.keyboard} {kbMode==='raw'?'Raw KB':'Text KB'}
                </button>

                {/* Audio toggle */}
                {hasAudio && (
                  <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setAudioMuted(m=>!m)}
                    title={audioMuted?'Unmute remote audio':'Mute remote audio'}
                    style={{ display:'flex',alignItems:'center',gap:5 }}>
                    {audioMuted ? IC.audioOff : IC.audio}
                  </button>
                )}

                {/* Clipboard */}
                <button className="btn btn-outline machine-calm-btn btn-sm" onClick={pushClipboard}
                  disabled={!dcOpen} title="Push clipboard to remote"
                  style={{ display:'flex',alignItems:'center',gap:5 }}>
                  {IC.clipboard} Clip
                </button>

                {/* Type text */}
                <button className={`btn btn-sm ${showPaste ? 'btn-primary machine-calm-primary' : 'btn-outline machine-calm-btn'}`}
                  onClick={() => setShowPaste(p=>!p)} title="Type text on remote"
                  style={{ display:'flex',alignItems:'center',gap:5 }}>
                  {IC.keyboard} Type
                </button>

                {/* File transfer */}
                <button className={`btn btn-sm ${showFilePanel ? 'btn-primary machine-calm-primary' : 'btn-outline machine-calm-btn'}`}
                  onClick={() => setShowFilePanel(p=>!p)} title="File transfer"
                  style={{ display:'flex',alignItems:'center',gap:5,
                    color:showFilePanel?'var(--brand)':'inherit' }}>
                  {IC.file} Files
                </button>

                {/* Input enable */}
                <label style={{ display:'flex',alignItems:'center',gap:6,fontSize:12,
                  cursor:'pointer',userSelect:'none',
                  color:inputOn?'var(--purple)':'var(--text-3)',
                  padding:'4px 10px',borderRadius:'var(--r-md)',
                  background:inputOn?'var(--purple-subtle)':'transparent',
                  border:`1px solid ${inputOn?'rgba(139,92,246,.35)':'transparent'}`,
                  transition:'all .15s' }}>
                  <input type="checkbox" checked={inputOn}
                    onChange={e => toggleInput(e.target.checked)}
                    style={{ accentColor:'var(--purple)',width:14,height:14 }} />
                  Input
                </label>
              </>
            )}
            {isConn && (
              <button className="btn btn-outline machine-calm-btn btn-sm" onClick={toggleFullscreen}
                style={{ display:'flex',alignItems:'center',gap:5 }}>
                {isFullscreen ? IC.minimize : IC.fullscreen}
                {isFullscreen ? 'Exit' : 'Full'}
              </button>
            )}
            {!isConn && mode!=='requesting' && sel?.online && (
              <button className="btn btn-primary machine-calm-primary btn-sm" onClick={startSession}
                style={{ display:'flex',alignItems:'center',gap:5 }}>
                {IC.play} Connect
              </button>
            )}
            {(isConn||mode==='requesting') && (
              <button className="btn btn-outline machine-calm-btn btn-sm" onClick={endSession}
                style={{ display:'flex',alignItems:'center',gap:5 }}>
                {IC.stop} Disconnect
              </button>
            )}
          </div>
        </div>

        {/* Type text row */}
        {showPaste && mode==='connected' && (
          <div className="machine-calm-card" style={{ display:'flex',gap:8,alignItems:'center',padding:'8px 14px' }}>
            <span style={{ fontSize:12,color:'var(--text-3)',flexShrink:0 }}>Type on remote:</span>
            <input className="input-field" style={{ flex:1 }} value={pasteText}
              onChange={e => setPasteText(e.target.value)}
              onKeyDown={e => { e.stopPropagation(); if(e.key==='Enter') sendPasteText() }}
              placeholder="Text to type on remote machine\u2026" autoFocus />
            <button className="btn btn-primary machine-calm-primary btn-sm"
              onClick={sendPasteText} disabled={!pasteText.trim()||!dcOpen}>Send</button>
            <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setShowPaste(false)}>{IC.x}</button>
          </div>
        )}

        {/* File Transfer Panel */}
        {showFilePanel && mode==='connected' && (
          <div className="machine-calm-card" style={{ padding:'12px 14px' }}>
            <div style={{ display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:10 }}>
              <div style={{ fontSize:10.5,fontWeight:700,color:'var(--text-3)',
                textTransform:'uppercase',letterSpacing:'1px' }}>File Transfer</div>
              <button className="btn btn-outline machine-calm-btn btn-sm" onClick={() => setShowFilePanel(false)}
                style={{ padding:2 }}>{IC.x}</button>
            </div>

            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onFileDrop}
              onClick={() => fileInputRef.current?.click()}
              style={{
                border:`2px dashed ${dragOver?'var(--brand)':'var(--border-1)'}`,
                borderRadius:'var(--r-md)', padding:'20px 14px', textAlign:'center',
                cursor:'pointer', transition:'all .15s',
                background:dragOver?'var(--brand-subtle)':'transparent',
              }}>
              <div style={{ display:'flex',justifyContent:'center',marginBottom:6,
                color:dragOver?'var(--brand)':'var(--text-3)' }}>
                {IC.upload}
              </div>
              <div style={{ fontSize:12,color:dragOver?'var(--brand)':'var(--text-3)' }}>
                Drop files here or click to browse
              </div>
              <input ref={fileInputRef} type="file" multiple onChange={onFileSelect}
                style={{ display:'none' }} />
            </div>

            {/* Transfer list */}
            {transfers.length > 0 && (
              <div style={{ marginTop:10,display:'flex',flexDirection:'column',gap:6 }}>
                {transfers.map(t => (
                  <div key={t.id} style={{ display:'flex',alignItems:'center',gap:8,
                    padding:'8px 10px',background:'var(--surface-3)',borderRadius:'var(--r-sm)',
                    border:'1px solid var(--border-0)' }}>
                    <span style={{ color:t.dir==='up'?'var(--brand)':'var(--success)',flexShrink:0 }}>
                      {t.dir==='up' ? IC.upload : IC.download}
                    </span>
                    <div style={{ flex:1,minWidth:0 }}>
                      <div style={{ fontSize:12,fontWeight:600,color:'var(--text-1)',
                        overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap' }}>
                        {t.name}
                      </div>
                      <div style={{ display:'flex',alignItems:'center',gap:8,marginTop:3 }}>
                        <div style={{ flex:1,height:4,background:'var(--surface-0)',borderRadius:2,overflow:'hidden' }}>
                          <div style={{ width:`${t.progress}%`,height:'100%',borderRadius:2,transition:'width .2s',
                            background:t.status==='done'?'var(--success)':
                              t.status==='rejected'?'var(--danger)':'var(--brand)' }} />
                        </div>
                        <span style={{ fontSize:10,color:'var(--text-3)',flexShrink:0 }}>
                          {t.progress}% \u00b7 {fmtSize(t.size)}
                        </span>
                      </div>
                    </div>
                    <span style={{ fontSize:10,fontWeight:700,flexShrink:0,
                      color:t.status==='done'?'var(--success)':
                        t.status==='rejected'?'var(--danger)':
                        t.status==='sending'||t.status==='receiving'?'var(--brand)':'var(--text-3)' }}>
                      {t.status==='done'?'Done':t.status==='rejected'?'Rejected':
                       t.status==='sending'?'Sending':t.status==='receiving'?'Receiving':'Pending'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Error */}
        <RealtimeStatusBanner
          status={realtimeStatus}
          message={errorMsg}
          onRetry={sel?.online ? startSession : undefined}
        />
        {errorMsg && mode === 'error' && (
            <div className="machine-calm-card" style={{ padding:'9px 14px',borderRadius:'var(--r-md)',fontSize:12.5,
              background:'var(--warning-subtle)',border:'1px solid rgba(245,166,35,.25)',
              color:'var(--warning)',display:'flex',gap:8,alignItems:'center' }}>
            {errorMsg}
            <button onClick={() => setErrorMsg('')} style={{ marginLeft:'auto',background:'none',
              border:'none',color:'inherit',cursor:'pointer' }}>{IC.x}</button>
          </div>
        )}

        {/* ════════════════════════════════════════
            SCREEN VIEWER
            ════════════════════════════════════════ */}
        <div
          ref={containerRef}
          tabIndex={0}
          className="session-viewer machine-calm-card"
          style={{
            flex:1, background:'#000', position:'relative', minHeight:300,
            borderRadius: isFullscreen?0:'var(--r-xl)',
            border: isFullscreen?'none':`2px solid ${inputOn&&dcOpen?'var(--purple)':'var(--border-0)'}`,
            overflow:'hidden', outline:'none',
            cursor: inputOn ? 'crosshair' : 'default',
            transition:'border-color .2s',
            userSelect:'none', touchAction:'none',
          }}
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          onPointerMove={onPointerMove}
          onPointerLeave={onPointerLeave}
          onDoubleClick={onDblClick}
          onWheel={onWheel}
          onKeyDown={onRawKeyDown}
          onKeyUp={onRawKeyUp}
          onContextMenu={e => { if(inputOn) e.preventDefault() }}
        >
          {/* Hidden textarea for text mode keyboard input */}
          {kbMode === 'text' && (
            <textarea
              ref={textareaRef}
              defaultValue=""
              autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
              onInput={onTextareaInput}
              onKeyDown={onTextareaKeyDown}
              onKeyUp={onTextareaKeyUp}
              onBlur={() => {
                if (inputOnRef.current && kbModeRef.current === 'text') {
                  setTimeout(() => {
                    const tag = document.activeElement?.tagName
                    if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'BUTTON' && tag !== 'SELECT')
                      textareaRef.current?.focus({ preventScroll:true })
                  }, 100)
                }
              }}
              style={{
                position:'absolute', left:'-9999px', top:0,
                width:1, height:1, opacity:0,
                pointerEvents:'none', resize:'none', border:'none', padding:0, margin:0,
              }}
            />
          )}

          {/* Audio element (hidden) */}
          <audio ref={audioRef} autoPlay style={{ display:'none' }} />

          {/* Video */}
          <video ref={videoRef} autoPlay playsInline muted style={{
            width:'100%', height:'100%', objectFit:'contain',
            display:mode==='connected'?'block':'none',
            pointerEvents:'none', background:'#000',
          }} />

          {/* JPEG */}
          {mode==='jpeg' && jpegSrc && (
            <img src={`data:image/jpeg;base64,${jpegSrc}`} alt="screen"
              style={{ width:'100%',height:'100%',objectFit:'contain',
                pointerEvents:'none',display:'block' }} />
          )}

          {/* Idle */}
          {mode==='idle' && (
            <div style={{ position:'absolute',inset:0,display:'flex',flexDirection:'column',
              alignItems:'center',justifyContent:'center',color:'var(--text-3)',padding:24,background:'var(--surface-0)' }}>
              <div style={{ marginBottom:14,opacity:.4 }}>{IC.fullscreen}</div>
              <div style={{ fontSize:15,fontWeight:600,color:'var(--text-2)' }}>
                {!sel?'Select a machine':!sel.online?'Machine is offline':'Ready to connect'}
              </div>
              {sel?.online && (
                <div style={{ display:'flex',gap:10,justifyContent:'center',marginTop:16,flexWrap:'wrap' }}>
                  <div style={{ padding:'7px 13px',background:'var(--brand-subtle)',
                    border:'1px solid var(--brand-glow)',borderRadius:10,fontSize:12,color:'var(--brand)' }}>
                    WebRTC P2P — full keyboard + mouse + audio + files
                  </div>
                  <div style={{ padding:'7px 13px',background:'var(--surface-3)',
                    border:'1px solid var(--border-0)',borderRadius:10,fontSize:12,color:'var(--text-3)' }}>
                    Screenshot fallback if WebRTC unavailable
                  </div>
                </div>
              )}
            </div>
          )}

          {mode==='requesting' && (
            <div style={{ position:'absolute',inset:0,display:'flex',flexDirection:'column',
              alignItems:'center',justifyContent:'center',background:'var(--surface-0)',color:'var(--text-3)' }}>
              <div className="spinner" style={{ width:36,height:36,borderWidth:3,marginBottom:16 }} />
              <div style={{ fontSize:14,fontWeight:600,color:'var(--text-2)' }}>Negotiating WebRTC\u2026</div>
            </div>
          )}

          {mode==='jpeg' && !jpegSrc && (
            <div style={{ position:'absolute',inset:0,display:'flex',flexDirection:'column',
              alignItems:'center',justifyContent:'center',background:'var(--surface-0)',color:'var(--text-3)' }}>
              <div className="spinner" style={{ width:28,height:28,borderWidth:3,marginBottom:12 }} />
              <div style={{ fontSize:13 }}>Waiting for screenshot\u2026</div>
            </div>
          )}

          {/* Live badge */}
          {mode==='connected' && (
            <div style={{ position:'absolute',top:12,left:12,display:'flex',alignItems:'center',gap:6,
              background:'rgba(15,201,125,.2)',border:'1px solid rgba(15,201,125,.45)',
              color:'var(--success)',padding:'4px 12px',borderRadius:100,
              fontSize:11,fontWeight:700,backdropFilter:'blur(6px)',pointerEvents:'none' }}>
              <span style={{ width:6,height:6,borderRadius:'50%',background:'var(--success)',animation:'pulse 2s infinite' }} />
              WebRTC LIVE
            </div>
          )}

          {/* Input badge */}
          {inputOn && dcOpen && (
            <div style={{ position:'absolute',top:12,right:12,
              background:'rgba(139,92,246,.22)',border:'1px solid rgba(139,92,246,.45)',
              color:'var(--purple)',padding:'4px 12px',borderRadius:100,
              fontSize:11,fontWeight:700,backdropFilter:'blur(6px)',pointerEvents:'none' }}>
              {kbMode==='raw' ? 'Raw Keyboard Active' : 'Text Input Active'}
            </div>
          )}

          {/* Fullscreen hint */}
          {isFullscreen && (
            <div style={{ position:'absolute',bottom:16,left:'50%',transform:'translateX(-50%)',
              background:'rgba(0,0,0,.5)',color:'rgba(255,255,255,.7)',
              padding:'5px 14px',borderRadius:100,fontSize:11,pointerEvents:'none' }}>
              Press Esc to exit fullscreen
            </div>
          )}
        </div>

        {/* System commands */}
        <div className="machine-calm-card" style={{ padding:'10px 14px' }}>
          <div style={{ fontSize:10.5,fontWeight:700,color:'var(--text-3)',
            textTransform:'uppercase',letterSpacing:'1px',marginBottom:9 }}>
            System Commands {!sel?.online && <span style={{ color:'var(--danger)',marginLeft:6 }}>· Offline</span>}
          </div>
          <div style={{ display:'flex',gap:8,flexWrap:'wrap' }}>
            {SYS_ACTIONS.map(a => (
              <button key={a.id} onClick={() => handleAction(a)}
                className="btn btn-outline machine-calm-btn btn-sm"
                disabled={!sel?.online||sending} title={a.id.replace(/_/g,' ')}
                style={{ display:'flex',alignItems:'center',gap:6,padding:'7px 13px',
                  background:'var(--surface-3)',color:'var(--text-2)',
                  cursor:'pointer',fontSize:12,fontWeight:500,fontFamily:'Inter,sans-serif',
                  transition:'all .15s',opacity:(!sel?.online||sending)?.4:1 }}
                onMouseEnter={e => { if(sel?.online) e.currentTarget.style.borderColor='var(--machine-calm-1)' }}
                onMouseLeave={e => { e.currentTarget.style.borderColor='var(--border-0)' }}>
                <span style={{ display:'flex',alignItems:'center' }}>{a.icon}</span> {a.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      </div>

      {/* Modal */}
      {pendingAct && (
        <div style={{ position:'fixed',inset:0,background:'rgba(0,0,0,.65)',
          display:'flex',alignItems:'center',justifyContent:'center',zIndex:1000,padding:20 }}>
          <div style={{ background:'var(--surface-3)',border:'1px solid var(--border-1)',
            borderRadius:20,padding:28,width:'100%',maxWidth:400,boxShadow:'var(--shadow-lg)' }}>
            <div style={{ display:'flex',alignItems:'center',gap:8,marginBottom:8 }}>
              <span style={{ display:'flex' }}>{pendingAct.icon}</span>
              <span style={{ fontSize:16,fontWeight:700 }}>{pendingAct.label}</span>
            </div>
            <div style={{ fontSize:13,color:'var(--text-3)',marginBottom:18 }}>Enter value</div>
            <div className="form-group">
              <input className="input-field" value={inputVal}
                onChange={e => setInputVal(e.target.value)}
                onKeyDown={e => { e.stopPropagation(); if(e.key==='Enter'&&inputVal.trim()) { sendCommand(pendingAct.id,inputVal); setPendingAct(null) } }}
                placeholder={pendingAct.ph} autoFocus />
            </div>
            <div style={{ display:'flex',gap:10,marginTop:18,justifyContent:'flex-end' }}>
              <button className="btn btn-ghost" onClick={() => setPendingAct(null)}>Cancel</button>
              <button className="btn btn-primary" disabled={!inputVal.trim()}
                onClick={() => { sendCommand(pendingAct.id,inputVal); setPendingAct(null) }}>
                Send
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
