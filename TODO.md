# TODO

## Completed

### Option B routing architecture - Core - completed

- Each screen record must store both `tv_ip` and `agent_id`.
- Frontend sends command requests with both values to cloud backend.
- Cloud backend enqueues by `agent_id` bucket and does not call TV IP directly.
- Only the Pi agent whose `AGENT_ID` equals the job `agent_id` can poll and receive that job.
- The matched agent executes locally in its LAN using the job `tv_ip`.

### Option B routing architecture - Backend-compatible remote job mapping - completed

- Frontend remote enqueue no longer uses unsupported `device_action` job kind.
- Action mapping now uses backend-supported kinds: `test`, `tv`, `mdc_execute`.
- Remote `power` is mapped to `tv` command (`on` / `off`).
- Remote CLI GET/SET and setter actions are mapped to `mdc_execute`.

### Option B routing architecture - Explore Agents workflow - completed

- Explore Agents page is available.
- Agent status list supports auto refresh and manual refresh.
- Clicking an agent row opens a TV list scoped to that agent.
- Clicking the same selected agent row again collapses that TV list.
- Clicking a TV row from the agent TV list switches to Controls with that TV selected.

### Option B routing architecture - MDC-only cleanup - completed

- Smart TV WS page and WS protocol option were removed from UI.
- WS logic was removed from frontend, Python bridge/backend, and Rust side checks.
- Dependency cleanup done (`samsungtvws` removed).

### Option B routing architecture - Startup and test flow alignment - completed

- Startup order aligned to web app logic:
  - Load saved devices
  - Load CLI catalog
  - Refresh agents (`/api/remote/agents`)
  - Refresh all device statuses
- Agent gate is strict for remote tests/status:
  - If cached agent status is not `online`, TV is marked offline immediately
  - TV call is sent only when agent is `online`

### Option B routing architecture - Cloud runtime configuration - completed

- Cloud base URL and API key are configured for development and production envs.
- Frontend remote requests use cloud backend when `VITE_CLOUD_BASE_URL` is set.

### Option B routing architecture - Validation - completed

- Remote `test` for `192.168.1.169:1515` via `paragon` succeeded.
- Remote `power OFF` and `power ON` via `paragon` succeeded.
- Remote CLI GET `software_version` succeeded.
- Remote CLI GET `model_number` succeeded.
- Repository changes were committed and pushed to `main`.

### Option B routing architecture - Timestamp Monitor page - completed

- Added a separate `Timestamp Monitor` workflow page/tab.
- Checks all saved TVs and keeps monitor list refreshed every 1 minute.
- Tracks and shows per device:
  - current status
  - `last online` timestamp
  - `offline since` timestamp
  - `last check` timestamp
- Added `Refresh Now` action for manual monitor refresh.

## Planned

- Optional: improve Windows Git Credential Manager stability (push succeeds, but CLI shows .NET exceptions on this machine).
- Add controlled parallel TV status checks (concurrency cap 8) for startup/refresh, with timing logs to compare against sequential mode.(this is from web app logic: In your app, TV checks are batched with a concurrency limit.

Concurrency cap is 8 (BULK_REFRESH_CONCURRENCY = 8).
Used by refreshAllDevices() via runInBatches(...).
Meaning: at most 8 TVs are tested at the same time during startup/“Refresh all”.
If you had more TVs, remaining ones wait for next batch.)
