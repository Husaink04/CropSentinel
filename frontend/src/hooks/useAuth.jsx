/**
 * CropSentinel — Auth + API + WebSocket + Fetch hooks
 * ====================================================
 *
 * Exports
 * ───────
 *  ThemeProvider / useTheme         — dark/light toggle
 *  AuthProvider  / useAuth          — login, logout, token, user
 *  useApi                           — typed REST helpers (get/post/put/patch/del)
 *  useFetch(path, deps?)            — data-fetching hook with AbortController,
 *                                     loading/error state, reload()
 *  WebSocketProvider / useWsContext — single shared WS connection per session;
 *                                     exposes { send, wsStatus, subscribe }
 *  useWsListener(handler)           — subscribe to all WS messages in a component
 *
 * Architecture
 * ────────────
 * Previously every page called connect() and opened its own WebSocket.
 * Now WebSocketProvider opens ONE connection for the whole session and
 * dispatches incoming messages to any number of registered listeners.
 * Pages that only read messages use useWsListener(handler).
 * Pages that also send (LiveView, RemoteAccess) call useWsContext().send().
 *
 * Backward compat
 * ───────────────
 * useWebSocket() is kept as a thin shim so any unconverted page still compiles.
 * It returns { connect } where connect() returns a no-op object.
 * Remove it once all pages are on useWsListener.
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useEffect,
  useRef,
} from 'react'

// ── Contexts ──────────────────────────────────────────────────────────────────
const AuthContext  = createContext(null)
const ThemeContext = createContext(null)
const WsContext    = createContext(null)

const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
export const UI_STATES = Object.freeze({
  LOADING: 'loading',
  EMPTY: 'empty',
  ERROR: 'error',
  READY: 'ready',
  PARTIAL: 'partial',
})

export class ApiError extends Error {
  constructor({ status = 0, code = 'request_failed', message = 'Request failed', actionableHint = '' } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.actionable_hint = actionableHint
  }
}

function parseDetail(detail) {
  if (!detail) return { code: '', message: '' }
  if (typeof detail !== 'string') return { code: '', message: String(detail) }
  const idx = detail.indexOf(':')
  if (idx <= 0) return { code: '', message: detail.trim() }
  const code = detail.slice(0, idx).trim()
  const message = detail.slice(idx + 1).trim()
  if (!/^[a-z0-9_]+$/i.test(code)) return { code: '', message: detail.trim() }
  return { code, message }
}

function formatDetail(detail) {
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const normalized = detail
      .map((item) => {
        if (!item || typeof item !== 'object') return null
        const loc = Array.isArray(item.loc) ? item.loc.map(String) : []
        const field = loc[loc.length - 1] || ''
        const msg = String(item.msg || item.message || '').toLowerCase()
        if (msg.includes('field required')) {
          if (field === 'username') return 'Enter your username.'
          if (field === 'password') return 'Enter your password.'
          return 'Please fill in all required fields.'
        }
        if (field === 'username' && msg) return `Username: ${item.msg || item.message}`
        if (field === 'password' && msg) return `Password: ${item.msg || item.message}`
        return null
      })
      .filter(Boolean)
    if (normalized.length) {
      return Array.from(new Set(normalized)).join(' ')
    }
    const parts = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object') {
          const loc = Array.isArray(item.loc) ? item.loc.join('.') : ''
          const msg = item.msg || item.message || JSON.stringify(item)
          return loc ? `${loc}: ${msg}` : msg
        }
        return String(item)
      })
      .filter(Boolean)
    return parts.join(' | ')
  }
  if (typeof detail === 'object') {
    return detail.message || detail.msg || JSON.stringify(detail)
  }
  return String(detail)
}

function actionableHintFor(status, code) {
  if (code === 'tenant_mismatch') return 'Machine is already bound to another tenant. Reinstall or re-enroll with the correct tenant token.'
  if (code === 'invalid_enrollment_token' || code === 'missing_enrollment_token') return 'Check tenant enrollment token on the agent host and retry registration.'
  if (code === 'tenant_subscription_expired' || code === 'tenant_seat_cap') return 'Tenant plan currently blocks enrollment. Verify plan/seat availability.'
  if (status === 401) return 'Sign in again and retry.'
  if (status === 403) return 'You do not have permission for this action.'
  if (status >= 500) return 'Server error. Retry in a moment or contact support if it persists.'
  return 'Retry the action and verify filters/input.'
}

async function normalizeApiError(res) {
  let payload = {}
  let fallbackText = ''
  try {
    payload = await res.json()
  } catch {
    fallbackText = await res.text().catch(() => '')
    payload = {}
  }
  const detail = payload?.detail
  const parsed = parseDetail(detail)
  const code = payload?.code || parsed.code || `http_${res.status}`
  const trimmedText = fallbackText.trim()
  const looksLikeHtml = trimmedText.startsWith('<')
  const message =
    payload?.message ||
    parsed.message ||
    detail ||
    (looksLikeHtml ? 'Server returned an unexpected HTML response.' : trimmedText) ||
    `Request failed (${res.status})`
  return new ApiError({
    status: res.status,
    code,
    message,
    actionableHint: payload?.actionable_hint || actionableHintFor(res.status, code),
  })
}

function attachListMeta(data, res) {
  if (!(Array.isArray(data) || (data && typeof data === 'object'))) return data
  const totalHeader = res.headers.get('X-Total-Count')
  const total = totalHeader == null ? null : Number(totalHeader)
  try {
    Object.defineProperty(data, '_meta', {
      value: { total: Number.isFinite(total) ? total : null, headers: res.headers },
      enumerable: false,
    })
  } catch {
    // ignore read-only objects
  }
  return data
}

// ── Theme ─────────────────────────────────────────────────────────────────────
export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(
    () => localStorage.getItem('croppro_theme') || 'dark'
  )
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('croppro_theme', theme)
  }, [theme])
  const toggle = useCallback(
    () => setTheme(t => (t === 'dark' ? 'light' : 'dark')),
    []
  )
  return (
    <ThemeContext.Provider value={{ theme, toggle, isDark: theme === 'dark' }}>
      {children}
    </ThemeContext.Provider>
  )
}
export function useTheme() { return useContext(ThemeContext) }

// ── Auth ──────────────────────────────────────────────────────────────────────
export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('croppro_token'))
  const [user, setUser]   = useState(() => {
    try { return JSON.parse(localStorage.getItem('croppro_user') || 'null') }
    catch { return null }
  })

  const login = useCallback(async (username, password) => {
    const form = new URLSearchParams()
    form.append('username', username)
    form.append('password', password)
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      const detail = formatDetail(err?.detail)
      throw new Error(detail || err?.message || 'Login failed')
    }
    const data = await res.json()
    setToken(data.access_token)
    localStorage.setItem('croppro_token', data.access_token)
    const profile = {
      username:     data.username,
      role:         data.role,
      display_name: data.display_name,
      tenant_id:    data.tenant_id || 1,
    }
    setUser(profile)
    localStorage.setItem('croppro_user', JSON.stringify(profile))
    return data
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
    localStorage.removeItem('croppro_token')
    localStorage.removeItem('croppro_user')
  }, [])

  return (
    <AuthContext.Provider value={{ token, user, login, logout, apiBase: API_BASE }}>
      {children}
    </AuthContext.Provider>
  )
}
export function useAuth() { return useContext(AuthContext) }

// ── API ───────────────────────────────────────────────────────────────────────
export function useApi() {
  const { token, apiBase, logout } = useAuth()

  const request = useCallback(async (path, options = {}) => {
    const headers = { Authorization: `Bearer ${token}`, ...options.headers }
    if (options.body != null) headers['Content-Type'] = 'application/json'
    const res = await fetch(`${apiBase}${path}`, { ...options, headers })
    if (res.status === 401) {
      logout()
      throw new ApiError({
        status: 401,
        code: 'session_expired',
        message: 'Session expired',
        actionableHint: 'Sign in again and retry.',
      })
    }
    if (!res.ok) throw await normalizeApiError(res)
    const ct = res.headers.get('content-type') || ''
    if (ct.includes('application/pdf')) return res.blob()
    const data = await res.json().catch(() => null)
    return attachListMeta(data, res)
  }, [token, apiBase, logout])

  const jsonBody = useCallback(
    body => (body != null ? JSON.stringify(body) : undefined),
    []
  )

  // options param forwarded so callers can pass { signal } for AbortController
  const get   = useCallback((path, opts)  => request(path, opts),                                     [request])
  const post  = useCallback((path, body)  => request(path, { method: 'POST',   body: jsonBody(body) }), [request, jsonBody])
  const put   = useCallback((path, body)  => request(path, { method: 'PUT',    body: jsonBody(body) }), [request, jsonBody])
  const patch = useCallback((path, body)  => request(path, { method: 'PATCH',  body: jsonBody(body) }), [request, jsonBody])
  const del_  = useCallback((path)        => request(path, { method: 'DELETE' }),                      [request])

  return useMemo(
    () => ({ get, post, put, patch, del: del_ }),
    [get, post, put, patch, del_]
  )
}

// ── useFetch ──────────────────────────────────────────────────────────────────
/**
 * Data-fetching hook with automatic AbortController cleanup.
 *
 * @param {string|null} path   — API path (e.g. '/api/machines').
 *                               Pass null to skip fetching.
 * @param {any[]}       deps   — Extra dependencies that retrigger the fetch.
 *
 * Returns { data, loading, error, reload }
 *   reload()  — increment internal counter to force a fresh fetch
 *
 * Example:
 *   const { data: machines, loading, reload } = useFetch('/api/machines')
 */
