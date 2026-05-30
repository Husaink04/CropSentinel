/**
 * CropSentinel — WebRTC ICE server config hook
 * ════════════════════════════════════════════
 * Fetches the admin-configured ICE server list from `/api/settings/ice-servers`
 * once per session and caches it in-memory. LiveView and RemoteAccess both
 * call this hook so TURN credentials can be rotated from the Settings UI
 * without a client rebuild.
 *
 * The hook never blocks — it returns a sensible public-STUN default
 * immediately, then swaps to the fetched list when it arrives.
 */

import { useEffect, useState } from 'react'
import { useApi } from './useAuth'

const DEFAULT_ICE_SERVERS = [{
  urls: ['stun:stun.l.google.com:19302', 'stun:stun1.l.google.com:19302'],
}]

// Module-scoped cache — shared across all components that use this hook.
let _cache = null
let _inflight = null

export function useIceServers() {
  const { get } = useApi()
  const [iceServers, setIceServers] = useState(_cache || DEFAULT_ICE_SERVERS)

  useEffect(() => {
    if (_cache) { setIceServers(_cache); return }
    if (!_inflight) {
      _inflight = get('/api/settings/ice-servers')
        .then(data => {
          _cache = Array.isArray(data?.ice_servers) && data.ice_servers.length
            ? data.ice_servers
            : DEFAULT_ICE_SERVERS
          return _cache
        })
        .catch(() => DEFAULT_ICE_SERVERS)
        .finally(() => { /* keep _cache */ })
    }
    let cancelled = false
    _inflight.then(list => { if (!cancelled) setIceServers(list) })
    return () => { cancelled = true }
  }, [get])

  return iceServers
}

// Exported for Settings save handlers that want to invalidate the cache
// after the admin updates the ICE config.
export function invalidateIceServersCache() {
  _cache = null
  _inflight = null
}
