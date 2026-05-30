/**
 * CropSentinel — App entry point
 * ═══════════════════════════════
 * Changes vs previous version
 * ───────────────────────────
 *  • All 23 page imports converted to React.lazy() for code splitting.
 *    Each lazy page is loaded only when its route is first visited, so the
 *    initial JS bundle drops from ~900 KB to the shell + current page.
 *
 *  • Routes wrapped in <Suspense> with a centered spinner fallback.
 *
 *  • WebSocketProvider added inside AuthProvider — opens a single shared
 *    WebSocket for the whole session instead of per-page connections.
 *
 *  • PlatformPrivateRoute added to guard /platform/* routes.
 *    Previously any unauthenticated visitor could access /platform/tenants etc.
 *    Now it checks localStorage for croppro_platform_token and redirects to
 *    /platform/login if absent.
 */

import React, { Suspense, lazy } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import * as Sentry from '@sentry/react'

import { AuthProvider, ThemeProvider, WebSocketProvider, useAuth } from './hooks/useAuth'
import { PageContextProvider } from './hooks/usePageContext'
import ErrorBoundary from './components/ErrorBoundary'
import { NotificationProvider } from './hooks/useNotifications'
import './i18n'              // initialise i18next before any component renders
import './index.css'

function scrubSentryEvent(event) {
  const sensitiveKeys = new Set([
    'authorization',
    'password',
    'token',
    'access_token',
    'refresh_token',
    'jwt',
    'license',
    'license_key',
  ])

  const scrub = (value) => {
    if (Array.isArray(value)) return value.map(scrub)
    if (value && typeof value === 'object') {
      return Object.fromEntries(
        Object.entries(value).map(([key, inner]) => [
          key,
          sensitiveKeys.has(key.toLowerCase()) ? '[Filtered]' : scrub(inner),
        ]),
      )
    }
    return value
  }

  return scrub(event)
}

if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || import.meta.env.MODE,
    tracesSampleRate: Number(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE || 0.1),
    beforeSend: scrubSentryEvent,
  })
}

// ── Lazy page imports ─────────────────────────────────────────────────────────
// Each becomes its own chunk. Vite names them by route segment automatically.

// Shell / structural (small — still lazy for consistency)
const App            = lazy(() => import('./App'))
const Login          = lazy(() => import('./pages/Login'))
const PlatformLogin  = lazy(() => import('./pages/PlatformLogin'))
const PlatformLayout = lazy(() => import('./pages/PlatformLayout'))

// Customer dashboard pages
const Dashboard      = lazy(() => import('./pages/Dashboard'))
const Machines       = lazy(() => import('./pages/Machines'))
const MachineDetail  = lazy(() => import('./pages/MachineDetail'))
const MachineProductivity = lazy(() => import('./pages/MachineProductivity'))
const Teams          = lazy(() => import('./pages/Teams'))
const TeamDashboard  = lazy(() => import('./pages/TeamDashboard'))
const LiveView       = lazy(() => import('./pages/LiveView'))
const AppUsage       = lazy(() => import('./pages/AppUsage'))
const BrowserLogs    = lazy(() => import('./pages/BrowserLogs'))
const Productivity   = lazy(() => import('./pages/Productivity'))
const InputActivity  = lazy(() => import('./pages/InputActivity'))
const FileLogs       = lazy(() => import('./pages/FileLogs'))
const NetworkLogs    = lazy(() => import('./pages/NetworkLogs'))
const DLPEvents      = lazy(() => import('./pages/DLPEvents'))
const Phishing       = lazy(() => import('./pages/Phishing'))
const Alerts         = lazy(() => import('./pages/Alerts'))
const RemoteAccess   = lazy(() => import('./pages/RemoteAccess'))   // ~64 KB — big win
const Reports        = lazy(() => import('./pages/Reports'))
const Settings       = lazy(() => import('./pages/Settings'))       // ~49 KB
const UserManagement = lazy(() => import('./pages/UserManagement'))

