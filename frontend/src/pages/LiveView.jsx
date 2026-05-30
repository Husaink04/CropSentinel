import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi, useWsContext, useWsListener } from '../hooks/useAuth'
import { useIceServers } from '../hooks/useIceServers'
import { usePageContext } from '../hooks/usePageContext'
import { RealtimeStatusBanner } from '../components/ui/RealtimeStatusBanner'
import { MachinesIcon, ChartLineIcon } from '../components/ui/OverviewIcons'
import { SESSION_MODES, useSessionMachineDirectory, useWebRtcSession } from '../features/sessions/sessionShared'

const RTC_OFFER_TIMEOUT_MS = 14_000
const JPEG_POLL_MS = 8_000

function Chip({ label, color, pulse = false }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px',
      borderRadius: 100, fontSize: 11, fontWeight: 700,
      background: `${color}1a`, border: `1px solid ${color}40`, color,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0,
        animation: pulse ? 'pulse 2s infinite' : 'none',
      }} />
      {label}
    </span>
  )
}

export default function LiveView() {
  const { get, post } = useApi()
  const { send: wsSend } = useWsContext()
  const { setPageContext, clearPageContext } = usePageContext()
  const [searchParams] = useSearchParams()
  const iceServers = useIceServers()
  const [activity, setActivity] = useState([])

  const {
    machines,
    selectedId,
    setSelectedId,
    refreshMachines,
    selectedRef,
  } = useSessionMachineDirectory(get, {
    initialSelectedId: searchParams.get('machine') || null,
    onlineOnly: true,
    pollMs: 20_000,
  })

  const {
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
    videoRef,
    realtimeStatus,
  } = useWebRtcSession({
    sessionKind: 'live',
    selectedId,
    selectedRef,
    wsSend,
    useWsListener,
    iceServers,
    offerTimeoutMs: RTC_OFFER_TIMEOUT_MS,
    jpegPollMs: JPEG_POLL_MS,
    beforeStart: (machineId, sessionKind) => post(`/api/sessions/machines/${machineId}/start`, { session_kind: sessionKind }),
    onMachinePresenceChange: () => { refreshMachines().catch(() => {}) },
    onAfterEnd: () => {
      setActivity([])
    },
    onMessage: (msg, ctx) => {
      const { type, machine_id } = msg
      if (machine_id !== ctx.currentId) return false
      if (type === 'machine_online') {
        if (ctx.modeRef.current === SESSION_MODES.UNSTABLE) {
          ctx.setModeSync(SESSION_MODES.IDLE)
          ctx.setErrorMsg('')
        }
        return false
      }
      if (type === 'app_update' || type === 'browser_update') {
        setActivity((items) => [
          { ...msg, ts: new Date().toLocaleTimeString() },
          ...items,
        ].slice(0, 40))
        return true
      }
      return false
    },
  })

  useEffect(() => {
    const label = selectedId ? `Machine ${selectedId.slice(0, 8)}` : 'No machine selected'
    setPageContext('Live Session', label)
    return () => clearPageContext()
  }, [selectedId, setPageContext, clearPageContext])

  const selectMachine = useCallback((machineId) => {
    if (machineId === selectedRef.current) return
    endSession()
    setSelectedId(machineId)
    setActivity([])
    setErrorMsg('')
  }, [endSession, selectedRef, setErrorMsg, setSelectedId])

  const selectedMachine = machines.find((item) => item.machine_id === selectedId)
  const isConnected = [SESSION_MODES.CONNECTED, SESSION_MODES.JPEG, SESSION_MODES.UNSTABLE].includes(mode)

  return (
    <div className="fade-in machine-calm-shell" style={{ display: 'flex', flexDirection: 'column', gap: 0, height: '100%' }}>
      <div className="page-header machine-calm-header" style={{ marginBottom: 16 }}>
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <ChartLineIcon size={24} />
          </div>
          <div>
            <div className="page-title">Live View</div>
            <div className="page-subtitle">
              {machines.length} machine{machines.length !== 1 ? 's' : ''} online
              {mode === SESSION_MODES.CONNECTED && rtcStats && ` · ${rtcStats.fps} fps · ${rtcStats.kbps} kbps`}
            </div>
          </div>
        </div>
        <div className="page-actions">
          {selectedId && !isConnected && mode !== SESSION_MODES.REQUESTING && (
            <button className="btn btn-primary machine-calm-primary" onClick={startSession}>Connect</button>
          )}
          {isConnected && (
            <button className="btn btn-outline machine-calm-btn" onClick={endSession}>Disconnect</button>
          )}
          {mode === SESSION_MODES.REQUESTING && (
            <button className="btn btn-outline machine-calm-btn" disabled>
              <span className="spinner" style={{ width: 13, height: 13, borderWidth: 2 }} /> Connecting...
            </button>
          )}
          {mode === SESSION_MODES.JPEG && (
            <>
              <button
                className={`btn ${liveJpeg ? 'btn-primary machine-calm-primary' : 'btn-outline machine-calm-btn'}`}
                onClick={() => setLiveJpeg((value) => !value)}
              >
                {liveJpeg ? 'Pause' : 'Auto (8s)'}
              </button>
              <button className="btn btn-outline machine-calm-btn" onClick={requestScreenshot}>Snapshot</button>
            </>
          )}
        </div>
      </div>

      <RealtimeStatusBanner
        status={realtimeStatus}
        message={errorMsg}
        onRetry={selectedId ? startSession : undefined}
      />

      <div className="session-layout">
        <div className="session-sidebar machine-calm-card">
          <div style={{
            padding: '12px 14px', borderBottom: '1px solid var(--border-0)',
            fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)',
            textTransform: 'uppercase', letterSpacing: '1px',
          }}>
            Online Machines
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {machines.length === 0 ? (
              <div className="empty-state" style={{ minHeight: 180, padding: '24px 14px' }}>
                <div className="empty-state-icon machine-calm-empty-icon"><MachinesIcon size={34} /></div>
                <div className="empty-state-title">No machines online</div>
              </div>
            ) : machines.map((machine) => (
              <div
                key={machine.machine_id}
                onClick={() => selectMachine(machine.machine_id)}
                className="session-machine-item"
                style={{
                  background: selectedId === machine.machine_id ? 'color-mix(in srgb, var(--machine-calm-1) 10%, transparent)' : 'transparent',
                  borderLeft: `3px solid ${selectedId === machine.machine_id ? 'var(--machine-calm-1)' : 'transparent'}`,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 2 }}>
                  <span className="dot-online" style={{ width: 6, height: 6 }} />
                  <span className="mono" style={{
                    fontSize: 12, fontWeight: 700,
                    color: selectedId === machine.machine_id ? 'var(--machine-calm-1)' : 'var(--text-1)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {machine.hostname}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginLeft: 13 }}>
                  {machine.username || machine.ip_address}
                </div>
                {machine.active_app && (
                  <div style={{
                    fontSize: 11, color: 'var(--success)', marginLeft: 13, marginTop: 2,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {machine.active_app}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="session-main">
          {selectedMachine && (
            <div className="session-topbar machine-calm-card">
              <span className="mono" style={{ fontSize: 13.5, fontWeight: 700 }}>{selectedMachine.hostname}</span>
              <span className="dot-online" />
              {mode === SESSION_MODES.CONNECTED && <Chip label="WebRTC LIVE" color="var(--success)" pulse />}
              {mode === SESSION_MODES.UNSTABLE && <Chip label="Unstable" color="var(--warning)" pulse />}
              {mode === SESSION_MODES.JPEG && liveJpeg && <Chip label="JPEG 8s" color="var(--warning)" pulse />}
              {mode === SESSION_MODES.JPEG && !liveJpeg && <Chip label="Paused" color="var(--text-3)" />}
              {mode === SESSION_MODES.REQUESTING && <Chip label="Connecting..." color="var(--brand)" pulse />}
              {mode === SESSION_MODES.ERROR && <Chip label="Error" color="var(--danger)" />}
              {rtcStats && mode === SESSION_MODES.CONNECTED && (
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
                  {rtcStats.fps} fps · {rtcStats.kbps} kbps{rtcStats.res ? ` · ${rtcStats.res}` : ''}
                </span>
              )}
              <span style={{ fontSize: 11, color: 'var(--text-3)', marginLeft: 'auto' }}>
                {selectedMachine.ip_address}
                {jpegTs && mode === SESSION_MODES.JPEG && ` · ${jpegTs.toLocaleTimeString()}`}
              </span>
            </div>
          )}

          <div className="session-viewer machine-calm-card">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              style={{
                maxWidth: '100%', maxHeight: '100%', objectFit: 'contain',
                display: (mode === SESSION_MODES.CONNECTED || mode === SESSION_MODES.UNSTABLE) ? 'block' : 'none',
              }}
            />

            {mode === SESSION_MODES.JPEG && jpegSrc && (
              <img
                src={`data:image/jpeg;base64,${jpegSrc}`}
                alt="screen"
                style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
              />
            )}

            {mode === SESSION_MODES.IDLE && !selectedId && (
              <div className="empty-state" style={{ minHeight: 300 }}>
                <div className="empty-state-icon machine-calm-empty-icon"><MachinesIcon size={42} /></div>
                <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-2)' }}>Select a machine</div>
                <div style={{ fontSize: 13, marginTop: 6 }}>Choose from the sidebar to start viewing</div>
              </div>
            )}

            {mode === SESSION_MODES.IDLE && selectedId && (
              <div className="empty-state" style={{ minHeight: 300 }}>
                <div className="empty-state-icon machine-calm-empty-icon"><ChartLineIcon size={42} /></div>
                <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-2)', marginBottom: 8 }}>
                  Ready to connect
                </div>
                <div style={{ fontSize: 13, marginBottom: 20 }}>
                  Click <strong style={{ color: 'var(--text-1)' }}>Connect</strong> to start a live session
                </div>
                <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
                  <div style={{
                    padding: '8px 14px', background: 'var(--brand-subtle)',
                    border: '1px solid var(--brand-glow)', borderRadius: 10, fontSize: 12, color: 'var(--brand)',
                  }}>
                    WebRTC live view
                  </div>
                  <div style={{
                    padding: '8px 14px', background: 'var(--surface-3)',
                    border: '1px solid var(--border-0)', borderRadius: 10, fontSize: 12, color: 'var(--text-3)',
                  }}>
                    JPEG fallback if direct stream is unavailable
                  </div>
                </div>
              </div>
            )}

            {mode === SESSION_MODES.REQUESTING && (
              <div className="empty-state" style={{ minHeight: 300 }}>
                <div className="spinner" style={{ width: 36, height: 36, borderWidth: 3, margin: '0 auto 16px' }} />
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-2)' }}>Negotiating...</div>
                <div style={{ fontSize: 12.5, marginTop: 6 }}>Waiting for agent to send WebRTC offer</div>
              </div>
            )}

            {mode === SESSION_MODES.JPEG && !jpegSrc && (
              <div className="empty-state" style={{ minHeight: 300 }}>
                <div className="spinner" style={{ width: 28, height: 28, borderWidth: 3, margin: '0 auto 12px' }} />
                <div style={{ fontSize: 13 }}>Waiting for screenshot...</div>
              </div>
            )}
          </div>

          <div className="session-feed machine-calm-card">
            <div style={{
              fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)',
              textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 8,
            }}>
              Activity Feed
            </div>
            <div style={{ overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {activity.length === 0 ? (
                <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Waiting for activity...</div>
              ) : activity.map((entry, index) => (
                <div key={`${entry.type}-${index}`} style={{ display: 'flex', gap: 10, fontSize: 12, alignItems: 'center' }}>
                  <span className="mono" style={{ fontSize: 10, color: 'var(--text-3)', minWidth: 64, flexShrink: 0 }}>
                    {entry.ts}
                  </span>
                  <span className={`badge ${entry.type === 'app_update' ? 'badge-blue' : 'badge-amber'}`} style={{ fontSize: 9 }}>
                    {entry.type === 'app_update' ? 'APP' : 'WEB'}
                  </span>
                  <span style={{ color: 'var(--text-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {entry.type === 'app_update' ? entry.data?.app_name : entry.data?.domain || entry.data?.title}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
