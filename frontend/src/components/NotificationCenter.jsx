/**
 * CropSentinel — Notification UI
 * ══════════════════════════════
 * Two pieces share the same context:
 *
 *   • <NotificationToasts /> — floating toast stack, mount once near the
 *     root. Auto-dismisses via the provider's TTL.
 *
 *   • <NotificationBell />   — topbar bell button with unread badge.
 *     Clicking opens a dropdown showing the full history (newest first),
 *     with "Mark all read" and "Clear" actions.
 */

import { useState, useRef, useEffect } from 'react'
import { useNotifications } from '../hooks/useNotifications'

// ── Shared palette ───────────────────────────────────────────────────────────
const TYPE_COLORS = {
  info:    { bg: 'rgba(59,130,246,0.12)',  border: 'rgba(59,130,246,0.35)',  fg: '#60a5fa', icon: 'i' },
  success: { bg: 'rgba(34,197,94,0.12)',   border: 'rgba(34,197,94,0.35)',   fg: '#4ade80', icon: '✓' },
  warning: { bg: 'rgba(245,158,11,0.12)',  border: 'rgba(245,158,11,0.35)',  fg: '#fbbf24', icon: '!' },
  error:   { bg: 'rgba(239,68,68,0.12)',   border: 'rgba(239,68,68,0.35)',   fg: '#f87171', icon: '×' },
  alert:   { bg: 'rgba(168,85,247,0.12)',  border: 'rgba(168,85,247,0.35)',  fg: '#c084fc', icon: '⚡' },
}

function formatRelative(iso) {
  const ms = Date.now() - new Date(iso).getTime()
  const s = Math.floor(ms / 1000)
  if (s < 60)     return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60)     return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24)     return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

// ═══════════════════════════════════════════════════════════════════════════
// TOAST STACK
// ═══════════════════════════════════════════════════════════════════════════
export function NotificationToasts() {
  const { toasts, remove } = useNotifications()

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      style={{
        position: 'fixed',
        bottom: 20,
        right: 20,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        zIndex: 9999,
        pointerEvents: 'none',
        maxWidth: 'min(92vw, 380px)',
      }}
    >
      {toasts.map(t => {
        const c = TYPE_COLORS[t.type] || TYPE_COLORS.info
        return (
          <div
            key={t.id}
            role="status"
            style={{
              pointerEvents: 'auto',
              padding: '12px 14px',
              borderRadius: 10,
              background: 'var(--surface-2)',
              border: `1px solid ${c.border}`,
              boxShadow: 'var(--shadow-lg)',
              display: 'flex',
              gap: 10,
              alignItems: 'flex-start',
              fontFamily: "'Inter', system-ui, sans-serif",
              color: 'var(--text-1)',
              animation: 'toast-in .18s ease-out',
            }}
          >
            <div
              aria-hidden="true"
              style={{
                width: 22, height: 22, borderRadius: 6, flexShrink: 0,
                background: c.bg, color: c.fg, fontWeight: 700, fontSize: 13,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >{c.icon}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.3 }}>{t.title}</div>
              {t.message && (
                <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2, lineHeight: 1.4 }}>
                  {t.message}
                </div>
              )}
            </div>
            <button
              onClick={() => remove(t.id)}
              aria-label="Dismiss notification"
              style={{
                background: 'transparent', border: 'none', cursor: 'pointer',
                color: 'var(--text-2)', fontSize: 16, padding: 0,
                lineHeight: 1, marginTop: 2,
              }}
            >×</button>
          </div>
        )
      })}
      <style>{`
        @keyframes toast-in {
          from { transform: translateY(8px); opacity: 0 }
          to   { transform: translateY(0);   opacity: 1 }
        }
      `}</style>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════
