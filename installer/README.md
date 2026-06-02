# CropSentinel Agent Installers

This folder contains the Windows packaging path for the endpoint agent.

Windows outputs are copied into `backend/dist/installers/` so the platform portal can serve tenant-specific download bundles.

## Windows installer

The Windows installer is a single bootstrapper EXE built from `bootstrapper.py`. It:

- shows a consent screen before installation continues
- copies the native payload into `C:\Program Files\CropSentinel Agent\`
- writes `C:\ProgramData\CropSentinel\config.env`
- writes `C:\ProgramData\CropSentinel\payload-manifest.json`
- stages a restore cache under `C:\ProgramData\CropSentinel\payload-cache\`
- installs `CropSentinelAgent` as a `LocalSystem` Windows service
- locks the payload and config paths so only `SYSTEM` or Administrators can modify them
- configures service recovery and starts the native session-supervisor service immediately
- verifies the bundled payload manifest before install

The installed payload currently includes:

- `cropsentinel-agent-native.exe`
- `cropsentinel-agent-service.exe`
- runtime support files such as `appsettings.json` and `e_sqlite3.dll`

The portal-prepared ZIP bundle ships the EXE next to a tenant-specific `config.env`, so the wizard can run with prefilled values and no manual file editing. If no sidecar config is present, the wizard shows simple fields for server URL and enrollment token.

## Build prerequisites

1. .NET 8 SDK
2. Visual Studio 2022 Build Tools with `Desktop development with C++` for Native AOT linking
3. Python 3.11 with PyInstaller for the Windows bootstrapper build

## Building

Windows:

```powershell
cd installer
.\build.ps1
```

Expected Windows outputs:

- `installer/dist/setup/cropsentinel-agent-1.3.0-setup.exe`
- `installer/dist/msi/cropsentinel-agent-1.3.0.msi`
- `backend/dist/installers/cropsentinel-agent-1.3.0-setup.exe`
- `backend/dist/installers/cropsentinel-agent-1.3.0.msi`
- `backend/dist/installers/cropsentinel-agent-1.3.0-windows.zip`

## GitHub Actions workflow

`.github/workflows/windows-agent-msi.yml` builds the Windows installer set on every push to `main`. It:

- checks out the latest code on `windows-latest`
- installs Python, .NET 8, PyInstaller, and WiX Toolset
- runs `installer/build-native-aot.ps1` to generate the native preview payload
- runs `installer/build.ps1` to generate the setup EXE
- runs `installer/build-msi.ps1` to wrap that EXE into an MSI
- signs the MSI with a PFX from GitHub Secrets when signing secrets are configured
- uploads the MSI, the full portal Windows installer set, and the raw native preview payload
- deploys the generated portal installer set onto the Kali self-hosted portal host

Expected GitHub Secrets:

- `WINDOWS_CODESIGN_CERT_BASE64`
- `WINDOWS_CODESIGN_CERT_PASSWORD`

## Smoke testing

Before shipping, verify the installer on a clean Windows 10 or 11 VM with admin rights:

1. Copy the portal bundle ZIP to the VM and extract it.
2. Keep `config.env` next to the EXE.
3. Run the EXE and confirm the wizard shows the consent and connection pages.
4. Check:
   - `C:\Program Files\CropSentinel Agent\cropsentinel-agent-native.exe` exists
   - `C:\Program Files\CropSentinel Agent\cropsentinel-agent-service.exe` exists
   - `C:\ProgramData\CropSentinel\config.env` exists and contains the tenant values
   - `C:\ProgramData\CropSentinel\payload-manifest.json` exists
   - `C:\ProgramData\CropSentinel\payload-cache\` exists
   - `sc.exe query CropSentinelAgent` shows `RUNNING`
   - `icacls "C:\Program Files\CropSentinel Agent"` shows only `SYSTEM` and `Administrators` with modify rights
   - the backend receives a registration from this machine under the dev tenant

## Known limitations

- the Windows path is not fully code-signed unless signing secrets are configured
- locked-screen capture returns black
- local tamper hardening is hash-based integrity and self-heal, not kernel-level protection
- Linux packaging is intentionally removed in this Windows-only native cutover

## File layout

```text
installer/
+- bootstrapper.py
+- build-msi.ps1
+- build-native-aot.ps1
+- build.ps1
+- config.env.example
+- README.md
```
