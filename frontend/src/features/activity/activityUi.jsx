import React from 'react'

export function ActivityToolbar({
  machines = [],
  selectedId = '',
  onMachineChange,
  machineLabel = 'All Machines',
  search = '',
  onSearchChange,
  searchPlaceholder = 'Search...',
  date = '',
  onDateChange,
  extraFilters = null,
  rightActions = null,
  onClear,
  clearable = false,
}) {
  return (
    <div className="filter-bar activity-toolbar analytics-toolbar machine-calm-card">
      {typeof onMachineChange === 'function' && (
        <select className="input-field machine-calm-search analytics-field" value={selectedId} onChange={(e) => onMachineChange(e.target.value)} style={{ maxWidth: 220, fontSize: 12 }}>
          <option value="">{machineLabel}</option>
          {machines.map((machine) => (
            <option key={machine.machine_id} value={machine.machine_id}>
              {machine.hostname || machine.machine_id.slice(0, 10)}
            </option>
          ))}
        </select>
      )}
      {typeof onSearchChange === 'function' && (
        <input
          className="input-field machine-calm-search analytics-field"
          placeholder={searchPlaceholder}
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          style={{ flex: 1, minWidth: 180, fontSize: 12 }}
        />
      )}
      {typeof onDateChange === 'function' && (
        <input
          className="input-field machine-calm-search analytics-field"
          type="date"
          value={date}
          onChange={(e) => onDateChange(e.target.value)}
          style={{ maxWidth: 160, fontSize: 12 }}
        />
      )}
      {extraFilters}
      {clearable && onClear && (
        <button className="btn btn-outline machine-calm-btn btn-sm" onClick={onClear}>
          Clear
        </button>
      )}
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
        {rightActions}
      </div>
    </div>
  )
}

export function ActivityDrawer({
  open,
  title,
  subtitle,
  badges = [],
  onClose,
  children,
  footer,
}) {
  if (!open) return null
  return (
    <div className="activity-drawer-overlay slide-in" role="presentation" onClick={onClose}>
      <aside className="activity-drawer" role="dialog" aria-modal="true" aria-label={title || 'Activity details'} onClick={(e) => e.stopPropagation()}>
        <div className="activity-drawer-header">
          <div>
            <div className="activity-drawer-title">{title}</div>
            {subtitle && <div className="activity-drawer-subtitle">{subtitle}</div>}
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close details">
            Close
          </button>
        </div>
        {badges.length > 0 && (
          <div className="activity-drawer-badges">
            {badges.map((badge, index) => (
              <span key={index} className="activity-drawer-badge" style={badge.style || {}}>
                {badge.label}
              </span>
            ))}
          </div>
        )}
        <div className="activity-drawer-body">{children}</div>
        {footer && <div className="activity-drawer-footer">{footer}</div>}
      </aside>
    </div>
  )
}
