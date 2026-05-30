import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth, useApi, useWsListener, useWsContext, useTheme } from './hooks/useAuth'
import { useNotifications } from './hooks/useNotifications'
import { NotificationToasts } from './components/NotificationCenter'
import './App.css'

// Legacy color→type mapping so existing addToast call-sites keep working.
const COLOR_TO_TYPE = { green: 'success', red: 'error', amber: 'warning', blue: 'info', purple: 'alert' }

/* ── SVG Icons ─────────────────────────────────────────────────────────────── */
const I = {
  dashboard:   <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>,
  machines:    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>,
  teams:       <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="3.5"/><path d="M23 21v-2a4 4 0 0 0-3-3.85"/><path d="M16 3.2a3.5 3.5 0 0 1 0 6.6"/></svg>,
  live:        <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>,
  apps:        <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>,
  browser:     <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10A15.3 15.3 0 0112 2z"/></svg>,
  productivity:<svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>,
  input:       <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M8 16h8"/></svg>,
  files:       <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg>,
  network:     <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><circle cx="6" cy="6" r="1" fill="currentColor"/><circle cx="6" cy="18" r="1" fill="currentColor"/><path d="M10 6h6M10 18h6"/></svg>,
  dlp:         <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg>,
  phishing:    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M12 2l8 4v6c0 5.25-3.5 8.75-8 10-4.5-1.25-8-4.75-8-10V6l8-4z"/><path d="M9.5 9.5a2.5 2.5 0 115 0c0 1.5-1 2.15-1.8 2.76-.68.5-1.2.94-1.2 1.74"/><circle cx="12" cy="17.25" r="1"/></svg>,
  alerts:      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>,
  remote:      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/><path d="M7.5 10l2.5 2.5L15 8" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  reports:     <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>,
  users:       <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>,
  settings:    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>,
  logout:      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>,
  sun:         <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>,
  moon:        <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M21 12.79A9 9 0 1111.21 3a7 7 0 009.79 9.79z"/></svg>,
  chevronL:    <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6"/></svg>,
  chevronR:    <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path d="M9 18l6-6-6-6"/></svg>,
}

/* ── Navigation config ─────────────────────────────────────────────────────── */
const NAV = [
  { section: 'MONITOR' },
  { to: '/dashboard',    icon: I.dashboard,    label: 'Dashboard',      perm: 'machines.view' },
  { to: '/machines',     icon: I.machines,     label: 'Machines',       perm: 'machines.view' },
  { to: '/teams',        icon: I.teams,        label: 'Teams',          perm: 'teams.view' },
  { to: '/live',         icon: I.live,         label: 'Live View',      perm: 'screenshots.view' },
  { section: 'ANALYTICS' },
  { to: '/apps',         icon: I.apps,         label: 'App Usage',      perm: 'activity.view' },
  { to: '/browser',      icon: I.browser,      label: 'Browser Logs',   perm: 'activity.view' },
  { to: '/productivity', icon: I.productivity, label: 'Productivity',   perm: 'productivity.view' },
  { to: '/files',        icon: I.files,        label: 'File Logs',      perm: 'activity.view' },
  { to: '/network',      icon: I.network,      label: 'Network Logs',   perm: 'activity.view' },
  { section: 'SECURITY' },
  { to: '/dlp',          icon: I.dlp,          label: 'DLP Events',     perm: 'activity.view' },
  { to: '/phishing',     icon: I.phishing,     label: 'Phishing',       perm: 'activity.view' },
  { section: 'CONTROL' },
  { to: '/alerts',       icon: I.alerts,       label: 'Alerts',         perm: 'alerts.view', badge: true },
  { to: '/remote',       icon: I.remote,       label: 'Remote Access',  perm: 'remote.access' },
  { to: '/reports',      icon: I.reports,      label: 'Reports',        perm: 'reports.generate' },
]
const NAV_BOT = [
  { to: '/users',    icon: I.users,    label: 'Users',    perm: 'users.view' },
  { to: '/settings', icon: I.settings, label: 'Settings', perm: 'settings.view' },
]

// Role permission map (mirrors backend)
const ROLE_PERMISSIONS = {
  admin: new Set([
    'machines.view','machines.edit','machines.delete','teams.view','teams.manage','activity.view','screenshots.view',
    'analytics.view','productivity.view','alerts.view','alerts.manage','remote.access',
    'reports.generate','settings.view','settings.edit','users.view','users.manage',
  ]),
  manager: new Set([
    'machines.view','teams.view','teams.manage','activity.view','screenshots.view','analytics.view','productivity.view',
    'alerts.view','alerts.manage','reports.generate',
  ]),
  viewer: new Set([
    'machines.view','teams.view','activity.view','screenshots.view','analytics.view','productivity.view',
  ]),
  remote_operator: new Set([
    'machines.view','teams.view','activity.view','screenshots.view','analytics.view','remote.access',
  ]),
}

function hasPerm(role, perm) {
  if (!perm) return true
  return ROLE_PERMISSIONS[role]?.has(perm) ?? false
}