// BELL + PANEL
// ═══════════════════════════════════════════════════════════════════════════
export function NotificationBell({ buttonStyle }) {
  const { history, unreadCount, markAllRead, markRead, clear } = useNotifications()
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = () => {
    setOpen(v => {
      const next = !v
      // Mark all read when the panel opens.
      if (next && unreadCount > 0) markAllRead()
      return next
    })
  }

  return (
    <div ref={rootRef} style={{ position: 'relative' }}>
      <button
        onClick={toggle}
        aria-label={unreadCount > 0 ? `${unreadCount} unread notifications` : 'Notifications'}
        aria-expanded={open}
        aria-haspopup="true"
        style={{
          position: 'relative',
          background: 'transparent',
          border: '1px solid var(--border-0)',
          borderRadius: 8,
          padding: '6px 10px',
          cursor: 'pointer',
          color: 'var(--text-2)',
          fontSize: 16,
          lineHeight: 1,
          ...buttonStyle,
        }}
      >
        <span aria-hidden="true">🔔</span>
        {unreadCount > 0 && (
          <span
            aria-hidden="true"
            style={{
              position: 'absolute',
              top: -4, right: -4,
              background: '#ef4444',
              color: '#fff',
              fontSize: 10,
              fontWeight: 700,
              minWidth: 16,
              height: 16,
              padding: '0 4px',
              borderRadius: 8,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '2px solid var(--bg, #0a0e1a)',
            }}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          style={{
            position: 'absolute',
            top: 'calc(100% + 8px)',
            right: 0,
            width: 360,
            maxWidth: '92vw',
            maxHeight: 460,
            display: 'flex',
            flexDirection: 'column',
            background: 'var(--surface-2)',
            border: '1px solid var(--border-0)',
            borderRadius: 12,
            boxShadow: 'var(--shadow-lg)',
            zIndex: 1000,
            overflow: 'hidden',
            fontFamily: "'Inter', system-ui, sans-serif",
          }}
        >
          <div
            style={{
              padding: '12px 14px',
              borderBottom: '1px solid var(--border-0)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-1)' }}>
              Notifications
            </div>
            <button
              onClick={clear}
              disabled={history.length === 0}
              style={{
                background: 'transparent', border: 'none', cursor: history.length ? 'pointer' : 'default',
                color: history.length ? 'var(--text-2)' : 'var(--text-3)',
                fontSize: 12, padding: 0,
                opacity: history.length ? 1 : 0.4,
              }}
            >
              Clear all
            </button>
          </div>

          <div style={{ flex: 1, overflowY: 'auto' }}>
            {history.length === 0 ? (
              <div style={{
                padding: '36px 20px', textAlign: 'center',
                fontSize: 13, color: 'var(--text-2)',
              }}>
                No notifications yet
              </div>
            ) : (
              history.map(n => {
                const c = TYPE_COLORS[n.type] || TYPE_COLORS.info
                return (
                  <button
                    key={n.id}
                    onClick={() => markRead(n.id)}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      display: 'flex',
                      gap: 10,
                      padding: '12px 14px',
                      background: n.read ? 'transparent' : 'var(--brand-subtle)',
                      border: 'none',
                      borderBottom: '1px solid var(--border-0)',
                      cursor: 'pointer',
                      color: 'var(--text-1)',
                    }}
                  >
                    <div
                      aria-hidden="true"
                      style={{
                        width: 22, height: 22, borderRadius: 6, flexShrink: 0,
                        background: c.bg, color: c.fg, fontWeight: 700, fontSize: 13,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                    >{c.icon}</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        display: 'flex', justifyContent: 'space-between', gap: 6,
                      }}>
                        <div style={{
                          fontSize: 13, fontWeight: n.read ? 500 : 700,
                          color: 'var(--text-1)',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>{n.title}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-2)', flexShrink: 0 }}>
                          {formatRelative(n.ts)}
                        </div>
                      </div>
                      {n.message && (
                        <div style={{
                          fontSize: 12, color: 'var(--text-2)', marginTop: 2,
                          lineHeight: 1.4, wordBreak: 'break-word',
                        }}>{n.message}</div>
                      )}
                    </div>
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
