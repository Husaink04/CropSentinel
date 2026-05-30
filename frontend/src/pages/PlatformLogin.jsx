import { useState } from 'react'
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import '../platform.css'

const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

function formatPlatformLoginDetail(detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map(item => {
      if (!item || typeof item !== 'object') return null
      const loc = Array.isArray(item.loc) ? item.loc.map(String) : []
      const field = loc[loc.length - 1] || ''
      const msg = String(item.msg || item.message || '').toLowerCase()
      if (msg.includes('field required')) {
        if (field === 'username') return 'Enter your username.'
        if (field === 'password') return 'Enter your password.'
        return 'Please fill in all required fields.'
      }
      return null
    }).filter(Boolean)
    if (messages.length) return Array.from(new Set(messages)).join(' ')
  }
  if (detail && typeof detail === 'object') {
    return detail.message || detail.msg || 'Login failed'
  }
  return 'Login failed'
}

async function parsePlatformResponse(res) {
  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return res.json().catch(() => ({}))
  }
  const text = await res.text().catch(() => '')
  return { detail: text.trim().startsWith('<') ? 'Server returned an unexpected HTML response.' : (text || 'Login failed') }
}

export default function PlatformLogin() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const root = document.documentElement
    const prev = root.getAttribute('data-theme')
    root.setAttribute('data-theme', 'light')
    return () => {
      if (prev) root.setAttribute('data-theme', prev)
      else root.removeAttribute('data-theme')
    }
  }, [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const normalizedUsername = username.trim()
    if (!normalizedUsername && !password) {
      setError('Enter your username and password.')
      return
    }
    if (!normalizedUsername) {
      setError('Enter your username.')
      return
    }
    if (!password) {
      setError('Enter your password.')
      return
    }
    setLoading(true)
    setError('')
    try {
      const form = new URLSearchParams()
      form.append('username', normalizedUsername)
      form.append('password', password)
      const res = await fetch(`${API_BASE}/api/platform/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: form,
      })
      const data = await parsePlatformResponse(res)
      if (!res.ok) {
        const detail = data?.detail
        let message = 'Login failed'
        if (typeof detail === 'string') {
          message = detail
        } else if (Array.isArray(detail)) {
          message = formatPlatformLoginDetail(detail) || message
        } else if (detail && typeof detail === 'object') {
          message = formatPlatformLoginDetail(detail) || message
        }
        throw new Error(message)
      }
      localStorage.setItem('croppro_platform_token', data.access_token)
      localStorage.setItem('croppro_platform_user', JSON.stringify({
        username: data.username,
        role: data.role,
        display_name: data.display_name,
        tenant_id: data.tenant_id,
      }))
      navigate('/platform')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="platform-login">
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <main id="main-content" tabIndex={-1} className="platform-login-card">
        <div style={{ textAlign: 'center', marginBottom: 18 }}>
          <div className="platform-brand-mark" style={{ margin: '0 auto 10px' }}>◆</div>
          <div className="platform-page-title" style={{ fontSize: 26 }}>CropSentinel</div>
          <div className="platform-page-sub">Platform Administration</div>
        </div>

        <form onSubmit={handleSubmit}>
          {error && (
            <div className="ui-inline-banner ui-inline-banner-danger" style={{ marginBottom: 10 }}>
              <div className="ui-inline-banner-copy">
                <strong>Login failed</strong>
                <span>{error}</span>
              </div>
            </div>
          )}

          <div className="form-group" style={{ marginBottom: 12 }}>
            <label className="form-label">Username</label>
            <input
              className="input-field"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter username"
              autoFocus
              autoComplete="username"
            />
          </div>

          <div className="form-group" style={{ marginBottom: 14 }}>
            <label className="form-label">Password</label>
            <input
              type="password"
              className="input-field"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter platform password"
              autoComplete="current-password"
            />
          </div>

          <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={loading}>
            {loading ? 'Authenticating...' : 'Access Platform'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => navigate('/login')}>
            Back to Dashboard Login
          </button>
        </div>
      </main>
    </div>
  )
}
