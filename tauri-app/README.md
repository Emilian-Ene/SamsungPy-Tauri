# Samsung Tauri Migration (Phase 3)

This folder contains a **Tauri shell** for your Samsung control project.

## What is already migrated

- Desktop app shell based on Tauri
- Web UI for core controls:
  - status
  - power on/off/reboot
  - set volume
  - set brightness (signage)
  - set mute
  - set input source
- Rust command layer (`src-tauri/src/main.rs`)
- Python bridge (`py/bridge.py`) that reuses your existing Python control stack
- Saved devices manager (load, apply, save/update, delete) backed by root `saved_devices.json`
- Auto Probe for protocol/port detection in order: `1515`, `8002`, `8001`
- Command Log panel for action history and diagnostics
- MDC CLI controls (manual command + GET/SET)
- Consumer Smart TV key sender (repeat support)
- HDMI macros for Smart TV (`HDMI1`..`HDMI4`)

## Prerequisites

- Node.js 18+
- Rust (stable) + Visual Studio Build Tools on Windows
- Python 3.x
- Existing Python dependencies installed in project root:

```bash
py -m pip install -r ..\requirements.txt
```

## Run in development

From this folder (`tauri-app`):

```bash
npm install
npm run tauri dev
```

## Build Windows EXE with GitHub Actions

- Workflow file: `.github/workflows/build-windows.yml`
- Trigger options:
  - manual: GitHub -> Actions -> **Build Windows EXE** -> Run workflow
  - tag push: `v*` (example: `v0.1.0`)
- Output artifact name: `windows-exe`
- Artifact content: compiled app binary from
  - `src-tauri/target/x86_64-pc-windows-msvc/release/*.exe`

## Notes

- This is a **migration baseline** with core parity for connection workflows.
- Full feature parity with `dashboard.py` tabs/advanced actions is still pending.
- Current bridge path uses a dev-oriented local file path.
- Packaging with embedded Python/runtime sidecar is the next phase.
