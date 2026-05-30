# backend/dist/installers/

This folder stores prebuilt CropSentinel Agent installers so the platform
portal's **Download Agent Bundle** endpoint
(`POST /api/tenants/{id}/download-agent`) can serve them to admins.

## What to drop here

Drop the output from `installer\build.ps1` on a Windows dev machine:

- `cropsentinel-agent-<version>-setup.exe`
- `cropsentinel-agent-<version>-windows.zip`

The download endpoint picks the newest `.exe` by modification time, so copying
in a new build is enough. The ZIP is useful for manual distribution and for
confirming the portal-prepared tenant bundle in isolation.

## How to build a new installer

```powershell
cd installer
.\build.ps1
```

The build script now copies the EXE and ZIP into this folder automatically.

## Git policy

- `.gitkeep` and this `README.md` are committed so the folder survives.
- `*.exe` and `*.zip` files are git-ignored because they are rebuilt per
  release.

## If the folder is empty

The download endpoint returns HTTP 503 with a helpful error message telling the
admin to build and drop an EXE here. This is expected on a fresh clone before
the first build.
