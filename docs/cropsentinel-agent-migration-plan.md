# CropSentinel Windows Endpoint Agent Migration Plan
## Python to Native OS Architecture Transition

**Prepared by:** CropSentinel Engineering Architecture Team  
**Date:** June 1, 2026  
**Status:** Under Architectural Review  

---

## 1. Executive Summary & Recommendation

Currently, the CropSentinel endpoint agent is implemented in **Python** (`agent/agent.py` and associated modules). While Python has enabled rapid prototyping and feature velocity during early development cycles, running a Python runtime on production endpoints introduces severe limitations in memory footprint, binary size, security protection, and low-level Windows integration.

### Strategic Recommendation
**Yes, it is absolutely the right decision to shift the Windows endpoint agent from Python to C# (.NET 8+ Native AOT) or Rust.** 

For Windows-focused enterprise environments, we highly recommend **C# (.NET 8+ utilizing Native AOT)** as the primary migration path, supplemented by small **C++ Minifilter Driver hooks** if active kernel-level file blocking is required. 

This transition will:
1. **Reduce memory footprint by 80%** (from ~80MB RAM down to <15MB RAM).
2. **Reduce installer/delivery footprint by 85%** (from an 80MB PyInstaller package down to an 8MB-12MB native binary).
3. **Enhance tamper-proofing & security** (preventing simple unpacking decompilation).
4. **Stabilize Windows Service lifecycle management** and session transitions.

---

## 2. Language Comparison for Windows Endpoint Agents

Before committing to C#, we compared the primary candidate ecosystems against our existing Python agent:

