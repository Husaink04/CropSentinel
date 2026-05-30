from __future__ import annotations

import sys
import threading
import traceback

import servicemanager
import win32service
import win32serviceutil

from watchdog import run_watchdog


class CropSentinelWatchdogService(win32serviceutil.ServiceFramework):
    _svc_name_ = "CropSentinelWatchdog"
    _svc_display_name_ = "CropSentinel Watchdog"
    _svc_description_ = "CropSentinel self-heal watchdog service."

    def __init__(self, args):
        super().__init__(args)
        self._stop_event = threading.Event()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._stop_event.set()

    def SvcDoRun(self):
        servicemanager.LogInfoMsg(f"{self._svc_name_} starting")
        try:
            run_watchdog(stop_event=self._stop_event)
        except Exception:
            servicemanager.LogErrorMsg(traceback.format_exc())
            raise
        finally:
            servicemanager.LogInfoMsg(f"{self._svc_name_} stopped")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(CropSentinelWatchdogService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(CropSentinelWatchdogService)
