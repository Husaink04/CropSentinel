"""
CropSentinel — Print Activity Tracker
Monitors print jobs on Windows via win32print API.
Falls back gracefully on non-Windows platforms.
"""
import time
import logging
import platform
from datetime import datetime, timezone

logger = logging.getLogger("croppro.print")

OS = platform.system()


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


class PrintTracker:
    """Polls the Windows print spooler for new jobs."""

    def __init__(self, machine_id: str, enqueue_fn, interval: int = 10):
        self.machine_id = machine_id
        self.enqueue = enqueue_fn
        self.interval = interval
        self.seen_jobs = set()
        self.running = True

    def run(self):
        if OS != "Windows":
            logger.info("Print tracking only supported on Windows — skipping")
            return

        try:
            import win32print
        except ImportError:
            logger.warning("win32print not available — install pywin32 for print tracking")
            return

        logger.info("Print tracker started")
        while self.running:
            try:
                self._poll(win32print)
            except Exception as e:
                logger.debug(f"Print poll error: {e}")
            time.sleep(self.interval)

    def _poll(self, win32print):
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        printers = win32print.EnumPrinters(flags, None, 1)

        for _, _, printer_name, _ in printers:
            try:
                handle = win32print.OpenPrinter(printer_name)
                try:
                    jobs = win32print.EnumJobs(handle, 0, 100, 1)
                    for job in jobs:
                        job_id = (printer_name, job["JobId"])
                        if job_id in self.seen_jobs:
                            continue
                        self.seen_jobs.add(job_id)

                        doc_name = job.get("pDocument", "Unknown")
                        pages = job.get("TotalPages", 0)

                        data = {
                            "machine_id": self.machine_id,
                            "timestamp": _utcnow_iso(),
                            "document": doc_name,
                            "printer": printer_name,
                            "pages": pages,
                        }
                        self.enqueue("print", data)
                        logger.info(f"Print job: {doc_name} ({pages}p) on {printer_name}")
                finally:
                    win32print.ClosePrinter(handle)
            except Exception as e:
                logger.debug(f"Error reading printer {printer_name}: {e}")

        # Prune old job IDs to prevent memory growth
        if len(self.seen_jobs) > 1000:
            self.seen_jobs = set(list(self.seen_jobs)[-500:])

    def stop(self):
        self.running = False
