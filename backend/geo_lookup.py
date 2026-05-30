"""
Geo-IP lookup utility for CropSentinel.

Uses ip-api.com (free, no key, 45 req/min per IP).
All results are cached in-process so each unique client IP is only
ever looked up once per server restart — no rate-limit risk in practice.

Private/loopback addresses return an empty dict immediately without hitting
the network.
"""
import asyncio
import json
import logging
import urllib.request
from typing import Optional

logger = logging.getLogger("croppro.geo")

# In-process cache: ip -> geo dict (or {} for failed/private lookups).
# Never evicted — the set of unique agent IPs is small and stable.
_cache: dict[str, dict] = {}

_PRIVATE_PREFIXES = (
    "10.", "192.168.", "127.", "::1", "fc", "fd",
    "169.254.",           # link-local
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
)

_API_URL = "http://ip-api.com/json/{ip}?fields=status,country,countryCode,city,isp,org,lat,lon"
_TIMEOUT  = 4  # seconds — tight so heartbeats are never noticeably delayed


def _is_private(ip: str) -> bool:
    return any(ip.startswith(p) for p in _PRIVATE_PREFIXES)


def lookup_sync(ip: str) -> dict:
    """Synchronous lookup. Safe to call from threads."""
    if not ip or _is_private(ip):
        return {}
    if ip in _cache:
        return _cache[ip]
    try:
        url = _API_URL.format(ip=ip)
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:  # noqa: S310
            data = json.loads(resp.read())
        if data.get("status") == "success":
            result = {
                "geo_country":      data.get("country", ""),
                "geo_country_code": data.get("countryCode", ""),
                "geo_city":         data.get("city", ""),
                "geo_isp":          data.get("isp", ""),
                "geo_org":          data.get("org", ""),
                "geo_lat":          data.get("lat"),
                "geo_lon":          data.get("lon"),
            }
        else:
            result = {}
        _cache[ip] = result
        logger.debug("Geo lookup %s → %s, %s", ip,
                     result.get("geo_city", "?"), result.get("geo_country", "?"))
        return result
    except Exception as exc:
        logger.debug("Geo lookup failed for %s: %s", ip, exc)
        _cache[ip] = {}   # cache the failure so we don't retry every heartbeat
        return {}


async def lookup(ip: str) -> dict:
    """Async wrapper — runs the blocking lookup in a thread-pool executor."""
    if not ip or _is_private(ip):
        return {}
    if ip in _cache:
        return _cache[ip]
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lookup_sync, ip)
