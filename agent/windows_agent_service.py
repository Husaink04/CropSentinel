from __future__ import annotations

import sys
import threading
import time
import traceback
from pathlib import Path

import servicemanager
import win32con
import win32event
import win32process
import win32profile
import win32security
import win32service
import win32serviceutil
import win32ts


POLL_SECONDS = 5
WORKER_ARGS = "--service-worker"


class ActiveSessionAgentSupervisor:
    def __init__(self, stop_event: threading.Event):
        self._stop_event = stop_event
        self._lock = threading.Lock()
        self._session_id: int | None = None
        self._proc_handle = None
        self._thread_handle = None
        self._pid: int | None = None
        self._worker_exe = self._resolve_worker_exe()

    def _resolve_worker_exe(self) -> Path:
        current = Path(sys.executable).resolve()
        candidate = current.with_name("cropsentinel-agent.exe")
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Agent worker executable not found next to service host: {candidate}")

    def _active_console_session_id(self) -> int | None:
        sid = win32ts.WTSGetActiveConsoleSessionId()
        if sid in (None, 0xFFFFFFFF):
            return None
        return int(sid)

    def _worker_running(self) -> bool:
        if not self._proc_handle:
            return False
        code = win32process.GetExitCodeProcess(self._proc_handle)
        return code == win32con.STILL_ACTIVE

    def _close_handles(self) -> None:
        for handle in (self._thread_handle, self._proc_handle):
            if handle:
                try:
                    handle.Close()
                except Exception:
                    pass
        self._thread_handle = None
        self._proc_handle = None
        self._pid = None

    def _terminate_worker(self) -> None:
        with self._lock:
            if self._proc_handle and self._worker_running():
                try:
                    win32process.TerminateProcess(self._proc_handle, 0)
                except Exception:
                    pass
            self._close_handles()
            self._session_id = None

    def _launch_worker_for_session(self, session_id: int) -> None:
        user_token = None
        primary_token = None
        env = None
        try:
            user_token = win32ts.WTSQueryUserToken(session_id)
            primary_token = win32security.DuplicateTokenEx(
                user_token,
                win32con.MAXIMUM_ALLOWED,
                win32security.SECURITY_ATTRIBUTES(),
                win32security.SecurityImpersonation,
                win32security.TokenPrimary,
            )
            env = win32profile.CreateEnvironmentBlock(primary_token, False)
            startup = win32process.STARTUPINFO()
            startup.lpDesktop = "winsta0\\default"
            startup.dwFlags |= win32con.STARTF_USESHOWWINDOW
            startup.wShowWindow = win32con.SW_HIDE
            command = f'"{self._worker_exe}" {WORKER_ARGS}'
            flags = win32con.CREATE_UNICODE_ENVIRONMENT | win32con.NORMAL_PRIORITY_CLASS
            proc_handle, thread_handle, pid, _tid = win32process.CreateProcessAsUser(
                primary_token,
                str(self._worker_exe),
                command,
                None,
                None,
                False,
                flags,
                env,
                str(self._worker_exe.parent),
                startup,
            )
            with self._lock:
                self._proc_handle = proc_handle
                self._thread_handle = thread_handle
                self._pid = int(pid)
                self._session_id = int(session_id)
            servicemanager.LogInfoMsg(
                f"CropSentinel worker launched in session {session_id} with pid {pid}"
            )
        finally:
            if env is not None:
                try:
                    win32profile.DestroyEnvironmentBlock(env)
                except Exception:
                    pass
            for token in (primary_token, user_token):
                if token:
                    try:
                        token.Close()
                    except Exception:
                        pass

    def run(self) -> None:
        while not self._stop_event.wait(POLL_SECONDS):
            active_session = self._active_console_session_id()
            worker_running = self._worker_running()

            if active_session is None:
                if worker_running:
                    servicemanager.LogInfoMsg("No active console session; stopping user-session worker")
                    self._terminate_worker()
                continue

            if worker_running and self._session_id == active_session:
                continue

            if worker_running:
                servicemanager.LogInfoMsg(
                    f"Restarting user-session worker due to session change or worker drift "
                    f"(old_session={self._session_id}, new_session={active_session})"
                )
                self._terminate_worker()

            try:
                self._launch_worker_for_session(active_session)
            except Exception:
                servicemanager.LogErrorMsg(traceback.format_exc())

        self._terminate_worker()


class CropSentinelAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "CropSentinelAgent"
    _svc_display_name_ = "CropSentinel Agent"
    _svc_description_ = "CropSentinel monitoring agent service."

    def __init__(self, args):
        super().__init__(args)
        self._stop_event = threading.Event()
        self._supervisor = ActiveSessionAgentSupervisor(self._stop_event)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._stop_event.set()

    def SvcDoRun(self):
        servicemanager.LogInfoMsg(f"{self._svc_name_} starting")
        try:
            self._supervisor.run()
        except Exception:
            servicemanager.LogErrorMsg(traceback.format_exc())
            raise
        finally:
            servicemanager.LogInfoMsg(f"{self._svc_name_} stopped")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(CropSentinelAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(CropSentinelAgentService)
