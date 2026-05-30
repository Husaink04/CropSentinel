import { useCallback, useEffect, useMemo, useState } from 'react'
import { UI_STATES, useApi, useWsListener } from '../../hooks/useAuth'

function buildQuery(params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value == null || value === '') return
    query.set(key, String(value))
  })
  return query.toString()
}

export function useActivityMachines({ defaultMode = 'first' } = {}) {
  const { get } = useApi()
  const [machines, setMachines] = useState([])
  const [selectedId, setSelectedId] = useState(defaultMode === 'all' ? '' : '')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    setLoading(true)
    get('/api/machines')
      .then((rows) => {
        if (!active) return
        setMachines(rows || [])
        setSelectedId((current) => {
          if (current) return current
          if (defaultMode === 'all') return ''
          return rows?.[0]?.machine_id || ''
        })
      })
      .catch(() => {
        if (!active) return
        setMachines([])
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [defaultMode, get])

  return { machines, selectedId, setSelectedId, loading }
}

export function useActivityFeed({
  endpoint,
  params,
  realtimeTypes = [],
  enabled = true,
}) {
  const { get } = useApi()
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)

  const realtimeKey = useMemo(() => realtimeTypes.join('|'), [realtimeTypes])
  const query = useMemo(() => buildQuery(params), [JSON.stringify(params || {})])

  const fetchFeed = useCallback(async (refreshMode = false) => {
    if (!enabled) {
      setItems([])
      setTotal(0)
      setStats(null)
      setLoading(false)
      setRefreshing(false)
      return
    }
    if (refreshMode) setRefreshing(true)
    else setLoading(true)
    try {
      const payload = await get(`${endpoint}${query ? `?${query}` : ''}`)
      setItems(payload?.items || [])
      setTotal(payload?.total || 0)
      setStats(payload?.stats || null)
      setError(null)
    } catch (err) {
      setItems([])
      setTotal(0)
      setStats(null)
      setError(err)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [enabled, endpoint, get, query])

  useEffect(() => {
    fetchFeed(false).catch(() => {})
  }, [fetchFeed])

  useWsListener(useCallback((msg) => {
    if (!enabled) return
    if (realtimeTypes.includes(msg.type)) {
      fetchFeed(true).catch(() => {})
    }
  }, [enabled, fetchFeed, realtimeKey]))

  const refresh = useCallback(() => fetchFeed(true), [fetchFeed])

  const uiState = loading
    ? UI_STATES.LOADING
    : error
      ? UI_STATES.ERROR
      : items.length === 0
        ? UI_STATES.EMPTY
        : UI_STATES.READY

  return {
    items,
    total,
    stats,
    loading,
    refreshing,
    error,
    uiState,
    refresh,
  }
}
