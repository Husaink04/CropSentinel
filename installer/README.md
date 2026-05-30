# CropSentinel Agent Installers

> Monitor. Detect. Protect.

This folder now holds both installer paths:

- Windows EXE installer bundles built with `build.ps1`
- Windows MSI wrappers built with `build-msi.ps1`
- Linux service bundles built with `build-linux-agent.sh`

Both outputs are copied into `backend/dist/installers/` so the platform portal
can serve tenant-specific download bundles.

## GitLab Runner WiX v7 setup

WiX Toolset v7 does not use `WIX_ACCEPT_OSMF=1` for the build path used in this
repo. It accepts either:

- a CLI switch such as `-acceptEula wix7`
- or a persisted file at `%USERPROFILE%\.wix\wix7-osmf-eula.txt`

For GitLab Runner on Windows, that acceptance must exist for the same identity
that executes the job. If the service runs as `LocalSystem`, the persisted file
lands under:

- `C:\Windows\System32\config\systemprofile\.wix\wix7-osmf-eula.txt`

Long-term provisioning for the runner host:

```powershell
cd installer
powershell -ExecutionPolicy Bypass -File .\provision-gitlab-runner-wix.ps1
```

That script detects the `gitlab-runner` service account and:

- accepts the WiX EULA for the current account when the runner uses that account
- or provisions the acceptance under `LocalSystem` through a one-shot scheduled task

The GitLab CI job also runs `ensure-wix-license.ps1` before each build. That
makes fresh or rebuilt Windows runners self-heal if the persisted acceptance
file is missing.

## Windows installer

A single `.exe` installer wizard that:

- Shows a consent screen before installation continues
- Copies the protected agent payload into
  `C:\Program Files\CropSentinel Agent\`
- Caches a signed-by-hash payload copy in `C:\ProgramData\CropSentinel\payload-cache\`
- Writes `C:\ProgramData\CropSentinel\config.env`
- Installs `CropSentinelAgent` and `CropSentinelWatchdog` as `LocalSystem` Windows services
- Locks the payload/config paths so only `SYSTEM` or Administrators can modify them
- Configures service recovery actions and starts both services immediately
- Verifies the bundled payload manifest before install and lets the watchdog
  restore missing/changed files from the cached payload
- Uninstalls cleanly without requiring the user to edit config files

The portal-prepared ZIP bundle ships the EXE next to a tenant-specific
`config.env`, so the wizard can run with prefilled values and no manual file
editing. If no sidecar config is present, the wizard shows simple fields for
server URL and enrollment token.

## Linux installer

The Linux pipeline builds `cropsentinel-agent-<version>-linux.tar.gz`, which
contains:

- `install-linux-agent.sh`
- a packaged copy of the Python agent source
- `cropsentinel-agent.service`
- `cropsentinel-watchdog.service`
- `config.env.example`

The Linux installer:

- copies the agent into `/opt/cropsentinel-agent/app`
- creates a virtual environment in `/opt/cropsentinel-agent/.venv`
- writes `/etc/cropsentinel/config.env`
- creates system-level `systemd` services for the agent and watchdog
- starts both immediately

## Build prerequisites

1. Python 3.11 with the agent's runtime dependencies installed
2. PyInstaller for the Windows build
3. A Linux environment with `bash`, `tar`, and `python3` for the Linux bundle build

## Building

Windows:

```powershell
cd installer
.\build.ps1
```

Kali / Linux for Windows EXE output:

```bash
cd installer
chmod +x build-windows-agent-kali.sh
./build-windows-agent-kali.sh
```

Linux:

```bash
cd installer
chmod +x build-linux-agent.sh
./build-linux-agent.sh
```

Output:

- `installer\dist\setup\cropsentinel-agent-1.3.0-setup.exe`
- `installer\dist\msi\cropsentinel-agent-1.3.0.msi`
- `backend\dist\installers\cropsentinel-agent-1.3.0-setup.exe`
- `backend\dist\installers\cropsentinel-agent-1.3.0.msi`
- `backend\dist\installers\cropsentinel-agent-1.3.0-windows.zip`
- `backend/dist/installers/cropsentinel-agent-1.3.0-linux.tar.gz`

The Kali helper updates the Windows portal artifacts in place, so
`POST /api/tenants/{tenant_id}/download-agent?platform=windows` will start
serving the fresh build as soon as the script finishes.

## GitHub Actions workflow

`.github/workflows/windows-agent-msi.yml` builds a Windows MSI on every push to
`main`. It:

- checks out the latest code on `windows-latest`
- installs Python, PyInstaller, and WiX Toolset
- runs `installer\build.ps1` to generate the current EXE installer
- runs `installer\build-msi.ps1` to wrap that EXE into an MSI
- signs the MSI with a PFX from GitHub Secrets
- uploads both the MSI and the full portal Windows installer set as workflow artifacts
- optionally publishes the full `backend\dist\installers\` Windows artifact set to S3 or SCP
- for Linux-hosted portals, use `scp` and point the destination to the server's `backend/dist/installers/`

Expected GitHub Secrets:

- `WINDOWS_CODESIGN_CERT_BASE64`
- `WINDOWS_CODESIGN_CERT_PASSWORD`
- `WINDOWS_AGENT_DEPLOY_UPLOAD_URL` for `http-put`
- `WINDOWS_AGENT_DEPLOY_SSH_KEY` for `scp`
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` for `s3`

