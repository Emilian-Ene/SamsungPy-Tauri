# Samsung Hybrid Control (Tauri)

This repository is focused on a **Tauri + Python bridge** architecture for Samsung signage/TV control.

## Project layout

- `tauri-app/` — Tauri/web frontend + Rust shell
- `tauri-app/py/bridge.py` — Python command bridge to Samsung control libraries
- `saved_devices.json` — persisted device list shared by the app
- `requirements.txt` — Python dependencies used by the bridge

## Migration status (Phase 3 baseline)

Implemented:

- Desktop app shell based on Tauri
- Web UI for core controls:
  - status
  - power on/off/reboot
  - set volume
  - set brightness (signage)
  - set mute
  - set input source
- Rust command layer (`tauri-app/src-tauri/src/main.rs`)
- Python bridge (`tauri-app/py/bridge.py`) reusing the Python control stack
- Saved devices manager (load, apply, save/update, delete)
- Auto Probe protocol/port detection order: `1515`, `8002`, `8001`
- Command Log panel for diagnostics
- MDC CLI controls (manual command + GET/SET)
- Smart TV key sender (repeat support)
- HDMI macros for Smart TV (`HDMI1`..`HDMI4`)

## Prerequisites

- Node.js 18+
- Rust (stable) + Visual Studio Build Tools on Windows
- Python 3.x

## Python dependencies

Install from project root:

```bash
py -m pip install -r requirements.txt
```

Installed packages:

- `python-samsung-mdc`
- `samsungtvws`

## Run as web app (no Rust required)

```bash
cd tauri-app
npm install
npm run dev
```

Open the local URL shown by Vite (typically `http://localhost:5173`).

## Run as Tauri desktop app

```bash
cd tauri-app
npm install
npm run tauri dev
```

## Build Windows EXE with GitHub Actions

- Build workflow: `.github/workflows/build-windows.yml`
- Release workflow: `.github/workflows/release-windows.yml`
- Trigger flow: push to `main` -> Build -> Release (automatic)

Release checklist:

1. Commit and push latest changes to `main`.
2. Ensure app version is updated consistently.
3. Wait for Build workflow success.
4. Release publishes assets and matching tag (`vX.Y.Z`).

## Notes

- CLI command schema in web mode: `tauri-app/src/cli_catalog.json`
- Regenerate schema from Python metadata:

```bash
cd tauri-app
py py/export_cli_catalog.py
```

---

# Tailscale Flow Runbook

## 1) Real command path

### MDC path (signage)

1. UI (Tauri frontend) triggers action (`status`, `cli_get`, `set_input`, etc.).
2. Frontend calls local backend (`/device_action` or Tauri invoke).
3. Python bridge uses `python-samsung-mdc` to open TCP to `TV_IP:1515`.
4. OS routing sends packets through Tailscale subnet route to Raspberry Pi.
5. Pi forwards to TV on LAN.
6. TV replies back through Pi -> Tailscale -> backend -> UI.

### Smart TV WS path (consumer)

Same flow, but destination ports are usually `8002`/`8001` and backend uses `samsungtvws`.

## 2) Important understanding

- Backend code does **not** explicitly "connect to Tailscale".
- Backend just opens sockets to target IP/port.
- Tailscale + OS routing decide transport path.
- Most intermittent failures are network state (route/ARP/cache), not app logic.

## 3) Per-hop checks (fast)

### Hop A: UI -> backend local health

Run on the machine where app is running:

```bash
curl http://127.0.0.1:8765/health
```

Expected: `{"ok": true, ...}`

If fail: start backend:

```bash
py tauri-app/py/web_backend.py
```

### Hop B: backend host -> target TV reachability

From backend host or Pi:

```bash
ping -c 3 192.168.1.166
nc -vz -w 3 192.168.1.166 1515
```

For WS mode:

```bash
nc -vz -w 3 192.168.1.166 8002
nc -vz -w 3 192.168.1.166 8001
```

### Hop C: Pi routing correctness (critical)

On Pi:

```bash
ip -4 addr
ip route get 192.168.1.166
```

Healthy output should show direct LAN dev (example `dev wlan0`).

### Hop D: protocol sanity

- MDC commands require: `SIGNAGE_MDC` + port `1515`.
- WS commands require: `SMART_TV_WS` + `8002/8001`.
- MDC display id: test both `0` and `1`.

## 4) When it worked yesterday and fails today

Most common causes:

- route cache / ARP state drift on Pi
- ICMP redirect-learned route weirdness
- TV boot/sleep state (MDC not responding yet)
- temporary packet loss on LAN

## 5) Quick recovery without reboot (Pi)

```bash
sudo ip route flush cache
sudo ip neigh flush dev wlan0
sudo ip route replace 192.168.1.0/24 dev wlan0 src $(ip -4 -o addr show wlan0 | awk '{print $4}' | cut -d/ -f1)
ip route get 192.168.1.166
nc -vz -w 3 192.168.1.166 1515
```

## 6) Production hardening checklist

- Use static IP or DHCP reservation for every TV.
- Use static IP or DHCP reservation for Pi.
- Keep Pi and TVs in same stable subnet/VLAN where possible.
- Keep protocol/port pinned in app profiles (`1515` for signage MDC).
- Keep backend timeout tuning.

## 7) Failure signature mapping

- `Request timeout` / `WinError 121` / `response header read timeout`
  - Usually path/routing/latency, not command syntax.
- `NAK` response
  - Device reachable, command rejected by firmware/mode/source.
- `connection refused` / `failed to fetch`
  - Backend down or target port closed.

## 8) One-line diagnostic sequence (Pi)

```bash
ip route get 192.168.1.166 && ping -c 3 192.168.1.166 && nc -vz -w 3 192.168.1.166 1515
```

If this passes but app still fails, focus on protocol/id/command compatibility, not network path.
