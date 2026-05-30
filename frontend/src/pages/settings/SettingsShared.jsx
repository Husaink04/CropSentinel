export function Toggle({ on, onChange, label }) {
  return (
    <label style={{ display:'flex', alignItems:'center', gap:12, cursor:'pointer', userSelect:'none' }}>
      <div onClick={() => onChange(!on)} style={{ position:'relative', width:42, height:24, flexShrink:0 }}>
        <div style={{ width:42, height:24, borderRadius:12,
          background: on ? 'var(--brand)' : 'var(--border-1)',
          transition:'background .2s' }} />
        <div style={{ position:'absolute', top:3, left: on ? 21 : 3,
          width:18, height:18, borderRadius:'50%', background:'white',
          transition:'left .18s cubic-bezier(.4,0,.2,1)',
          boxShadow:'0 1px 4px rgba(0,0,0,.25)' }} />
      </div>
      {label && <span style={{ fontSize:13, color:'var(--text-2)', lineHeight:1.4 }}>{label}</span>}
    </label>
  )
}

export function Field({ label, hint, children }) {
  return (
    <div className="form-group">
      {label && <label className="form-label">{label}</label>}
      {children}
      {hint && <span className="form-hint">{hint}</span>}
    </div>
  )
}

export function InfoBox({ variant = 'brand', icon, children, style }) {
  const map = {
    brand:   { bg:'var(--brand-dim)',   border:'var(--brand-glow)',  text:'var(--text-2)' },
    danger:  { bg:'var(--red-dim)',     border:'var(--red-glow)',    text:'var(--red)' },
    success: { bg:'var(--green-dim)',   border:'var(--green-glow)',  text:'var(--text-2)' },
    amber:   { bg:'var(--amber-dim)',   border:'rgba(245,158,11,.2)',text:'var(--text-2)' },
  }
  const s = map[variant] || map.brand

  return (
    <div style={{ background:s.bg, border:`1px solid ${s.border}`,
      borderRadius:'var(--r-md)', padding:'12px 16px',
      fontSize:12.5, color:s.text, lineHeight:1.7, display:'flex', gap:10, alignItems:'flex-start', ...style }}>
      {icon && <span style={{ flexShrink:0, marginTop:1 }}>{icon}</span>}
      <div>{children}</div>
    </div>
  )
}

export function SectionCard({ icon, title, description, children }) {
  return (
    <div className="settings-card" style={{ padding:'20px 22px' }}>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:6 }}>
        <span style={{ color:'var(--brand)', display:'flex' }}>{icon}</span>
        <span style={{ fontSize:14, fontWeight:700, color:'var(--text-1)' }}>{title}</span>
      </div>
      {description && (
        <div style={{ fontSize:12.5, color:'var(--text-3)', marginBottom:18, lineHeight:1.5 }}>
          {description}
        </div>
      )}
      {children}
    </div>
  )
}

export function SaveBtn({ saving, onClick, label = 'Save Changes', saveIcon }) {
  return (
    <button className="btn btn-primary" onClick={onClick} disabled={saving}
      style={{ display:'inline-flex', alignItems:'center', gap:7 }}>
      {saving ? (
        <><span className="spinner" style={{ width:13, height:13 }} /> Saving...</>
      ) : (
        <>{saveIcon} {label}</>
      )}
    </button>
  )
}

export function PwdStrength({ pwd, checkIcon, circleIcon }) {
  if (!pwd) return null

  const checks = [
    { ok: pwd.length >= 8,           label:'8+ chars'  },
    { ok: /[A-Z]/.test(pwd),         label:'Upper'     },
    { ok: /[a-z]/.test(pwd),         label:'Lower'     },
    { ok: /\d/.test(pwd),            label:'Number'    },
    { ok: /[^A-Za-z0-9]/.test(pwd),  label:'Symbol'    },
  ]
  const score = checks.filter(c => c.ok).length
  const color = ['var(--red)','var(--red)','var(--amber)','var(--amber)','var(--green)'][score - 1] || 'var(--border-1)'

  return (
    <div style={{ marginTop:8 }}>
      <div style={{ display:'flex', gap:3, marginBottom:6 }}>
        {checks.map((_, i) => (
          <div key={i} style={{ flex:1, height:3, borderRadius:2,
            background: i < score ? color : 'var(--border-1)', transition:'background .2s' }} />
        ))}
      </div>
      <div style={{ display:'flex', gap:12, flexWrap:'wrap' }}>
        {checks.map(c => (
          <span key={c.label} style={{ fontSize:11, display:'inline-flex', alignItems:'center', gap:4,
            color: c.ok ? 'var(--green)' : 'var(--text-3)' }}>
            {c.ok ? checkIcon : circleIcon} {c.label}
          </span>
        ))}
      </div>
    </div>
  )
}

export function Stat({ label, value }) {
  return (
    <div style={{ display:'flex', flexDirection:'column', gap:3 }}>
      <span style={{ fontSize:11, textTransform:'uppercase', letterSpacing:'.05em',
        color:'var(--text-3)', fontWeight:600 }}>{label}</span>
      <span style={{ fontSize:13.5, color:'var(--text-1)' }}>{value}</span>
    </div>
  )
}

export function UploadButton({ fileRef, uploading, onChange, uploadIcon }) {
  return (
    <>
      <input
        ref={fileRef}
        type="file"
        accept=".key,.json,application/json"
        style={{ display:'none' }}
        onChange={onChange}
      />
      <button
        className="btn btn-primary"
        onClick={() => fileRef.current?.click()}
        disabled={uploading}
        style={{ display:'inline-flex', alignItems:'center', gap:7 }}>
        {uploading ? (
          <><span className="spinner" style={{ width:13, height:13 }} /> Verifying...</>
        ) : (
          <>{uploadIcon} Choose license.key File</>
        )}
      </button>
    </>
  )
}