Expected GitHub Variables:

- `WINDOWS_AGENT_DEPLOY_METHOD` as `s3`, `scp`, or `http-put`
- `WINDOWS_AGENT_DEPLOY_DESTINATION`
- `WINDOWS_AGENT_DEPLOY_HOST`
- `WINDOWS_AGENT_DEPLOY_PORT`
- `WINDOWS_AGENT_DEPLOY_USERNAME`

For a Linux portal server, set:

- `WINDOWS_AGENT_DEPLOY_METHOD=scp`
- `WINDOWS_AGENT_DEPLOY_HOST=<server-ip-or-hostname>`
- `WINDOWS_AGENT_DEPLOY_PORT=22`
- `WINDOWS_AGENT_DEPLOY_USERNAME=<ssh-user>`
- `WINDOWS_AGENT_DEPLOY_DESTINATION=/path/to/CropSentinel/backend/dist/installers/`

The workflow runner pulls from GitHub. The Linux server does not need Git access;
it only needs SSH write access to the target installers directory.

## Smoke-testing the installer bundle

Before shipping, verify the installer on a clean Windows 10/11 VM with admin
rights:

1. Copy the portal bundle ZIP to the VM and extract it.
2. Keep `config.env` next to the EXE.
3. Run the EXE and confirm the wizard shows the consent and connection pages.
4. Check:
   - `C:\Program Files\CropSentinel Agent\cropsentinel-agent.exe` exists
   - `C:\Program Files\CropSentinel Agent\cropsentinel-agent-service.exe` exists
   - `C:\ProgramData\CropSentinel\config.env` exists and contains the tenant values
   - `sc.exe query CropSentinelAgent` shows `RUNNING`
   - `sc.exe query CropSentinelWatchdog` shows `RUNNING`
   - `icacls "C:\Program Files\CropSentinel Agent"` shows only `SYSTEM` and `Administrators` with modify rights
   - The backend receives a registration from this machine under the dev tenant

## Publishing a new build

After the smoke test passes, the portal can serve:

- the newest `cropsentinel-agent-*.exe` for Windows
- the newest `cropsentinel-agent-*-linux.tar.gz` for Linux

Both are read from `backend\dist\installers\`.

## Known limitations

- Not code-signed. SmartScreen will warn until an Authenticode cert is used.
- Locked-screen capture returns black.
- PyInstaller may need hidden imports added in `agent.spec` on first pass.
- Local tamper hardening is hash-based integrity and self-heal, not kernel-level protection.

## File layout

```text
installer/
├─ agent.spec
├─ bootstrapper.py
├─ build-linux-agent.sh
├─ build.ps1
├─ config.env.example
├─ linux/
│  ├─ cropsentinel-agent.service
│  ├─ cropsentinel-watchdog.service
│  └─ install-linux-agent.sh
└─ README.md
```
