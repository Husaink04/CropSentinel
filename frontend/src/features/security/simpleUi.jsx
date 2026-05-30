import React from 'react'

export function SimpleSection({ title, subtitle, action, children }) {
  return (
    <div className="card machine-calm-card control-card">
      <div className="card-header" style={{ alignItems: 'flex-start' }}>
        <div>
          <div className="card-title">{title}</div>
          {subtitle && <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text-3)' }}>{subtitle}</div>}
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}

export function SimpleBadge({ tone = 'default', children }) {
  const tones = {
    default: { bg: 'var(--surface-2)', text: 'var(--text-2)' },
    info: { bg: 'rgba(59,130,246,.12)', text: '#1D4ED8' },
    success: { bg: 'rgba(16,185,129,.12)', text: '#047857' },
    warning: { bg: 'rgba(245,158,11,.12)', text: '#B45309' },
    danger: { bg: 'rgba(239,68,68,.12)', text: '#B91C1C' },
  }
  const toneColors = tones[tone] || tones.default
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      padding: '4px 10px',
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 700,
      background: toneColors.bg,
      color: toneColors.text,
      whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  )
}

export function ChoiceGrid({ value, onChange, options }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
      {options.map(option => {
        const active = value === option.value
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className="card machine-calm-card control-card"
            style={{
              textAlign: 'left',
              padding: 16,
              border: active ? '1px solid var(--brand)' : '1px solid var(--border-0)',
              background: active ? 'rgba(59,130,246,.06)' : 'var(--surface-1)',
              boxShadow: active ? '0 8px 24px rgba(59,130,246,.08)' : 'none',
              cursor: 'pointer',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
              <strong style={{ fontSize: 15 }}>{option.label}</strong>
              {active && <SimpleBadge tone="info">Selected</SimpleBadge>}
            </div>
            <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text-3)', lineHeight: 1.5 }}>
              {option.description}
            </div>
          </button>
        )
      })}
    </div>
  )
}

export function SimpleBulletList({ items }) {
  if (!items?.length) {
    return <div style={{ color: 'var(--text-3)', fontSize: 13 }}>None</div>
  }
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {items.map(item => (
        <div
          key={item}
          style={{
            padding: '10px 12px',
            borderRadius: 12,
            border: '1px solid var(--border-0)',
            background: 'var(--surface-2)',
            fontSize: 13,
          }}
        >
          {item}
        </div>
      ))}
    </div>
  )
}

export function SimpleKeyValue({ items }) {
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {items.map(item => (
        <div key={item.label} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13 }}>
          <span style={{ color: 'var(--text-3)' }}>{item.label}</span>
          <strong style={{ textAlign: 'right' }}>{item.value}</strong>
        </div>
      ))}
    </div>
  )
}
