import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export const SESSION_MODES = Object.freeze({
  IDLE: 'idle',
  REQUESTING: 'requesting',
  CONNECTED: 'connected',
  JPEG: 'jpeg',
  UNSTABLE: 'unstable',
  ERROR: 'error',
})

export function mapRealtimeStatus(mode, errorMessage) {
  if (mode === SESSION_MODES.REQUESTING) return 'connecting'
  if (mode === SESSION_MODES.CONNECTED) return 'connected'
  if (mode === SESSION_MODES.UNSTABLE) return 'reconnecting'
  if (mode === SESSION_MODES.JPEG) return 'degraded'
  if (mode === SESSION_MODES.ERROR && /permission/i.test(errorMessage || '')) return 'permission_denied'
  return 'disconnected'
}

export function useSessionMachineDirectory(get, {
  initialSelectedId = null,
  onlineOnly = false,
  pollMs = 0,
} = {}) {
  const [machines, setMachines] = useState([])
  const [selectedId, setSelectedId] = useState(initialSelectedId)
  const selectedRef = useRef(initialSelectedId)

  useEffect(() => {
    selectedRef.current = selectedId
  }, [selectedId])

  const refreshMachines = useCallback(async () => {
    const all = await get('/api/machines')
    const next = onlineOnly ? all.filter((item) => item.online) : all
    setMachines(next)
    if (!selectedRef.current && next.length > 0) {
      setSelectedId(next[0].machine_id)
    }
    return next
  }, [get, onlineOnly])

  useEffect(() => {
    refreshMachines().catch(() => {})
    if (!pollMs) return undefined
    const timer = setInterval(() => { refreshMachines().catch(() => {}) }, pollMs)
    return () => clearInterval(timer)
  }, [pollMs, refreshMachines])

  return {
    machines,
    selectedId,
    setSelectedId,
    refreshMachines,
    selectedRef,
  }
}

