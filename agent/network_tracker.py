"""
CropSentinel — Network Activity Tracker
Monitors open/listening ports, active connections, per-process network usage,
and byte-counter deltas.  Sends periodic snapshots to the backend.
"""
import time
import socket
import logging
import platform
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger("croppro.network")


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _resolve_domain(ip: str) -> str:
    """Best-effort reverse DNS lookup, cached."""
    if ip in _resolve_domain._cache:
        return _resolve_domain._cache[ip]
    try:
        host = socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, OSError):
        host = ip
    _resolve_domain._cache[ip] = host
    if len(_resolve_domain._cache) > 2000:
        _resolve_domain._cache.clear()
    return host

_resolve_domain._cache = {}


def _safe_proc_name(pid):
    """Get process name from PID, or return empty string."""
    try:
        import psutil
        p = psutil.Process(pid)
        return p.name()
    except Exception:
        return ""


class NetworkTracker:
    """Periodically samples network state: open ports, connections, bandwidth."""

    def __init__(self, machine_id: str, enqueue_fn, interval: int = 30):
        self.machine_id = machine_id
        self.enqueue = enqueue_fn
        self.interval = interval
        self.running = True
        self._prev_bytes_sent = 0
        self._prev_bytes_recv = 0

    def run(self):
        try:
            import psutil
        except ImportError:
            logger.warning("psutil not installed — network tracking disabled")
            return

        logger.info("Network tracker started")
        counters = psutil.net_io_counters()
        self._prev_bytes_sent = counters.bytes_sent
        self._prev_bytes_recv = counters.bytes_recv

        while self.running:
            try:
                self._sample(psutil)
            except Exception as e:
                logger.debug(f"Network sample error: {e}")
            time.sleep(self.interval)

    def _sample(self, psutil):
        ts = _utcnow_iso()

        # ── Byte deltas ──────────────────────────────────────────
        counters = psutil.net_io_counters()
        delta_sent = max(0, counters.bytes_sent - self._prev_bytes_sent)
        delta_recv = max(0, counters.bytes_recv - self._prev_bytes_recv)
        self._prev_bytes_sent = counters.bytes_sent
        self._prev_bytes_recv = counters.bytes_recv

        # ── Scan connections ─────────────────────────────────────
        listening = []       # ports this machine is listening on
        connections = []     # active outbound/established connections
        seen_listen = set()
        seen_conn = set()

        try:
            for conn in psutil.net_connections(kind="inet"):
                laddr = conn.laddr
                raddr = conn.raddr
                pid = conn.pid or 0
                proto = "tcp" if conn.type == socket.SOCK_STREAM else "udp"
                proc = _safe_proc_name(pid) if pid else ""

                # Listening ports
                if conn.status == "LISTEN" and laddr:
                    port = laddr.port
                    key = (port, proto, proc)
                    if key not in seen_listen:
                        seen_listen.add(key)
                        listening.append({
                            "port": port,
                            "protocol": proto,
                            "process": proc,
                            "pid": pid,
                            "address": laddr.ip,
                        })

                # Established connections
                elif conn.status == "ESTABLISHED" and raddr:
                    remote_ip = raddr.ip
                    if remote_ip.startswith("127.") or remote_ip.startswith("0."):
                        continue
                    remote_port = raddr.port
                    key = (remote_ip, remote_port, proto, proc)
                    if key not in seen_conn:
                        seen_conn.add(key)
                        domain = _resolve_domain(remote_ip)
                        connections.append({
                            "remote_ip": remote_ip,
                            "remote_port": remote_port,
                            "local_port": laddr.port if laddr else 0,
                            "domain": domain,
                            "protocol": proto,
                            "process": proc,
                            "pid": pid,
                        })
        except (psutil.AccessDenied, PermissionError):
            pass

        # Sort: listening by port, connections by process
        listening.sort(key=lambda x: x["port"])
        connections.sort(key=lambda x: x.get("process", ""))

        # ── Build snapshot ───────────────────────────────────────
        data = {
            "machine_id": self.machine_id,
            "timestamp": ts,
            "bytes_sent": delta_sent,
            "bytes_recv": delta_recv,
            "total_sent": counters.bytes_sent,
            "total_recv": counters.bytes_recv,
            "listening_ports": listening[:50],     # cap to avoid huge payloads
            "connections": connections[:100],
            "listen_count": len(listening),
            "conn_count": len(connections),
        }

        self.enqueue("network", data)

    def stop(self):
        self.running = False
