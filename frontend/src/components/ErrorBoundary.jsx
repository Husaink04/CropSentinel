/**
 * CropSentinel — ErrorBoundary
 * ════════════════════════════
 * Catches render / lazy-load failures so a bad chunk doesn't white-screen the
 * whole app. Two common failure modes this handles:
 *
 *  1. **Chunk-load errors** — Vite hashes lazy chunks by content. After a new
 *     deploy, a browser tab open since yesterday still references the old
 *     hashes; `import()` fails with `ChunkLoadError` / `Failed to fetch
 *     dynamically imported module`. We detect those and show a "reload"
 *     prompt instead of a blank page.
 *
 *  2. **Any other render-time throw** — generic fallback with the error
 *     message (in dev) and a reload button.
 *
 * Wrap the `<Suspense>` in `main.jsx` with this boundary. We deliberately
 * keep it as a class component because hooks cannot implement
 * `componentDidCatch` / `getDerivedStateFromError`.
 */

import React from 'react'
import * as Sentry from '@sentry/react'

const CHUNK_ERROR_PATTERNS = [
  /Loading chunk [\d]+ failed/i,
  /Loading CSS chunk/i,
  /ChunkLoadError/i,
  /Failed to fetch dynamically imported module/i,
  /Importing a module script failed/i,
]

function isChunkLoadError(err) {
  if (!err) return false
  const msg = err.message || String(err)
  return CHUNK_ERROR_PATTERNS.some(re => re.test(msg))
}

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null, isChunkError: false }
  }

  static getDerivedStateFromError(error) {
    return { error, isChunkError: isChunkLoadError(error) }
  }

  componentDidCatch(error, info) {
    Sentry.captureException(error, {
      extra: { componentStack: info?.componentStack || '' },
    })
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', error, info?.componentStack)
  }

  handleReload = () => {
    // Hard reload to pull fresh chunk hashes.
    window.location.reload()
  }

  handleReset = () => {
    this.setState({ error: null, isChunkError: false })
  }

  render() {
    const { error, isChunkError } = this.state
    if (!error) return this.props.children

    const isDev = import.meta.env?.DEV

    return (
      <div
        role="alert"
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
          background: 'var(--bg, #0a0e1a)',
          fontFamily: "'Inter', system-ui, sans-serif",
          color: 'var(--text-1, #f1f5f9)',
        }}
      >
        <div
          style={{
            maxWidth: 460,
            width: '100%',
            padding: '32px 28px',
            borderRadius: 14,
            background: 'var(--surface, rgba(15,23,42,0.8))',
            border: '1px solid rgba(239,68,68,0.25)',
            boxShadow: '0 20px 48px rgba(0,0,0,0.4)',
          }}
        >
          <div style={{ fontSize: 28, marginBottom: 12 }}>⚠️</div>
          <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>
            {isChunkError ? 'A new version is available' : 'Something went wrong'}
          </div>
          <div style={{ fontSize: 14, color: 'var(--text-3, #7C8AA0)', lineHeight: 1.5, marginBottom: 20 }}>
            {isChunkError
              ? 'This page failed to load because the app was updated. Reload to get the latest version.'
              : 'An unexpected error broke this view. You can try again, or reload the page.'}
          </div>

          {isDev && !isChunkError && (
            <pre
              style={{
                fontSize: 11,
                background: 'rgba(239,68,68,0.08)',
                border: '1px solid rgba(239,68,68,0.2)',
                color: '#fca5a5',
                padding: 10,
                borderRadius: 6,
                overflow: 'auto',
                maxHeight: 160,
                marginBottom: 16,
                whiteSpace: 'pre-wrap',
              }}
            >
              {error.message || String(error)}
            </pre>
          )}

          <div style={{ display: 'flex', gap: 10 }}>
            <button
              onClick={this.handleReload}
              style={{
                flex: 1,
                padding: '10px 16px',
                borderRadius: 8,
                border: 'none',
                cursor: 'pointer',
                fontSize: 14,
                fontWeight: 600,
                color: '#fff',
                background: 'linear-gradient(135deg, #6366f1, #7c3aed)',
              }}
            >
              Reload page
            </button>
            {!isChunkError && (
              <button
                onClick={this.handleReset}
                style={{
                  flex: 1,
                  padding: '10px 16px',
                  borderRadius: 8,
                  border: '1px solid rgba(148,163,184,0.25)',
                  cursor: 'pointer',
                  fontSize: 14,
                  fontWeight: 600,
                  color: 'var(--text-1, #f1f5f9)',
                  background: 'transparent',
                }}
              >
                Try again
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }
}
