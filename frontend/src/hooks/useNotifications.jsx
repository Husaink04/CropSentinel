/**
 * CropSentinel — Notification Centre
 * ══════════════════════════════════
 * Problem
 * ───────
 * The old `addToast` in App.jsx queued inline toasts that disappeared after
 * 4.5s. If the user was looking away, they missed the message — and there
 * was no way to go back and read recent alerts.
 *
 * This module provides:
 *
 *  • `NotificationProvider` — a context that both replaces the old toast
 *    queue and persists a bounded history (50 items) in localStorage so
 *    recent notifications survive a page reload.
 *
 *  • `useNotifications()` — exposes:
 *        push({ title, message, type, meta })   → add toast + history entry
 *        remove(id)                              → dismiss a live toast
 *        markAllRead() / markRead(id)            → badge management
 *        clear()                                 → wipe history
 *        toasts[]                                → currently-visible items
 *        history[]                               → full history (newest first)
 *        unreadCount                             → for the topbar bell badge
 *
 * The provider is mounted inside `WebSocketProvider` in main.jsx so any page
 * — customer dashboard or platform portal — can push notifications.
 */

import React, {
  createContext, useContext, useState, useCallback, useEffect, useMemo, useRef,
} from 'react'
import { useAuth } from './useAuth'

const STORAGE_KEY_PREFIX = 'croppro_notifications_v1'
const MAX_HISTORY = 50
const TOAST_TTL_MS = 4500
const SCOPE_WATCH_KEYS = new Set([
  'croppro_token',
  'croppro_user',
  'croppro_platform_token',
  'croppro_platform_user',
])

const NotificationContext = createContext(null)

// ── Valid notification types (drives styling only) ───────────────────────────
const TYPES = new Set(['info', 'success', 'warning', 'error', 'alert'])

function readJsonStorage(key) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function resolveScopeFromSession(user, token) {
  // Customer-portal session (tenant-bound, fail-closed to "customer:unknown")
  if (token) {
    const storedUser = user || readJsonStorage('croppro_user')
    const tenantId = storedUser?.tenant_id
    return tenantId != null ? `customer:${tenantId}` : 'customer:unknown'
  }

  // Platform-portal session (tenant-bound if impersonating/scope present)
  const platformToken = localStorage.getItem('croppro_platform_token')
  if (platformToken) {
    const platformUser = readJsonStorage('croppro_platform_user')
    const tenantId = platformUser?.tenant_id
    return tenantId != null ? `platform:${tenantId}` : 'platform:global'
  }

  return 'anon'
}

function storageKeyForScope(scope) {
  return `${STORAGE_KEY_PREFIX}:${scope}`
}

function loadHistory(scope) {
  try {
    const raw = localStorage.getItem(storageKeyForScope(scope))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(entry => entry?.scope === scope)
      .slice(0, MAX_HISTORY)
  } catch {
    return []
  }
}

function saveHistory(scope, history) {
  try {
    localStorage.setItem(storageKeyForScope(scope), JSON.stringify(history.slice(0, MAX_HISTORY)))
  } catch {
    // Storage may be full or blocked (private mode) — ignore.
  }
}

export function NotificationProvider({ children }) {
  const auth = useAuth()
  const user = auth?.user || null
  const token = auth?.token || null
  const [scope, setScope] = useState(() => resolveScopeFromSession(user, token))
  const [toasts, setToasts]   = useState([])        // currently-visible
  const [history, setHistory] = useState(() => loadHistory(scope))
  const timersRef = useRef(new Map())

  // Keep scope synced with auth/session state; tenant boundary changes must clear visible toasts.
  useEffect(() => {
    const syncScope = () => {
      const next = resolveScopeFromSession(user, token)
      setScope(prev => (prev === next ? prev : next))
    }
    syncScope()

    const onStorage = (event) => {
      if (!event.key || SCOPE_WATCH_KEYS.has(event.key)) syncScope()
    }
    window.addEventListener('storage', onStorage)

    // Same-tab localStorage writes do not emit storage events.
    const interval = window.setInterval(syncScope, 1500)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.clearInterval(interval)
    }
  }, [user, token])

  // When scope changes, load scoped history and clear live toasts from old scope.
  useEffect(() => {
    setHistory(loadHistory(scope))
    setToasts([])
    timersRef.current.forEach(id => clearTimeout(id))
    timersRef.current.clear()
  }, [scope])

  // Persist current scope history whenever it changes.
  useEffect(() => { saveHistory(scope, history) }, [scope, history])

  // Clear all timers on unmount.
  useEffect(() => {
    const timers = timersRef.current
    return () => { timers.forEach(id => clearTimeout(id)); timers.clear() }
  }, [])

  const remove = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
    const timer = timersRef.current.get(id)
    if (timer) { clearTimeout(timer); timersRef.current.delete(id) }
  }, [])

  /**
   * Push a notification.
   *   @param {object} opts
   *   @param {string} opts.title    - short headline (required)
   *   @param {string} [opts.message] - longer detail
   *   @param {'info'|'success'|'warning'|'error'|'alert'} [opts.type='info']
   *   @param {boolean} [opts.persist=false] - skip toast, history only
   *   @param {number}  [opts.ttl=4500] - toast dismiss in ms (0 = sticky)
   *   @param {object}  [opts.meta] - arbitrary data (e.g. machine_id, url)
   */
  const push = useCallback((opts) => {
    const {
      title, message = '', type = 'info',
      persist = false, ttl = TOAST_TTL_MS, meta = null,
    } = typeof opts === 'string' ? { title: opts } : (opts || {})

    if (!title) return null
    const t = TYPES.has(type) ? type : 'info'
    const id = `n_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
    const now = new Date().toISOString()
    const entry = { id, title, message, type: t, meta, ts: now, read: false, scope }

    // Add to history (newest first, bounded).
    setHistory(prev => [entry, ...prev].slice(0, MAX_HISTORY))

    // Show as toast unless persist-only.
    if (!persist) {
      setToasts(prev => [...prev.slice(-4), entry])  // sliding window of 5
      if (ttl > 0) {
        const timer = setTimeout(() => remove(id), ttl)
        timersRef.current.set(id, timer)
      }
    }

    return id
  }, [remove, scope])

  const markRead = useCallback((id) => {
    setHistory(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))
  }, [])

  const markAllRead = useCallback(() => {
    setHistory(prev => prev.map(n => n.read ? n : { ...n, read: true }))
  }, [])

  const clear = useCallback(() => {
    setHistory([])
    setToasts([])
    timersRef.current.forEach(id => clearTimeout(id))
    timersRef.current.clear()
  }, [])

  const unreadCount = useMemo(
    () => history.reduce((n, x) => n + (x.read ? 0 : 1), 0),
    [history],
  )

  const value = useMemo(() => ({
    toasts, history, unreadCount,
    push, remove, markRead, markAllRead, clear,
  }), [toasts, history, unreadCount, push, remove, markRead, markAllRead, clear])

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  )
}

export function useNotifications() {
  const ctx = useContext(NotificationContext)
  if (!ctx) {
    // Safe fallback so components work even if provider is absent (tests etc).
    return {
      toasts: [], history: [], unreadCount: 0,
      push: () => null, remove: () => {}, markRead: () => {},
      markAllRead: () => {}, clear: () => {},
    }
  }
  return ctx
}