export function useWebRtcSession({
  sessionKind,
  selectedId,
  selectedRef,
  wsSend,
  useWsListener,
  iceServers,
  offerTimeoutMs,
  jpegPollMs,
  onMessage,
  configurePeerConnection,
  onMachinePresenceChange,
  onAfterEnd,
  beforeStart,
} = {}) {
  const [mode, setMode] = useState(SESSION_MODES.IDLE)
  const [errorMsg, setErrorMsg] = useState('')
  const [rtcStats, setRtcStats] = useState(null)
  const [jpegSrc, setJpegSrc] = useState(null)
  const [jpegTs, setJpegTs] = useState(null)
  const [liveJpeg, setLiveJpeg] = useState(false)

  const sessionRef = useRef(null)
  const pcRef = useRef(null)
  const videoRef = useRef(null)
  const offerTimer = useRef(null)
  const jpegTimer = useRef(null)
  const statsTimer = useRef(null)
  const modeRef = useRef(SESSION_MODES.IDLE)
  const iceRestartAttemptsRef = useRef(0)

  const setModeSync = useCallback((nextMode) => {
    modeRef.current = nextMode
    setMode(nextMode)
  }, [])

  const teardown = useCallback(() => {
    clearTimeout(offerTimer.current)
    clearInterval(statsTimer.current)
    if (pcRef.current) {
      try { pcRef.current.close() } catch {}
      pcRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
    setRtcStats(null)
  }, [])

  const requestScreenshot = useCallback(() => {
    if (selectedRef.current) {
      wsSend({ type: 'request_screenshot', machine_id: selectedRef.current })
    }
  }, [selectedRef, wsSend])

  const startJpeg = useCallback(() => {
    setModeSync(SESSION_MODES.JPEG)
    setLiveJpeg(true)
    requestScreenshot()
    clearInterval(jpegTimer.current)
    jpegTimer.current = setInterval(requestScreenshot, jpegPollMs)
  }, [jpegPollMs, requestScreenshot, setModeSync])

  const handleIce = useCallback(async (candidate) => {
    if (!pcRef.current || !candidate) return
    try {
      await pcRef.current.addIceCandidate(new RTCIceCandidate(candidate))
    } catch {}
  }, [])

  const attemptIceRestart = useCallback(async (pc) => {
    if (!pc || !sessionRef.current) {
      teardown()
      setModeSync(SESSION_MODES.ERROR)
      setErrorMsg('Connection lost.')
      startJpeg()
      return
    }
    if (iceRestartAttemptsRef.current >= 3) {
      iceRestartAttemptsRef.current = 0
      teardown()
      setModeSync(SESSION_MODES.ERROR)
      setErrorMsg('WebRTC could not recover. Switched to screenshot mode.')
      startJpeg()
      return
    }
    iceRestartAttemptsRef.current += 1
    try {
      const offer = await pc.createOffer({ iceRestart: true })
      await pc.setLocalDescription(offer)
      wsSend({
        type: 'webrtc_answer',
        session_id: sessionRef.current,
        sdp: {
          type: pc.localDescription.type,
          sdp: pc.localDescription.sdp,
        },
        ice_restart: true,
      })
      setErrorMsg('Reconnecting… (ICE restart)')
    } catch {
      teardown()
      setModeSync(SESSION_MODES.ERROR)
      setErrorMsg('ICE restart failed.')
      startJpeg()
    }
  }, [setModeSync, startJpeg, teardown, wsSend])

  const handleOffer = useCallback(async (sdpObj) => {
    try {
      const pc = new RTCPeerConnection({ iceServers })
      pcRef.current = pc

      const hooks = configurePeerConnection?.({
        pc,
        videoRef,
        sessionRef,
        setModeSync,
        setErrorMsg,
        setRtcStats,
        teardown,
        startJpeg,
        wsSend,
      }) || {}

      pc.ontrack = (event) => {
        if (hooks.onTrack) {
          hooks.onTrack(event)
          return
        }
        if (event.track.kind === 'video' && videoRef.current) {
          const stream = event.streams?.[0] || new MediaStream([event.track])
          videoRef.current.srcObject = stream
          videoRef.current.play().catch(() => {})
          setModeSync(SESSION_MODES.CONNECTED)
        }
      }

      pc.onicecandidate = (event) => {
        if (!event.candidate) return
        wsSend({
          type: 'webrtc_ice_admin',
          session_id: sessionRef.current,
          candidate: {
            sdpMid: event.candidate.sdpMid,
            sdpMLineIndex: event.candidate.sdpMLineIndex,
            candidate: event.candidate.candidate,
          },
        })
      }

      pc.onconnectionstatechange = () => {
        const state = pc.connectionState
        const handled = hooks.onConnectionStateChange?.(state)
        if (handled === false) return
        if (state === 'failed') {
          attemptIceRestart(pc)
        } else if (['disconnected', 'closed'].includes(state) && modeRef.current === SESSION_MODES.CONNECTED) {
          setModeSync(SESSION_MODES.UNSTABLE)
          setErrorMsg('Connection interrupted — attempting ICE restart…')
          attemptIceRestart(pc)
        }
      }

      statsTimer.current = setInterval(async () => {
        if (!pcRef.current) return
        try {
          const stats = await pcRef.current.getStats()
          let fps = 0
          let kbps = 0
          let res = ''
          stats.forEach((row) => {
            if (row.type === 'inbound-rtp' && row.kind === 'video') {
              fps = Math.round(row.framesPerSecond || 0)
              kbps = Math.round(((row.bytesReceived || 0) * 8) / 1000)
              res = row.frameWidth ? `${row.frameWidth}x${row.frameHeight}` : ''
            }
          })
          setRtcStats({ fps, kbps, res })
        } catch {}
      }, 2000)

      await pc.setRemoteDescription(new RTCSessionDescription(sdpObj))
      const answer = await pc.createAnswer()
      await pc.setLocalDescription(answer)
      wsSend({
        type: 'webrtc_answer',
        session_id: sessionRef.current,
        sdp: {
          type: pc.localDescription.type,
          sdp: pc.localDescription.sdp,
        },
      })
    } catch (error) {
      teardown()
      setModeSync(SESSION_MODES.ERROR)
      setErrorMsg(`WebRTC setup failed: ${error.message}`)
      startJpeg()
    }
  }, [attemptIceRestart, configurePeerConnection, iceServers, setModeSync, startJpeg, teardown, wsSend])

  const endSession = useCallback(() => {
    if (sessionRef.current) {
      wsSend({ type: 'webrtc_end', session_id: sessionRef.current })
    }
    teardown()
    clearInterval(jpegTimer.current)
    iceRestartAttemptsRef.current = 0
    sessionRef.current = null
    setModeSync(SESSION_MODES.IDLE)
    setErrorMsg('')
    onAfterEnd?.()
  }, [onAfterEnd, setModeSync, teardown, wsSend])

  const startSession = useCallback(() => {
    if (!selectedRef.current) return
    const machineId = selectedRef.current
    setModeSync(SESSION_MODES.REQUESTING)
    setErrorMsg('')
    sessionRef.current = null
    Promise.resolve(beforeStart?.(machineId, sessionKind))
      .then(() => {
        wsSend({
          type: 'webrtc_request',
          machine_id: machineId,
          session_kind: sessionKind,
        })
      })
      .catch((error) => {
        setModeSync(SESSION_MODES.ERROR)
        setErrorMsg(error?.message || 'Session preflight failed.')
      })
  }, [beforeStart, selectedRef, sessionKind, setModeSync, wsSend])

  useEffect(() => {
    if (mode !== SESSION_MODES.JPEG) return undefined
    clearInterval(jpegTimer.current)
    if (liveJpeg) {
      requestScreenshot()
      jpegTimer.current = setInterval(requestScreenshot, jpegPollMs)
    }
    return () => clearInterval(jpegTimer.current)
  }, [jpegPollMs, liveJpeg, mode, requestScreenshot])

  useWsListener(useCallback((msg) => {
    const { type, machine_id, session_id } = msg
    const currentId = selectedRef.current

    if (type === 'machine_online' || type === 'machine_offline') {
      onMachinePresenceChange?.(msg)
      if (type === 'machine_offline' && machine_id === currentId) {
        teardown()
        clearInterval(jpegTimer.current)
        setModeSync(SESSION_MODES.IDLE)
        setJpegSrc(null)
      }
      return
    }
    if (type === 'machine_unstable' && machine_id === currentId) {
      setErrorMsg('Agent connection unstable — waiting for reconnect…')
      if (modeRef.current === SESSION_MODES.CONNECTED || modeRef.current === SESSION_MODES.JPEG) {
        setModeSync(SESSION_MODES.UNSTABLE)
      }
      return
    }
    if (type === 'screenshot' && machine_id === currentId) {
      setJpegSrc(msg.image_data)
      setJpegTs(new Date())
      return
    }
    if (onMessage?.(msg, {
      currentId,
      modeRef,
      sessionRef,
      setModeSync,
      setErrorMsg,
      setJpegSrc,
      setJpegTs,
      startJpeg,
      handleOffer,
      handleIce,
      teardown,
    })) {
      return
    }
    if (type === 'webrtc_session_created' && machine_id === currentId) {
      sessionRef.current = msg.session_id
      clearTimeout(offerTimer.current)
      offerTimer.current = setTimeout(() => {
        setModeSync(SESSION_MODES.ERROR)
        setErrorMsg('Agent timed out — no WebRTC offer received.')
        startJpeg()
      }, offerTimeoutMs)
      return
    }
    if (type === 'webrtc_error' && machine_id === currentId) {
      clearTimeout(offerTimer.current)
      teardown()
      setModeSync(SESSION_MODES.ERROR)
      setErrorMsg(msg.message || 'WebRTC unavailable on this agent.')
      startJpeg()
      return
    }
    if (!sessionRef.current || session_id !== sessionRef.current) return
    if (type === 'webrtc_offer') {
      clearTimeout(offerTimer.current)
      handleOffer(msg.sdp)
      return
    }
    if (type === 'webrtc_ice_agent') {
      handleIce(msg.candidate)
      return
    }
    if (type === 'webrtc_ended') {
      teardown()
      setModeSync(SESSION_MODES.IDLE)
      return
    }
  }, [handleIce, handleOffer, offerTimeoutMs, onMachinePresenceChange, onMessage, selectedRef, setModeSync, startJpeg, teardown, useWsListener]))

  useEffect(() => () => {
    teardown()
    clearInterval(jpegTimer.current)
  }, [teardown])

  const realtimeStatus = useMemo(
    () => mapRealtimeStatus(mode, errorMsg),
    [errorMsg, mode],
  )

  return {
    mode,
    errorMsg,
    setErrorMsg,
    rtcStats,
    jpegSrc,
    jpegTs,
    liveJpeg,
    setLiveJpeg,
    startSession,
    endSession,
    requestScreenshot,
    startJpeg,
    setModeSync,
    sessionRef,
    pcRef,
    videoRef,
    realtimeStatus,
  }
}
