import React from 'react'

export function InlineBanner({ tone = 'info', title, message, actionLabel, onAction, onClose }) {
  const cls = `ui-inline-banner ui-inline-banner-${tone}`
  return (
    <div className={cls} role={tone === 'danger' ? 'alert' : 'status'}>
      <div className="ui-inline-banner-copy">
        {title && <strong>{title}</strong>}
        {message && <span>{message}</span>}
      </div>
      <div className="ui-inline-banner-actions">
        {actionLabel && onAction && (
          <button className="btn btn-ghost btn-sm" onClick={onAction}>
            {actionLabel}
          </button>
        )}
        {onClose && (
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Dismiss">
            Close
          </button>
        )}
      </div>
    </div>
  )
}

export function PageStateView({
  state,
  title,
  message,
  retryLabel = 'Retry',
  onRetry,
  children,
}) {
  if (state === 'loading') {
    return (
      <div className="loading-center">
        <div className="spinner" style={{ width: 28, height: 28 }} />
      </div>
    )
  }

  if (state === 'error') {
    return (
      <div className="empty-state">
        <div className="empty-state-title">{title || 'Something went wrong'}</div>
        <div className="empty-state-sub">{message || 'This view failed to load.'}</div>
        {onRetry && (
          <button className="btn btn-outline btn-sm" onClick={onRetry}>
            {retryLabel}
          </button>
        )}
      </div>
    )
  }

  if (state === 'empty') {
    return (
      <div className="empty-state">
        <div className="empty-state-title">{title || 'No data found'}</div>
        <div className="empty-state-sub">{message || 'Nothing to display for this filter.'}</div>
      </div>
    )
  }

  if (state === 'partial') {
    return (
      <>
        <InlineBanner
          tone="warning"
          title={title || 'Some data could not be loaded'}
          message={message || 'This view is showing partial information.'}
          actionLabel={onRetry ? retryLabel : undefined}
          onAction={onRetry}
        />
        {children}
      </>
    )
  }

  return children
}
