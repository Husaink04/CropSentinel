import React from 'react'

const MODE_META = {
  connecting: { tone: 'info', text: 'Connecting to remote session...' },
  connected: { tone: 'success', text: 'Connected.' },
  reconnecting: { tone: 'warning', text: 'Connection unstable. Reconnecting...' },
  degraded: { tone: 'warning', text: 'Running in degraded mode (JPEG fallback).' },
  disconnected: { tone: 'danger', text: 'Disconnected.' },
  permission_denied: { tone: 'danger', text: 'Permission denied for remote session.' },
}

export function RealtimeStatusBanner({ status, message, onRetry }) {
  const meta = MODE_META[status]
  if (!meta) return null
  if (status === 'connected') return null
  return (
    <div className={`ui-inline-banner ui-inline-banner-${meta.tone}`} role="status">
      <div className="ui-inline-banner-copy">
        <strong>Realtime Status</strong>
        <span>{message || meta.text}</span>
      </div>
      {onRetry && (status === 'disconnected' || status === 'reconnecting' || status === 'degraded') && (
        <div className="ui-inline-banner-actions">
          <button className="btn btn-ghost btn-sm" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}
    </div>
  )
}