const PAGE_TITLES = {
  '/dashboard':    'Dashboard',
  '/machines':     'Machines',
  '/teams':        'Teams',
  '/live':         'Live View',
  '/apps':         'App Usage',
  '/browser':      'Browser Logs',
  '/productivity': 'Productivity',
  '/input':        'Input Activity',
  '/files':        'File Logs',
  '/network':      'Network Logs',
  '/dlp':          'DLP Events',
  '/phishing':     'Phishing Protection',
  '/alerts':           'Alerts',
  '/remote':       'Remote Access',
  '/reports':      'Reports',
  '/settings':     'Settings',
  '/users':        'User Management',
  '/machines/:id': 'Machine Detail',
  '/teams/:id':    'Team Dashboard',
}

const WS_INDICATOR = {
  connected:     { color: 'var(--green)',  label: 'Live',           dot: true  },
  connecting:    { color: 'var(--amber)',  label: 'Connecting',     dot: false },
  reconnecting:  { color: 'var(--amber)',  label: 'Reconnecting',  dot: false },
  disconnected:  { color: 'var(--red)',    label: 'Offline',        dot: false },
}

/* ── ROLE BADGE COLORS ─────────────────────────────────────────────────────── */
const ROLE_COLORS = {
  admin:           { bg: 'var(--red-dim)',    text: 'var(--red)',    label: 'Admin' },
  manager:         { bg: 'var(--amber-dim)',  text: 'var(--amber)',  label: 'Manager' },
  viewer:          { bg: 'var(--brand-dim)',  text: 'var(--brand)',  label: 'Viewer' },
  remote_operator: { bg: 'var(--purple-dim)', text: 'var(--purple)', label: 'Operator' },
}