| Vector | Python (Current) | C# (.NET 8 Native AOT) [RECOMMENDED] | Rust | C++ (Win32) |
| :--- | :--- | :--- | :--- | :--- |
| **Executable Size** | 80MB+ (Unpacked PyInstaller) | **~8MB - 15MB** (Standalone executable) | ~3MB - 5MB | **~1MB - 3MB** |
| **Idle Memory (RAM)** | ~60MB - 100MB | **~10MB - 20MB** | **~2MB - 8MB** | ~3MB - 10MB |
| **Windows API Access** | Poor (relies on `ctypes` & pywin32) | **Excellent** (CsWin32 source generator / P-Invoke) | Excellent (Native Win32 crates) | **Native** (First-class SDKs) |
| **Reverse-Engineering Protection** | Extremely Poor (trivial to recover python source) | **Good** (Native compiled machine code) | **Excellent** (Optimized LLVM compiled code) | **Excellent** (Highly optimized assembly) |
| **Development Velocity** | Fast | **Fast** (Excellent IDE tools, massive C# standard library) | Medium (High learning curve, borrow checker overhead) | Slow (No default memory safety, complex pointer tracking) |
| **Windows Service Stability** | Poor (prone to session-switch hangs) | **Excellent** (Native BackgroundService API) | Excellent (Rust service library integration) | **Excellent** (Native SCM interfaces) |

---

## 3. Why C# (.NET 8 Native AOT) is the Best Fit

1. **Native AOT (Ahead-of-Time Compilation):**  
   Traditionally, .NET required installing a heavy .NET Runtime on the target machine. Starting with .NET 8, C# natively supports **Native AOT**. This compiles C# code directly into self-contained Win32 machine code, omitting the JIT compiler and runtime installer dependencies. The resulting binary is a single standalone `.exe` under 15MB.
2. **CsWin32 Source Generator:**  
   Microsoft's official CsWin32 tool auto-generates highly-optimized P/Invoke bindings for any Win32 or COM API (e.g. session changes, CPU stats, WMI queries) directly at compile-time with full type-safety.
3. **Security / Memory Safety:**  
   Unlike C++, C# is a garbage-collected, memory-safe language. This is crucial for an agent running as `NT AUTHORITY\SYSTEM`—a single memory leak or buffer overflow in C++ could blue-screen the employee's machine, causing severe business disruption.
4. **Developer Velocity:**  
   C# allows us to reuse our structured OOP design patterns, asynchronous tasks, and JSON serialization models seamlessly with rapid developer onboarding.

---

## 4. Component Mapping: Python to .NET 8

To convert the agent, we will map our existing Python subsystem modules into native C# classes:

```mermaid
classDiagram
    class CropSentinelAgent {
        +String MachineId
        +String ServerUrl
        +Start()
        +Stop()
    }
    class TelemetryQueue {
        +Enqueue(Event)
        +Flush()
    }
    class DlpEngine {
        +EvaluateFile(FilePath)
        +ScanRegex(Content)
    }
    class WindowsServiceHost {
        +OnStart()
        +OnStop()
    }
    CropSentinelAgent --> TelemetryQueue
    CropSentinelAgent --> DlpEngine
    WindowsServiceHost --> CropSentinelAgent
```

| Current Python Module | C# (.NET 8) Equivalent Component | Implementation Strategy |
| :--- | :--- | :--- |
| **`agent/agent.py`** | `CropSentinel.Agent.Core` | Core controller class, orchestrating heartbeats, configuration loading, and subsystem lifecycles. |
| **`agent/offline_queue.py`** | `SQLite-net` or custom Memory Buffer | High-speed local queuing. Can utilize a lightweight SQLite local DB or file-backed system with `System.IO` pipelines. |
| **`agent/file_tracker.py`** | `System.IO.FileSystemWatcher` | Native Windows folder notification system. If active blocking is required, hooks into a C++ Kernel Minifilter Driver. |
| **`agent/network_tracker.py`** | `System.Net.NetworkInformation` | Reads socket details from IP Helper Win32 APIs (`GetExtendedTcpTable`). |
| **`agent/input_tracker.py`** | Windows Low-Level Hook APIs | Implements Win32 Low-Level Keyboard hook (`WH_KEYBOARD_LL`) and Mouse hook to compile telemetry counts. |
| **`agent/dlp_engine.py`** | `System.Text.RegularExpressions` | Evaluates multi-threaded DLP policies utilizing highly optimized JIT-compiled Regex engines. |
| **`agent/webrtc_agent.py`** | `SIPSorcery` or C# WebRTC Library | Handles WebRTC interactive command logic and screen capture streaming. |
| **`agent/windows_agent_service.py`** | `Microsoft.Extensions.Hosting.WindowsServices` | A standard .NET BackgroundService that hooks into the Service Control Manager natively. |

---

## 5. Phase-by-Phase Migration Plan

We propose a **4-Phase execution path** to securely roll out the C# Native agent without disrupting active backend services.

### Phase 1: Architectural Foundation & Ingestion Contract Alignment (Weeks 1-2)
* Setup the .NET 8 SDK environment and configure `<PublishAot>true</PublishAot>` inside the `.csproj` file.
* Build the core HTTP/WebSocket transport service using `.NET HttpClient` and `ClientWebSocket`.
* Align JSON data models with the backend's `models.py` schema (e.g. `MachineRegisterRequest` and `ActivityEnvelopeRequest`).
* **Milestone:** The C# agent successfully compiles as Native AOT under 10MB and registers to the backend with an active heartbeat.

### Phase 2: Telemetry & Monitoring Subsystem Implementation (Weeks 3-5)
* Implement low-level Win32 tracking services:
  * Foreground window tracking via `GetForegroundWindow` and `GetWindowText`.
  * Browser history capture using active hooks or local browser database readers.
  * Idle state validation using `GetLastInputInfo`.
  * Keypress/mouse click count aggregation via safe standard hook loops.
* **Milestone:** The agent streams continuous application, browser, and input timeline packets to the backend.

### Phase 3: DLP & Phishing Policy Porting (Weeks 6-8)
* Port the Python regex scanning, content fingerprinting, and threat score evaluation models to C#.
* Integrate the local warning overlay (Win32 window dialogs or styled WPF overlays) to intercept and warn users of phishing or DLP violations.
* Secure local caching and offline database sync mechanics.
* **Milestone:** Full local DLP scoring and interactive block overlays active on Windows client endpoints.

### Phase 4: Installer Packaging & QA Stabilization (Weeks 9-10)
* Package the standalone `.exe` using the WiX Toolset to compile a highly compressed enterprise MSI installer.
* Perform validation loops on target operating systems (Windows 10, Windows 11, Windows Server) and verify active session switches (Fast User Switching).
* Conduct memory-leak checks under long-running stress tests.
* **Milestone:** Stable MSI package ready for platform distribution via GPO or SCCM.
