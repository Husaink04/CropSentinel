# CropSentinel Native Agent

This project is the native Windows agent implemented on top of the
Native AOT .NET runtime.

Current scope:

- compile as a `net8.0` Native AOT executable
- register with the existing backend using `POST /api/machines/register`
- send recurring heartbeats to `POST /api/activity/heartbeat`
- collect real Windows heartbeat signals for CPU, memory, idle time, and foreground application
- emit foreground application activity to `POST /api/activity/application`
- read recent Chrome, Edge, and Firefox history and emit `POST /api/activity/browser`
- collect low-level keyboard and mouse counts, hash key n-grams locally, and emit `POST /api/activity/input`
- capture scheduled and on-demand screenshots and emit `POST /api/activity/screenshot`
- sample native network activity and emit `POST /api/activity/network`
- watch common Windows user folders and removable roots for file activity, emit `POST /api/activity/file` with full support for user-mode active blocking (DLP enforcement) and local base64-encoded delete backup staging
- ingest heartbeat config updates into a native runtime policy store
- evaluate browser events with local phishing heuristics and backend-assisted phishing checks
- queue phishing alerts and DLP alerts for replay through `POST /api/activity/batch`
- persist failed telemetry into an encrypted SQLite offline queue and drain it back to `/api/activity/batch`
- maintain an authenticated agent websocket connection to `/ws/agent/{machine_id}` and handle screenshot requests
- answer live-view WebRTC offer requests from the backend and stream native screen frames over the existing signalling channel
- accept remote-control WebRTC sessions with native input injection, remote command execution, and file-transfer receive support
- run correctly either as a console worker or as a Windows service host

Not migrated yet:

- remote system-audio streaming parity
- Linux/macOS agent parity

## Local run

Set configuration using `appsettings.json` or environment variables:

- `CropSentinelAgent__ApiBaseUrl`
- `CropSentinelAgent__WebSocketBaseUrl`
- `CropSentinelAgent__AgentApiKey`
- `CropSentinelAgent__EnrollmentToken`
- `CropSentinelAgent__HeartbeatIntervalSeconds`

Build:

```powershell
dotnet publish .\agent\native\CropSentinel.AgentNative\CropSentinel.AgentNative.csproj -c Release
```

The agent persists a generated machine id under `%ProgramData%\CropSentinel\NativeAgent\machine-id.txt`
unless `CropSentinelAgent__MachineId` is explicitly set.
