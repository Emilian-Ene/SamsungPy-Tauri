# Samsung Hybrid Control (Tauri)

Samsung display control app using a Tauri frontend and Python backend, with support for local direct control and Option B remote agent routing.

## Project layout

- `tauri-app/` — frontend app (Vite + Tauri shell)
- `tauri-app/py/bridge.py` — Python command bridge to Samsung control libraries
- `tauri-app/py/web_backend.py` — local backend + Option B broker endpoints
- `tauri-app/py/option_b_agent.py` — polling agent for remote job execution
- `saved_devices.json` — persisted device list
- `requirements.txt` — Python dependencies

## Core logic flow

### 1) Device data model

Each saved device keeps:

- `name`
- `tv_ip`
- `port`
- `id`
- `protocol` (`AUTO`, `SIGNAGE_MDC`, `SMART_TV_WS`)
- `agent_id` (empty = local/direct mode)
- optional metadata (`site`, `city`, `zone`, `area`, `description`)

### 2) Command routing

#### Local/direct mode (`agent_id` empty)

1. UI selects a TV.
2. Frontend sends command to local backend.
3. Backend talks directly to target TV IP/port.

#### Option B remote mode (`agent_id` present)

1. Frontend sends request with `agent_id` + `tv_ip`.
2. Backend queues job by `agent_id`.
3. Matching polling agent (`AGENT_ID`) receives job.
4. Agent executes locally in its LAN and posts result back.
5. Frontend polls job/result and updates UI status.

### 3) Status flow

- Agent statuses refresh automatically and can be refreshed manually.
- TV statuses refresh via heartbeat loop and can also be tested manually.
- If a device has an assigned agent and that agent is offline, remote TV checks are skipped.

### 4) Explore Agents flow

1. Open **Explore Agents** page.
2. See tracked Agent IDs from saved devices with status + timestamp.
3. Click agent row to show TVs assigned to that agent.
4. Click same agent row again to collapse details.
5. Click a TV row in that list to auto-select it and open **Controls** page.

## Current implemented features

- Saved devices manager (load/apply/save/delete)
- Core controls (status, power, volume, brightness, mute, input)
- MDC CLI commands (manual GET/SET)
- Smart TV key sender (repeat)
- HDMI macros (`HDMI1`..`HDMI4`)
- Command Log
- Explore Agents page with agent-to-TV drill-down

## Prerequisites

- Node.js 18+
- Python 3.x
- Rust + Visual Studio Build Tools (only for Tauri desktop run/build)

## Install dependencies

From project root:

```bash
py -m pip install -r requirements.txt
```

From `tauri-app`:

```bash
npm install
```

## Run

### Web UI

```bash
cd tauri-app
npm run dev
```

### Tauri desktop

```bash
cd tauri-app
npm run tauri dev
```

### Backend (required for API/Option B paths)

From project root:

```bash
py tauri-app/py/web_backend.py
```

### Option B agent (required for remote queued jobs)

From project root:

```bash
set CLOUD_BASE_URL=http://127.0.0.1:8765
set AGENT_ID=site-bucharest
set AGENT_SHARED_SECRET=replace-with-strong-random-secret
set LOCAL_BACKEND_URL=http://127.0.0.1:8765
py tauri-app/py/option_b_agent.py
```

## Security envs (when auth is required)

Backend process:

```bash
set REMOTE_AUTH_REQUIRED=true
set CLOUD_API_KEY=replace-with-strong-random-secret
set AGENT_SHARED_SECRET=replace-with-strong-random-secret
```

Frontend (`tauri-app/.env`):

```bash
VITE_CLOUD_API_KEY=replace-with-strong-random-secret
```

## Next tasks

See [TODO.md](TODO.md).