export default function App() {
  const { logout, user: authUser } = useAuth()
  const { get }                    = useApi()
  const { wsStatus }               = useWsContext()
  const { toggle, isDark }         = useTheme()
  const navigate           = useNavigate()
  const location           = useLocation()
  const userRole           = authUser?.role || 'viewer'

  const [unreadAlerts, setUnreadAlerts] = useState(0)
  const [companyName,  setCompanyName]  = useState('CropSentinel')
  const [collapsed,    setCollapsed]    = useState(false)
  const [tick,         setTick]         = useState(new Date())
  const { push: pushNotification }       = useNotifications()

  useEffect(() => {
    const t = setInterval(() => setTick(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const refreshState = useCallback(() => {
    get('/api/alerts/stats').then(s => setUnreadAlerts(s.unread || 0)).catch(() => {})
  }, [get])

  useEffect(() => {
    get('/api/settings').then(s => setCompanyName(s.company_name || 'CropSentinel')).catch(() => {})
    refreshState()

  }, [])

  // Live WS messages — shared connection via WebSocketProvider
  useWsListener((msg) => {
    switch (msg.type) {
      case 'machine_online':
        addToast(`${msg.hostname || msg.machine_id?.slice(0,10)} came online`, 'green')
        break
      case 'machine_offline':
        addToast(`${msg.hostname || 'Machine'} went offline`, 'red')
        break
      case 'machine_unstable':
        addToast(`${msg.hostname || 'Machine'} connection unstable`, 'amber')
        break
      case 'new_alert':
        setUnreadAlerts(n => n + 1)
        addToast(`${msg.message?.slice(0,48) || 'Alert triggered'}`, 'amber')
        break
    }
  })

  // Refresh state after every WS reconnect
  const prevWsStatus = useRef(wsStatus)
  useEffect(() => {
    if (prevWsStatus.current !== 'connected' && wsStatus === 'connected') {
      refreshState() // re-fetch counts after reconnect
    }
    prevWsStatus.current = wsStatus
  }, [wsStatus, refreshState])

  // Back-compat shim: forwards legacy addToast calls into the notification centre,
  // so the same event pings both the floating toast AND the persistent history.
  function addToast(msg, color = 'blue') {
    pushNotification({ title: msg, type: COLOR_TO_TYPE[color] || 'info' })
  }

  const currentPage = PAGE_TITLES[location.pathname] ||
    PAGE_TITLES[Object.keys(PAGE_TITLES).find(k => location.pathname.startsWith(k)) || ''] || ''

  const wsInd  = WS_INDICATOR[wsStatus] || WS_INDICATOR.connecting
  const rc     = ROLE_COLORS[userRole]  || ROLE_COLORS.viewer
  const uName  = authUser?.display_name || authUser?.username || 'User'
  const uInit  = uName.charAt(0).toUpperCase()

  return (
    <div className="app-shell">

      {/* Keyboard skip-link — first tab stop, jumps past the sidebar. */}
      <a href="#main-content" className="skip-link">Skip to main content</a>

      {/* ─── SIDEBAR ─── */}
      <aside className={`sidebar ${collapsed ? 'closed' : 'open'}`}>

        {/* Logo */}
        <div className="sidebar-logo" onClick={() => navigate('/dashboard')} style={{ cursor: 'pointer' }}>
          <div className="logo-mark">
            <img src="/CropSentinel-logo.png" alt="CropSentinel" className="logo-mark-image" />
          </div>
          {!collapsed && (
            <div style={{ overflow: 'hidden', minWidth: 0 }}>
              <div className="logo-text">{companyName}</div>
              <div className="logo-sub">Employee Monitoring</div>
            </div>
          )}
        </div>

        {/* Main Navigation */}
        <nav className="sidebar-nav">
          {NAV.map((n, i) => {
            if (n.section) {
              const sectionItems = NAV.slice(i + 1)
              const nextSectionIdx = sectionItems.findIndex(x => x.section)
              const items = nextSectionIdx >= 0 ? sectionItems.slice(0, nextSectionIdx) : sectionItems
              const hasVisible = items.some(x => hasPerm(userRole, x.perm))
              if (!hasVisible) return null
              return !collapsed
                ? <div key={i} className="nav-section-label">{n.section}</div>
                : <div key={i} className="nav-section-dot" />
            }
            if (!hasPerm(userRole, n.perm)) return null
            const isActive = location.pathname === n.to || location.pathname.startsWith(n.to + '/')
            return (
              <NavLink key={n.to} to={n.to}
                className={`nav-item${isActive ? ' active' : ''}`}
                title={collapsed ? n.label : undefined}>
                <span className="nav-icon">{n.icon}</span>
                {!collapsed && <span className="nav-label">{n.label}</span>}
                {n.badge && unreadAlerts > 0 && (
                  <span className="nav-badge">{unreadAlerts > 99 ? '99+' : unreadAlerts}</span>
                )}
              </NavLink>
            )
          })}
        </nav>

        {/* Bottom Section */}
        <div className="sidebar-bottom">

          {/* Bottom nav items */}
          {NAV_BOT.filter(n => hasPerm(userRole, n.perm)).map(n => {
            const isActive = location.pathname === n.to
            return (
              <NavLink key={n.to} to={n.to}
                className={`nav-item${isActive ? ' active' : ''}`}
                title={collapsed ? n.label : undefined}>
                <span className="nav-icon">{n.icon}</span>
                {!collapsed && <span className="nav-label">{n.label}</span>}
              </NavLink>
            )
          })}

          {/* User card */}
          <div className="sidebar-user-card">
            <div className="user-avatar" style={{ background: rc.bg, color: rc.text }}>{uInit}</div>
            {!collapsed && (
              <div className="user-info">
                <div className="user-name">{uName}</div>
                <div className="user-role-badge" style={{ background: rc.bg, color: rc.text }}>{rc.label}</div>
              </div>
            )}
            {!collapsed && (
              <div className="user-actions">
                <button className="btn-icon-sm" onClick={toggle}
                  title={`Switch to ${isDark ? 'light' : 'dark'} mode`}>
                  {isDark ? I.sun : I.moon}
                </button>
                <button className="btn-icon-sm btn-logout"
                  onClick={() => { logout(); navigate('/login') }} title="Log out">
                  {I.logout}
                </button>
              </div>
            )}
          </div>

          {/* Collapsed: just icons */}
          {collapsed && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, marginTop: 4 }}>
              <button className="btn-icon-sm" onClick={toggle} title={isDark ? 'Light mode' : 'Dark mode'}>
                {isDark ? I.sun : I.moon}
              </button>
              <button className="btn-icon-sm btn-logout"
                onClick={() => { logout(); navigate('/login') }} title="Log out">
                {I.logout}
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* ─── MAIN ─── */}
      <main id="main-content" className="main-area" tabIndex={-1}>

        <header className="topbar">
          <div className="topbar-left">
            <button className="collapse-btn" onClick={() => setCollapsed(c => !c)}
              title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
              {collapsed ? I.chevronR : I.chevronL}
            </button>
            {currentPage && (
              <>
                <div className="topbar-divider" />
                <div style={{ display: 'grid', gap: 1 }}>
                  <span className="topbar-page-title">{currentPage}</span>
                </div>
              </>
            )}
          </div>

          <div className="topbar-right">
            {/* WS indicator */}
            <div className="ws-indicator" style={{
              background: `color-mix(in srgb, ${wsInd.color} 10%, transparent)`,
              borderColor: `color-mix(in srgb, ${wsInd.color} 20%, transparent)`,
              color: wsInd.color,
            }}>
              <span className={`ws-dot${wsInd.dot ? ' ws-dot-live' : ' ws-dot-spin'}`}
                style={{ background: wsInd.color }} />
              {wsInd.label}
            </div>

            {/* Clock */}
            <div className="topbar-clock mono">
              {tick.toLocaleTimeString('en-US', { hour12: false })}
            </div>
          </div>
        </header>

        <div className="page-content">
          <Outlet />
        </div>
      </main>

      {/* ─── TOASTS ─── (rendered by the notification centre) */}
      <NotificationToasts />
    </div>
  )
}