export function useFetch(path, deps = []) {
  const { token, apiBase, logout } = useAuth()
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [tick,    setTick]    = useState(0)   // increment to force reload

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!path || !token) { setLoading(false); return }

    const controller = new AbortController()
    setLoading(true)
    setError(null)

    fetch(`${apiBase}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal:  controller.signal,
    })
      .then(async res => {
        if (res.status === 401) {
          logout()
          throw new ApiError({
            status: 401,
            code: 'session_expired',
            message: 'Session expired',
            actionableHint: 'Sign in again and retry.',
          })
        }
        if (!res.ok) throw await normalizeApiError(res)
        const json = await res.json().catch(() => null)
        return attachListMeta(json, res)
      })
      .then(setData)
      .catch(e => {
        if (e.name === 'AbortError') return
        setError(e instanceof ApiError ? e : new ApiError({ message: e?.message || 'Request failed' }))
      })
      .finally(() => setLoading(false))

    return () => controller.abort()
  }, [token, path, tick, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps

  const reload = useCallback(() => setTick(t => t + 1), [])
  const uiState = !path || loading
    ? UI_STATES.LOADING
    : error
      ? (data ? UI_STATES.PARTIAL : UI_STATES.ERROR)
      : Array.isArray(data) && data.length === 0
        ? UI_STATES.EMPTY
        : UI_STATES.READY

  return { data, loading, error, reload, uiState }
}

// ── WebSocket Provider ────────────────────────────────────────────────────────
/**
 * Opens a single /ws/admin WebSocket for the authenticated session and
 * dispatches every incoming message to all registered listeners.
 *
 * Wrap your route tree with <WebSocketProvider> inside <AuthProvider>:
 *
 *   <AuthProvider>
 *     <WebSocketProvider>
 *       <BrowserRouter>...</BrowserRouter>
 *     </WebSocketProvider>
 *   </AuthProvider>
 *
 * Context value: { subscribe, send, wsStatus }
 *   subscribe(handler) — add a message handler; returns an unsubscribe fn
 *   send(data)         — JSON-stringify and send; silently drops if not open
 *   wsStatus           — 'connecting' | 'connected' | 'reconnecting' | 'disconnected'
 */
export function WebSocketProvider({ children }) {
  const { token, apiBase } = useAuth()
  const listenersRef  = useRef(new Set())
  const wsRef         = useRef(null)
  const destroyedRef  = useRef(false)
  const backoffRef    = useRef(1000)
  const timerRef      = useRef(null)
  const [wsStatus, setWsStatus] = useState('disconnected')

  useEffect(() => {
    if (!token) { setWsStatus('disconnected'); return }

    destroyedRef.current = false
    backoffRef.current   = 1000
    let isFirstConnect   = true

    const connect = () => {
      if (destroyedRef.current) return
      setWsStatus(isFirstConnect ? 'connecting' : 'reconnecting')

      const wsBase = apiBase.replace('http://', 'ws://').replace('https://', 'wss://')
      const ws     = new WebSocket(`${wsBase}/ws/admin?token=${token}`)
      wsRef.current = ws

      ws.onopen = () => {
        isFirstConnect     = false
        backoffRef.current = 1000
        setWsStatus('connected')
      }

      ws.onmessage = (e) => {
        let msg
        try { msg = JSON.parse(e.data) } catch { return }
        listenersRef.current.forEach(h => { try { h(msg) } catch {} })
      }

      ws.onclose = () => {
        if (destroyedRef.current) { setWsStatus('disconnected'); return }
        setWsStatus('reconnecting')
        backoffRef.current = Math.min(backoffRef.current * 2, 30_000)
        timerRef.current   = setTimeout(connect, backoffRef.current)
      }

      ws.onerror = () => { /* close follows immediately — handled there */ }
    }

    connect()

    return () => {
      destroyedRef.current = true
      clearTimeout(timerRef.current)
      wsRef.current?.close()
      wsRef.current = null
      setWsStatus('disconnected')
    }
  }, [token, apiBase])

  /** Register a message handler. Returns a cleanup fn that removes it. */
  const subscribe = useCallback((handler) => {
    listenersRef.current.add(handler)
    return () => listenersRef.current.delete(handler)
  }, [])

  /** Send JSON data over the shared WebSocket (fire-and-forget). */
  const send = useCallback((data) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    try { ws.send(typeof data === 'string' ? data : JSON.stringify(data)) } catch {}
  }, [])

  return (
    <WsContext.Provider value={{ subscribe, send, wsStatus }}>
      {children}
    </WsContext.Provider>
  )
}

/** Access the shared WS context (subscribe, send, wsStatus). */
export function useWsContext() { return useContext(WsContext) }

/**
 * Subscribe to all WebSocket messages inside a component.
 *
 * The handler is stored in a ref so it always receives fresh closure values
 * without causing the subscription to re-register on every render.
 *
 * Usage:
 *   useWsListener(msg => {
 *     if (msg.type === 'machine_online') setOnline(id => ...)
 *   })
 */
export function useWsListener(handler) {
  const ctx        = useWsContext()
  const handlerRef = useRef(handler)

  // Keep ref current without re-subscribing
  useEffect(() => { handlerRef.current = handler })

  useEffect(() => {
    if (!ctx) return
    // stable wrapper — the listener set never changes; only the inner fn does
    const stable = (msg) => handlerRef.current(msg)
    return ctx.subscribe(stable)
  }, [ctx])
}

// ── Backward-compat shim ──────────────────────────────────────────────────────
/**
 * @deprecated  Use useWsListener() + useWsContext() instead.
 * Kept so any not-yet-migrated import still compiles.
 */
export function useWebSocket() {
  const ctx = useWsContext()

  const connect = useCallback((onMessage, _opts = {}) => {
    // Register as a listener on the shared connection
    const unsub = ctx?.subscribe(onMessage) ?? (() => {})
    return {
      send:       (data)  => ctx?.send(data),
      close:      ()      => unsub(),
      get status()        { return ctx?.wsStatus ?? 'disconnected' },
      get readyState()    { return WebSocket.OPEN },
    }
  }, [ctx])

  return { connect }
}
