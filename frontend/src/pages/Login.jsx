import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function Login() {
  const { login } = useAuth()
  const navigate  = useNavigate()
  const [form, setForm] = useState({ username: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    const username = form.username.trim()
    const password = form.password
    if (!username && !password) {
      setError('Enter your username and password.')
      return
    }
    if (!username) {
      setError('Enter your username.')
      return
    }
    if (!password) {
      setError('Enter your password.')
      return
    }
    setError(''); setLoading(true)
    try {
      await login(username, password)
      navigate('/dashboard', { replace: true })
    } catch(e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <div style={{
      minHeight:'100vh', display:'flex', alignItems:'center', justifyContent:'center',
      background:'var(--bg)', padding:20,
    }}>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <main id="main-content" tabIndex={-1} style={{ width:'100%', maxWidth:380 }}>
        {/* Logo */}
        <div style={{ textAlign:'center', marginBottom:36 }}>
          <div style={{
            width:52, height:52, borderRadius:14, background:'var(--brand)',
            display:'flex', alignItems:'center', justifyContent:'center',
            fontSize:22, color:'#fff', fontWeight:800, margin:'0 auto 14px',
          }}>C</div>
          <div style={{ fontSize:22, fontWeight:800, color:'var(--text-1)', letterSpacing:'-.3px' }}>CropSentinel</div>
          <div style={{ fontSize:12, color:'var(--brand)', marginTop:2, fontWeight:600, letterSpacing:'.3px' }}>Monitor. Detect. Protect.</div>
          <div style={{ fontSize:13, color:'var(--text-3)', marginTop:4 }}>Employee Monitoring Dashboard</div>
        </div>

        {/* Card */}
        <div className="card" style={{ padding:28 }}>
          <div style={{ fontSize:15, fontWeight:700, marginBottom:20 }}>Sign in to continue</div>

          <form onSubmit={submit} style={{ display:'flex', flexDirection:'column', gap:14 }}>
            <div className="form-group">
              <label className="form-label">Username</label>
              <input className="input-field" autoComplete="username" autoFocus
                value={form.username} onChange={e=>setForm(f=>({...f,username:e.target.value}))}
                placeholder="Enter username"/>
            </div>
            <div className="form-group">
              <label className="form-label">Password</label>
              <input type="password" className="input-field" autoComplete="current-password"
                value={form.password} onChange={e=>setForm(f=>({...f,password:e.target.value}))}
                placeholder="••••••••"/>
            </div>

            {error && (
              <div style={{ background:'var(--red-dim)', border:'1px solid rgba(239,68,68,.2)',
                color:'var(--red)', padding:'9px 13px', borderRadius:'var(--r-md)', fontSize:13 }}>
                {error}
              </div>
            )}

            <button type="submit" className="btn btn-primary"
              disabled={loading} style={{ width:'100%', padding:'10px', marginTop:4 }}>
              {loading ? <><span className="spinner" style={{width:14,height:14}}/> Signing in…</> : 'Sign In'}
            </button>
          </form>
        </div>
      </main>
    </div>
  )
}
