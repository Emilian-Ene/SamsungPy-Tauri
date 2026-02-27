# Samsung Hybrid Control (Tauri)

This repository is now cleaned and focused on the **Tauri + Python bridge** architecture.

## Project layout

- `tauri-app/` — Tauri/web frontend + Rust shell
- `tauri-app/py/bridge.py` — Python command bridge to Samsung control libraries
- `saved_devices.json` — persisted device list shared by the app
- `requirements.txt` — Python dependencies used by the bridge

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

Then open the local URL shown by Vite (typically `http://localhost:5173` or `http://localhost:5174`).

## Run as Tauri desktop app

Prerequisites:

- Rust/Cargo installed
- Node.js 18+
- Python 3.x

Run:

```bash
cd tauri-app
npm install
npm run tauri dev
```

## Build EXE with GitHub Actions

Release flow checklist:

1. Commit and push your latest changes to `main`.
2. Create and push a version tag (example `v0.1.1`):

```bash
git tag v0.1.1
git push tauri v0.1.1
```

3. Open GitHub -> Actions -> `Release Windows EXE` and wait for success.
4. Download the `.exe` from either:
   - the workflow artifact `windows-exe-release`, or
   - the GitHub Release assets for the pushed tag.

## Notes

- CLI command schema is available in web mode via `tauri-app/src/cli_catalog.json`.
- To regenerate it from Python metadata:

```bash
cd tauri-app
py py/export_cli_catalog.py
```