// Platform admin portal pages
const PlatformDashboard  = lazy(() => import('./pages/PlatformDashboard'))
const TenantManagement   = lazy(() => import('./pages/TenantManagement'))  // ~56 KB
const PlatformUsers      = lazy(() => import('./pages/PlatformUsers'))
const PlatformDlp        = lazy(() => import('./pages/PlatformDlp'))
const PlatformPhishing   = lazy(() => import('./pages/PlatformPhishing'))

// ── Loading fallback ──────────────────────────────────────────────────────────
function PageLoader() {
  return (
    <div className="loading-center" style={{ minHeight: '100vh' }}>
      <div className="spinner" style={{ width: 32, height: 32, borderWidth: 3 }} />
    </div>
  )
}

// ── Customer route guard ──────────────────────────────────────────────────────
function PrivateRoute({ children }) {
  const { token } = useAuth()
  return token ? children : <Navigate to="/login" replace />
}

// ── Platform route guard ──────────────────────────────────────────────────────
/**
 * Guards all /platform/* routes except /platform/login.
 * The platform admin session is stored separately from the customer session
 * (croppro_platform_token vs croppro_token) so the two portals are fully
 * independent — a logged-in customer cannot access platform routes.
 */
function PlatformPrivateRoute({ children }) {
  const platformToken = localStorage.getItem('croppro_platform_token')
  return platformToken ? children : <Navigate to="/platform/login" replace />
}

// ── App tree ──────────────────────────────────────────────────────────────────
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider>
      <AuthProvider>
        {/*
          WebSocketProvider sits inside AuthProvider so it can read the auth
          token, but outside BrowserRouter so it's never remounted on navigation.
          The single WS connection lives for the full authenticated session.
        */}
        <WebSocketProvider>
          <NotificationProvider>
            <PageContextProvider>
              <BrowserRouter>
                <ErrorBoundary>
                  <Suspense fallback={<PageLoader />}>
                    <Routes>
                {/* ── Customer dashboard ──────────────────────────────── */}
                <Route path="/login" element={<Login />} />

                <Route path="/" element={<PrivateRoute><App /></PrivateRoute>}>
                  <Route index element={<Navigate to="/dashboard" replace />} />
                  <Route path="dashboard"            element={<Dashboard />} />
                  <Route path="machines"             element={<Machines />} />
                  <Route path="machines/:machineId"  element={<MachineDetail />} />
                  <Route path="machines/:machineId/productivity" element={<MachineProductivity />} />
                  <Route path="teams"                element={<Teams />} />
                  <Route path="teams/:teamId"        element={<TeamDashboard />} />
                  <Route path="live"                 element={<LiveView />} />
                  <Route path="apps"                 element={<AppUsage />} />
                  <Route path="browser"              element={<BrowserLogs />} />
                  <Route path="productivity"         element={<Productivity />} />
                  <Route path="input"                element={<InputActivity />} />
                  <Route path="files"                element={<FileLogs />} />
                  <Route path="network"              element={<NetworkLogs />} />
                  <Route path="dlp"                  element={<DLPEvents />} />
                  <Route path="phishing"             element={<Phishing />} />
                  <Route path="alerts"               element={<Alerts />} />
                  <Route path="remote"               element={<RemoteAccess />} />
                  <Route path="reports"              element={<Reports />} />
                  <Route path="settings"             element={<Settings />} />
                  <Route path="users"                element={<UserManagement />} />
                </Route>

                {/* ── Platform admin portal ────────────────────────────── */}
                <Route path="/platform/login" element={<PlatformLogin />} />

                <Route
                  path="/platform"
                  element={
                    <PlatformPrivateRoute>
                      <PlatformLayout />
                    </PlatformPrivateRoute>
                  }
                >
                  <Route index                  element={<PlatformDashboard />} />
                  <Route path="tenants"         element={<TenantManagement />} />
                  <Route path="users"           element={<PlatformUsers />} />
                  <Route path="dlp"             element={<PlatformDlp />} />
                  <Route path="phishing"        element={<PlatformPhishing />} />
                  <Route path="license"         element={<Navigate to="/platform" replace />} />
                </Route>
                    </Routes>
                  </Suspense>
                </ErrorBoundary>
              </BrowserRouter>
            </PageContextProvider>
          </NotificationProvider>
        </WebSocketProvider>
      </AuthProvider>
    </ThemeProvider>
  </React.StrictMode>
)
