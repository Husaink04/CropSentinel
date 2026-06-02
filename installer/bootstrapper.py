r"""CropSentinel agent installer bootstrapper.

This is a single Windows EXE installer built with PyInstaller. It:
- shows a consent screen
- reads tenant config from a sidecar config.env when present
- requests elevation when the user starts installation
- copies the native worker + native session-supervisor payload into Program Files
- writes C:\ProgramData\CropSentinel\config.env
- installs the native session-supervisor Windows service under LocalSystem
- applies locked-down ACLs so only SYSTEM or administrators can modify payload
- configures service recovery and starts the service immediately
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


APP_NAME = "CropSentinel Installer"
VERSION = "1.3.0"
PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "CropSentinel"
INSTALL_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "CropSentinel Agent"
CONFIG_PATH = PROGRAM_DATA / "config.env"
PAYLOAD_MANIFEST = "payload-manifest.json"
PAYLOAD_MANIFEST_PATH = PROGRAM_DATA / PAYLOAD_MANIFEST
PAYLOAD_CACHE_DIR = PROGRAM_DATA / "payload-cache"
AGENT_SERVICE = "CropSentinelAgent"
AGENT_EXE_NAME = "cropsentinel-agent-native.exe"
AGENT_SERVICE_EXE_NAME = "cropsentinel-agent-service.exe"
APP_ICON_NAME = "app.ico"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate(args: list[str]) -> None:
    param_str = subprocess.list2cmdline(args)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, param_str, None, 1)


def is_quiet_mode() -> bool:
    return "--quiet" in sys.argv


def show_info(message: str) -> None:
    if is_quiet_mode():
        return
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(APP_NAME, message)
    root.destroy()


def show_error(message: str) -> None:
    if is_quiet_mode():
        return
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(APP_NAME, message)
    root.destroy()


def exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", exe_dir()))
    candidate = base / name
    if candidate.exists():
        return candidate
    fallback = exe_dir() / "dist" / "cropsentinel-agent" / name
    if fallback.exists():
        return fallback
    return candidate


def _run(args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        check=check,
        capture_output=True,
        text=True,
        creationflags=_NO_WINDOW,
    )


def _run_sc(args: list[str]) -> subprocess.CompletedProcess:
    return _run(["sc.exe", *args], check=False)


def load_sidecar_config() -> dict[str, str]:
    candidates = [
        exe_dir() / "config.env",
        Path(sys.executable).resolve().with_name("config.env"),
        Path(__file__).resolve().with_name("config.env"),
    ]
    data: dict[str, str] = {}
    for path in candidates:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
        if data:
            break
    return data


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def load_payload_manifest() -> dict[str, object]:
    payload_root = resource_path("cropsentinel-agent")
    manifest_path = payload_root / PAYLOAD_MANIFEST
    if not manifest_path.exists():
        manifest_path = resource_path(PAYLOAD_MANIFEST)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing bundled payload manifest: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def verify_bundled_payload() -> dict[str, object]:
    manifest = load_payload_manifest()
    payload_root = resource_path("cropsentinel-agent")
    files = manifest.get("files") or []
    if not isinstance(files, list) or not files:
        raise RuntimeError("Bundled payload manifest is empty.")

    for entry in files:
        relative = entry.get("path")
        expected_hash = (entry.get("sha256") or "").lower()
        if not relative or not expected_hash:
            raise RuntimeError("Bundled payload manifest contains an invalid entry.")
        source = payload_root / Path(str(relative).replace("/", os.sep))
        if not source.exists():
            raise FileNotFoundError(f"Missing bundled payload file: {source}")
        actual_hash = compute_sha256(source)
        if actual_hash != expected_hash:
            raise RuntimeError(f"Bundled payload integrity check failed for {relative}")

    return manifest


def normalize_config(values: dict[str, str]) -> str:
    server = (values.get("CROPSENTINEL_SERVER") or values.get("CROPPRO_SERVER") or "http://localhost:8000").strip()
    token = (values.get("CROPSENTINEL_ENROLL_TOKEN") or values.get("CROPPRO_ENROLL_TOKEN") or "").strip()
    agent_key = (values.get("CROPSENTINEL_AGENT_KEY") or values.get("CROPPRO_AGENT_KEY") or "").strip()
    stop_hash = (values.get("AGENT_STOP_PASSWORD_HASH") or values.get("CROPSENTINEL_STOP_PASSWORD_HASH") or "").strip()
    screenshot_interval = (values.get("CROPSENTINEL_SCREENSHOT_INTERVAL") or values.get("CROPPRO_SCREENSHOT_INTERVAL") or "60").strip()
    sync_interval = (values.get("CROPSENTINEL_SYNC_INTERVAL") or values.get("CROPPRO_SYNC_INTERVAL") or "30").strip()
    lines = [
        "# CropSentinel Agent configuration",
        f"CROPSENTINEL_SERVER={server}",
        f"CROPPRO_SERVER={server}",
        f"CROPSENTINEL_ENROLL_TOKEN={token}",
        f"CROPPRO_ENROLL_TOKEN={token}",
        f"CROPSENTINEL_AGENT_KEY={agent_key}",
        f"CROPPRO_AGENT_KEY={agent_key}",
        f"CROPSENTINEL_SCREENSHOT_INTERVAL={screenshot_interval}",
        f"CROPPRO_SCREENSHOT_INTERVAL={screenshot_interval}",
        f"CROPSENTINEL_SYNC_INTERVAL={sync_interval}",
        f"CROPPRO_SYNC_INTERVAL={sync_interval}",
    ]
    if stop_hash:
        lines.extend([
            f"AGENT_STOP_PASSWORD_HASH={stop_hash}",
            f"CROPSENTINEL_STOP_PASSWORD_HASH={stop_hash}",
        ])
    return "\n".join(lines) + "\n"


def _unlock_program_data_targets(*targets: Path) -> None:
    PROGRAM_DATA.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "icacls.exe",
            str(PROGRAM_DATA),
            "/grant:r",
            "*S-1-5-18:(F)",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(F)",
            "*S-1-5-32-544:(OI)(CI)F",
            "/t",
            "/c",
        ],
        check=False,
    )
    for target in (PROGRAM_DATA, *targets):
        if target.exists():
            _run(["attrib.exe", "-R", str(target)], check=False)
            _run(
                [
                    "icacls.exe",
                    str(target),
                    "/grant:r",
                    "*S-1-5-18:F",
                    "*S-1-5-32-544:F",
                ],
                check=False,
            )


def write_config(values: dict[str, str]) -> None:
    _unlock_program_data_targets(CONFIG_PATH)
    content = normalize_config(values)
    temp_path = CONFIG_PATH.with_suffix(".tmp")
    temp_path.write_text(content, encoding="utf-8")
    try:
        os.replace(temp_path, CONFIG_PATH)
    except PermissionError:
        _unlock_program_data_targets(CONFIG_PATH)
        try:
            if CONFIG_PATH.exists():
                CONFIG_PATH.unlink()
        except Exception:
            pass
        os.replace(temp_path, CONFIG_PATH)
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass


def copy_payload_files(destination: Path) -> None:
    bundle_src = resource_path("cropsentinel-agent")
    if not bundle_src.exists():
        raise FileNotFoundError(f"Missing bundled agent directory: {bundle_src}")
    if bundle_src.is_file():
        raise FileNotFoundError(f"Expected bundled agent directory but found file: {bundle_src}")
    shutil.copytree(bundle_src, destination, dirs_exist_ok=True)


def write_payload_manifest(manifest: dict[str, object]) -> None:
    _unlock_program_data_targets(PAYLOAD_MANIFEST_PATH)
    content = json.dumps(manifest, indent=2)
    temp_path = PAYLOAD_MANIFEST_PATH.with_suffix(".tmp")
    temp_path.write_text(content, encoding="utf-8")
    try:
        os.replace(temp_path, PAYLOAD_MANIFEST_PATH)
    except PermissionError:
        _unlock_program_data_targets(PAYLOAD_MANIFEST_PATH)
        try:
            if PAYLOAD_MANIFEST_PATH.exists():
                PAYLOAD_MANIFEST_PATH.unlink()
        except Exception:
            pass
        os.replace(temp_path, PAYLOAD_MANIFEST_PATH)
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass


def stage_payload_cache(manifest: dict[str, object]) -> None:
    _unlock_program_data_targets(PAYLOAD_MANIFEST_PATH, PAYLOAD_CACHE_DIR)
    if PAYLOAD_CACHE_DIR.exists():
        shutil.rmtree(PAYLOAD_CACHE_DIR, ignore_errors=True)
    copy_payload_files(PAYLOAD_CACHE_DIR)
    write_payload_manifest(manifest)


def _service_exists(service_name: str) -> bool:
    return _run_sc(["qc", service_name]).returncode == 0


def _wait_for_service_state(service_name: str, expected: str, timeout_seconds: int = 20) -> bool:
    deadline = time.time() + max(1, timeout_seconds)
    expected = expected.upper()
    while time.time() < deadline:
        result = _run_sc(["query", service_name])
        if result.returncode == 0 and expected in (result.stdout or "").upper():
            return True
        time.sleep(1)
    return False


def _stop_service(service_name: str) -> None:
    if not _service_exists(service_name):
        return
    _run_sc(["stop", service_name])
    _wait_for_service_state(service_name, "STOPPED", timeout_seconds=15)


def _delete_service(service_name: str) -> None:
    if not _service_exists(service_name):
        return
    _stop_service(service_name)
    _run_sc(["delete", service_name])


def _delete_legacy_task(task_name: str) -> None:
    _run(["schtasks.exe", "/End", "/TN", task_name], check=False)
    _run(["schtasks.exe", "/Delete", "/TN", task_name, "/F"], check=False)


def stop_existing_install() -> None:
    """Stop old services, legacy tasks, and processes before overwriting files."""
    for service_name in (AGENT_SERVICE,):
        _stop_service(service_name)
    for task_name in (AGENT_SERVICE,):
        _delete_legacy_task(task_name)
    for proc_name in (
        AGENT_EXE_NAME,
        AGENT_SERVICE_EXE_NAME,
    ):
        _run(["taskkill.exe", "/F", "/IM", proc_name, "/T"], check=False)


def remove_existing_install_dir() -> None:
    if not INSTALL_DIR.exists():
        return
    for _ in range(10):
        try:
            shutil.rmtree(INSTALL_DIR)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(1)
        except OSError:
            time.sleep(1)
    raise PermissionError(f"Could not clear existing install directory: {INSTALL_DIR}")


def _configure_service_recovery(service_name: str) -> None:
    _run_sc([
        "failure",
        service_name,
        "reset=",
        "86400",
        "actions=",
        "restart/5000/restart/5000/restart/5000",
    ])
    _run_sc(["failureflag", service_name, "1"])


def _upsert_service(service_name: str, binary_path: Path, display_name: str, description: str) -> None:
    if not binary_path.exists():
        raise FileNotFoundError(f"Service executable not found: {binary_path}")
    quoted_path = f'"{binary_path}"'
    if _service_exists(service_name):
        result = _run_sc([
            "config",
            service_name,
            "binPath=",
            quoted_path,
            "start=",
            "auto",
            "obj=",
            "LocalSystem",
            "type=",
            "own",
        ])
    else:
        result = _run_sc([
            "create",
            service_name,
            "binPath=",
            quoted_path,
            "start=",
            "auto",
            "obj=",
            "LocalSystem",
            "type=",
            "own",
            "DisplayName=",
            display_name,
        ])
    if result.returncode != 0:
        detail = (result.stdout or result.stderr).strip()
        raise RuntimeError(f"Failed to install service {service_name}: {detail}")

    _run_sc(["description", service_name, description])
    _configure_service_recovery(service_name)


def apply_locked_acl(path: Path) -> None:
    if not path.exists():
        return
    result = _run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(F)",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(F)",
            "*S-1-5-32-544:(OI)(CI)F",
            "/t",
            "/c",
        ],
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout or result.stderr).strip()
        raise RuntimeError(f"Failed to harden ACL for {path}: {detail}")


def harden_windows_paths() -> None:
    for path in (INSTALL_DIR, PROGRAM_DATA):
        apply_locked_acl(path)


def ensure_services() -> None:
    agent_service_exe = INSTALL_DIR / AGENT_SERVICE_EXE_NAME

    _upsert_service(
        AGENT_SERVICE,
        agent_service_exe,
        "CropSentinel Agent",
        "CropSentinel native monitoring agent service.",
    )

    agent_start = _run_sc(["start", AGENT_SERVICE])
    agent_text = ((agent_start.stdout or "") + (agent_start.stderr or "")).lower()
    if agent_start.returncode != 0 and "service has already been started" not in agent_text:
        raise RuntimeError(f"Failed to start agent service: {(agent_start.stdout or agent_start.stderr).strip()}")
    if not _wait_for_service_state(AGENT_SERVICE, "RUNNING", 20):
        raise RuntimeError("Agent service did not reach RUNNING state.")


def install_from_payload(payload: dict[str, str]) -> None:
    manifest = verify_bundled_payload()
    stop_existing_install()
    write_config(payload)
    remove_existing_install_dir()
    copy_payload_files(INSTALL_DIR)
    stage_payload_cache(manifest)
    harden_windows_paths()
    ensure_services()


def uninstall_agent() -> None:
    stop_existing_install()
    for service_name in (AGENT_SERVICE,):
        _delete_service(service_name)
    for task_name in (AGENT_SERVICE,):
        _delete_legacy_task(task_name)
    for path in (INSTALL_DIR, PAYLOAD_CACHE_DIR):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    for file_path in (CONFIG_PATH, PAYLOAD_MANIFEST_PATH):
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass
    try:
        if PROGRAM_DATA.exists() and not any(PROGRAM_DATA.iterdir()):
            PROGRAM_DATA.rmdir()
    except Exception:
        pass


def read_payload(path: str | None) -> dict[str, str]:
    if not path:
        return load_sidecar_config()
    payload_path = Path(path)
    if payload_path.exists():
        try:
            return json.loads(payload_path.read_text(encoding="utf-8"))
        except Exception:
            return load_sidecar_config()
    return load_sidecar_config()


class InstallerUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} {VERSION}")
        self.root.geometry("760x740")
        self.root.minsize(720, 700)
        self.root.configure(bg="#f6f8fb")
        self.root.resizable(True, True)
        self._apply_icon()

        self.values = load_sidecar_config()
        self.server_var = tk.StringVar(value=self.values.get("CROPSENTINEL_SERVER") or self.values.get("CROPPRO_SERVER") or "http://localhost:8000")
        self.token_var = tk.StringVar(value=self.values.get("CROPSENTINEL_ENROLL_TOKEN") or self.values.get("CROPPRO_ENROLL_TOKEN") or "")
        self.consent_var = tk.BooleanVar(value=False)

        self._build()
        self.server_var.trace_add("write", lambda *_: self._sync_buttons())
        self.token_var.trace_add("write", lambda *_: self._sync_buttons())

    def _apply_icon(self) -> None:
        icon_path = resource_path(APP_ICON_NAME)
        if not icon_path.exists():
            return
        try:
            self.root.iconbitmap(default=str(icon_path))
        except Exception:
            pass

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(outer, text="Install CropSentinel Agent", font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            outer,
            text="The installer will copy the agent, write the tenant config, install protected LocalSystem services, and start them automatically.",
            wraplength=590,
        )
        subtitle.pack(anchor="w", pady=(6, 14))

        consent_box = tk.Text(outer, height=8, wrap="word", relief="solid", borderwidth=1)
        consent_box.pack(fill="x")
        consent_text = (
            "Consent notice\n\n"
            "CropSentinel monitors employee activity on this device for security and productivity purposes.\n\n"
            "What will happen after install:\n"
            "- the agent will run in the background as a Windows service\n"
            "- the agent will send activity and security events to your server\n"
            "- an administrator can manage or uninstall it using Windows rights\n\n"
            "You should only continue if you are authorized to install monitoring software on this computer."
        )
        consent_box.insert("1.0", consent_text)
        consent_box.config(state="disabled")

        form = ttk.Frame(outer)
        form.pack(fill="x", pady=(16, 0))

        ttk.Label(form, text="Server URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.server_var).grid(row=1, column=0, sticky="ew", pady=(4, 10))
        ttk.Label(form, text="Enrollment token").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.token_var, show="*").grid(row=3, column=0, sticky="ew", pady=(4, 10))
        form.columnconfigure(0, weight=1)

        self.consent_check = ttk.Checkbutton(
            outer,
            text="I confirm I am authorized to install CropSentinel on this machine.",
            variable=self.consent_var,
            command=self._sync_buttons,
        )
        self.consent_check.pack(anchor="w", pady=(12, 10))

        summary = ttk.Frame(outer)
        summary.pack(fill="x", pady=(0, 12))
        ttk.Label(summary, text="Install location:").grid(row=0, column=0, sticky="w")
        ttk.Label(summary, text=str(INSTALL_DIR)).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(summary, text="Config location:").grid(row=1, column=0, sticky="w")
        ttk.Label(summary, text=str(CONFIG_PATH)).grid(row=1, column=1, sticky="w", padx=(8, 0))

        buttons = ttk.Frame(outer)
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.root.destroy).pack(side="right")
        self.install_btn = ttk.Button(buttons, text="Next", command=self._install_clicked)
        self.install_btn.pack(side="right", padx=(0, 8))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.install_btn.config(state=("normal" if self.consent_var.get() and self.token_var.get().strip() else "disabled"))

    def _install_clicked(self) -> None:
        if not self.consent_var.get():
            messagebox.showwarning(APP_NAME, "You must accept the consent notice before installing.")
            return
        if not self.token_var.get().strip():
            messagebox.showwarning(APP_NAME, "Enrollment token is required.")
            return

        payload = {
            "CROPSENTINEL_SERVER": self.server_var.get().strip(),
            "CROPPRO_SERVER": self.server_var.get().strip(),
            "CROPSENTINEL_ENROLL_TOKEN": self.token_var.get().strip(),
            "CROPPRO_ENROLL_TOKEN": self.token_var.get().strip(),
        }
        extra = self.values.get("CROPSENTINEL_AGENT_KEY") or self.values.get("CROPPRO_AGENT_KEY")
        if extra:
            payload["CROPSENTINEL_AGENT_KEY"] = extra
            payload["CROPPRO_AGENT_KEY"] = extra
        stop_hash = self.values.get("AGENT_STOP_PASSWORD_HASH") or self.values.get("CROPSENTINEL_STOP_PASSWORD_HASH")
        if stop_hash:
            payload["AGENT_STOP_PASSWORD_HASH"] = stop_hash
            payload["CROPSENTINEL_STOP_PASSWORD_HASH"] = stop_hash
        payload["CROPSENTINEL_SCREENSHOT_INTERVAL"] = self.values.get("CROPSENTINEL_SCREENSHOT_INTERVAL") or self.values.get("CROPPRO_SCREENSHOT_INTERVAL") or "60"
        payload["CROPSENTINEL_SYNC_INTERVAL"] = self.values.get("CROPSENTINEL_SYNC_INTERVAL") or self.values.get("CROPPRO_SYNC_INTERVAL") or "30"

        payload_path = Path(tempfile.gettempdir()) / "cropsentinel-installer-payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        if not is_admin():
            elevate(["--install", "--payload", str(payload_path)])
            self.root.destroy()
            return

        self.root.destroy()
        perform_install(payload_path)

    def run(self) -> None:
        self.root.mainloop()


def perform_install(payload_path: Path) -> None:
    try:
        payload = read_payload(str(payload_path))
        install_from_payload(payload)
        show_info("CropSentinel installed successfully.")
    except Exception as exc:
        show_error(f"Installation failed:\n\n{exc}")
        raise
    finally:
        try:
            if payload_path.exists():
                payload_path.unlink()
        except Exception:
            pass


def perform_uninstall() -> None:
    try:
        uninstall_agent()
        show_info("CropSentinel was removed successfully.")
    except Exception as exc:
        show_error(f"Uninstall failed:\n\n{exc}")
        raise


def main() -> None:
    if "--install" in sys.argv:
        payload_file = None
        if "--payload" in sys.argv:
            idx = sys.argv.index("--payload")
            if idx + 1 < len(sys.argv):
                payload_file = sys.argv[idx + 1]
        if not is_admin():
            elevate(sys.argv[1:])
            return
        payload = read_payload(payload_file)
        try:
            install_from_payload(payload)
            show_info("CropSentinel installed successfully.")
        except Exception as exc:
            show_error(f"Installation failed:\n\n{exc}")
            raise
        return

    if "--uninstall" in sys.argv:
        if not is_admin():
            elevate(sys.argv[1:])
            return
        perform_uninstall()
        return

    InstallerUI().run()


if __name__ == "__main__":
    main()
