import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useState, useEffect, useMemo, useCallback } from 'react'
import '../platform.css'

const I = {
  overview: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 13h6V4H4z"/><path d="M14 20h6v-9h-6z"/><path d="M14 10h6V4h-6z"/><path d="M4 20h6v-3H4z"/></svg>,
  tenants: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18"/><path d="M8 16h3M14 16h2"/></svg>,
  dlp: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>,
  phishing: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 2 4 6v6c0 5.2 3.5 8.7 8 10 4.5-1.3 8-4.8 8-10V6z"/><path d="M12 8v4"/><circle cx="12" cy="16.5" r=".8" fill="currentColor"/></svg>,
  users: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
  logout: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></svg>,
}

function usePlatformAuth() {
  const [token, setToken] = useState(() => localStorage.getItem('croppro_platform_token'))
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('croppro_platform_user') || 'null')
    } catch {
      return null
    }
  })
  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
    localStorage.removeItem('croppro_platform_token')
    localStorage.removeItem('croppro_platform_user')
  }, [])
  return { token, user, logout }
}

function usePlatformApi() {
  const { token, logout } = usePlatformAuth()
  const apiBase = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

  const request = useCallback(async (path, options = {}) => {
    const headers = { Authorization: `Bearer ${token}`, ...options.headers }
    if (options.body != null) headers['Content-Type'] = 'application/json'
    const res = await fetch(`${apiBase}${path}`, { ...options, headers })
    if (res.status === 401) {
      logout()
      throw new Error('Session expired')
    }
    if (res.status === 403) throw new Error('You do not have access to this platform action')
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Request failed (${res.status})`)
    }
    const json = await res.json()
    if (Array.isArray(json) || (json && typeof json === 'object')) {
      const totalHeader = res.headers.get('X-Total-Count')
      const total = totalHeader == null ? null : Number(totalHeader)
      try {
        Object.defineProperty(json, '_meta', {
          value: { total: Number.isFinite(total) ? total : null, headers: res.headers },
          enumerable: false,
        })
      } catch {
        // ignore
      }
    }
    return json
  }, [token, apiBase, logout])

  return useMemo(() => ({
    get: path => request(path),
    post: (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) }),
    put: (path, body) => request(path, { method: 'PUT', body: JSON.stringify(body) }),
    del: path => request(path, { method: 'DELETE' }),
  }), [request])
}

export { usePlatformAuth, usePlatformApi }

const NAV = [
  { to: '/platform', icon: I.overview, label: 'Overview', exact: true, note: 'Cross-tenant health' },
  { to: '/platform/tenants', icon: I.tenants, label: 'Tenants', note: 'Workspace setup' },
  { to: '/platform/dlp', icon: I.dlp, label: 'DLP', note: 'Policy baseline' },
  { to: '/platform/phishing', icon: I.phishing, label: 'Phishing', note: 'Threat posture' },
  { to: '/platform/users', icon: I.users, label: 'Users', note: 'Platform admins' },
]

const TITLES = {
  '/platform': 'Platform Overview',
  '/platform/tenants': 'Tenant Management',
  '/platform/dlp': 'Enterprise DLP',
  '/platform/phishing': 'Platform Phishing',
  '/platform/users': 'Platform Users',
}

function useClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function PlatformLayout() {
  const { user, logout } = usePlatformAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const clock = useClock()

  useEffect(() => {
    const token = localStorage.getItem('croppro_platform_token')
    if (!token) navigate('/platform/login', { replace: true })
  }, [navigate])

  useEffect(() => {
    const root = document.documentElement
    const prev = root.getAttribute('data-theme')
    root.setAttribute('data-theme', 'light')
    return () => {
      if (prev) root.setAttribute('data-theme', prev)
      else root.removeAttribute('data-theme')
    }
  }, [])

  const pageTitle = TITLES[location.pathname] || 'Platform Admin'
  const initials = (user?.display_name || user?.username || 'A').slice(0, 2).toUpperCase()
  const isMsp = Boolean(user?.is_msp)
  const visibleNav = useMemo(
    () => (isMsp ? NAV.filter((item) => item.to === '/platform' || item.to === '/platform/tenants') : NAV),
    [isMsp],
  )
  const activeNav = visibleNav.find((item) => item.exact ? location.pathname === item.to : location.pathname.startsWith(item.to))

  return (
    <div className="platform-root">
      <a href="#main-content" className="skip-link">Skip to main content</a>

      <aside className="platform-sidebar">
        <div className="platform-brand">
          <div className="platform-brand-mark">
            <img src="/CropSentinel-logo.png" alt="CropSentinel" className="platform-brand-image" />
          </div>
          <div>
            <div className="platform-brand-name">CropSentinel</div>
            <div className="platform-brand-sub">{isMsp ? 'MSP Partner Portal' : 'Platform Control'}</div>
          </div>
        </div>

        <div className="platform-sidebar-intro">
          <div className="platform-sidebar-eyebrow">Workspace</div>
          <div className="platform-sidebar-copy">
            {isMsp
              ? 'Manage your client tenants, seat allocation, and partner operations from one place.'
              : 'Manage tenants, agent access, and cross-tenant security from one place.'}
          </div>
        </div>

        <nav className="platform-nav">
          {visibleNav.map((n) => {
            const isActive = n.exact ? location.pathname === n.to : location.pathname.startsWith(n.to)
            return (
              <NavLink key={n.to} to={n.to} end={n.exact} className={`platform-nav-item${isActive ? ' active' : ''}`}>
                <span className="platform-nav-icon">{n.icon}</span>
                <span className="platform-nav-copy">
                  <strong>{n.label}</strong>
                  <small>{n.note}</small>
                </span>
              </NavLink>
            )
          })}
        </nav>

        <div className="platform-user">
          <div className="platform-user-avatar">{initials}</div>
          <div className="platform-user-meta">
            <span className="platform-user-name">{user?.display_name || user?.username}</span>
            <span className="platform-user-role">{isMsp ? 'MSP Admin' : 'Platform Admin'}</span>
          </div>
          <button className="btn btn-ghost btn-sm platform-logout-btn" onClick={() => { logout(); navigate('/platform/login') }}>
            {I.logout}
            <span>Log out</span>
          </button>
        </div>
      </aside>

      <div className="platform-main">
        <header className="platform-topbar">
          <div className="platform-topbar-copy">
            <div className="platform-title">{pageTitle}</div>
            <div className="platform-topbar-subtitle">{activeNav?.note || 'Platform operations workspace'}</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="topbar-clock mono">{clock}</span>
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="platform-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
