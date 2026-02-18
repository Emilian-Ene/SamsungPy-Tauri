# Samsung Hybrid Screen Control (Async)

## Setup

1. Open this folder in VS Code.
2. (Optional) Create and activate a virtual environment.
3. Install dependencies:

```bash
py -m pip install -r requirements.txt
```

This installs both control stacks:

- `python-samsung-mdc` for Samsung Signage displays (QMRE/QMR/QBR) via MDC (`1515`)
- `samsungtvws` for Samsung consumer Smart TVs via WebSocket (`8001/8002`)

## CLI script

Edit `IP_ADDRESS` in `screen_control.py` or pass it from CLI.

Run default flow (status + screenshot):

```bash
py screen_control.py
```

Examples:

```bash
py screen_control.py --ip 192.168.1.50 --id 0
py screen_control.py --ip 192.168.1.50 --brightness 80
py screen_control.py --ip 192.168.1.50 --reboot
py screen_control.py --ip 192.168.1.50 --no-screenshot
```

## Desktop dashboard (CustomTkinter)

Run directly:

```bash
py launch_dashboard.py
```

Use the **Protocol** selector in the Connection card:

- `AUTO`: uses `SIGNAGE_MDC` when port is `1515`, otherwise `SMART_TV_WS`
- `SIGNAGE_MDC`: force MDC mode (professional signage)
- `SMART_TV_WS`: force Smart TV WebSocket mode (consumer TVs)

Use **Auto Probe** to detect the device type by checking control ports in order: `1515`, `8002`, `8001`. The app then auto-fills `Port` and `Protocol`.
The sidebar **⚡ Connect** action runs this probe automatically, then checks status.
When the IP already exists in saved devices, detected `Port` and `Protocol` are saved automatically.

Notes:

- CLI Commands tab is MDC-only.
- Some actions are protocol-specific. Smart TV mode supports status reachability, power/home/mute keys, while deep hardware controls (brightness, MDC screenshot, direct input source, serial) remain signage-focused.

Consumer Smart TV quick CLI:

- In the CLI tab, use **CONSUMER SMART TV KEYS** to send WebSocket keys (`KEY_HOME`, `KEY_POWER`, `KEY_MUTE`, `KEY_VOLUP`, `KEY_VOLDOWN`, etc.).
- This section works only when protocol resolves to `SMART_TV_WS`.
- One-click HDMI macros are available (`HDMI1`..`HDMI4`) and send `KEY_SOURCE` navigation sequences.

## Build EXE (Windows, Nuitka)

Install build dependencies:

```bash
py -m pip install -U nuitka zstandard ordered-set
```

Build single-file EXE:

```bash
py -m nuitka --onefile --standalone --windows-console-mode=disable --output-filename=SamsungMDCDashboard.exe launch_dashboard.py
```

Output EXE is created in the Nuitka output folder shown in terminal.

## Build Installer (optional)

If you want a setup wizard (`.exe` installer), create the EXE first with Nuitka, then package it with your installer tool of choice (for example Inno Setup).

## Tizen URL Launcher (NowSignage) via Python on laptop

If the URL is configured but nothing appears on screen, use this exact order from MDC:

1. Set launcher mode to URL Launcher.
2. Set launcher URL.
3. Force input source to URL Launcher.
4. Wait 2-5 seconds and read back source/status.

Example async sequence:

```python
await mdc.launcher_play_via(display_id, ("URL_LAUNCHER",))
await mdc.launcher_url_address(display_id, ("https://cdn.nowsignage.com/tizen/",))
await mdc.input_source(display_id, ("URL_LAUNCHER",))
print(await mdc.input_source(display_id))
```

If still blank:

- Try `WEB_BROWSER` as source on some firmware:

```python
await mdc.input_source(display_id, ("WEB_BROWSER",))
```

- Test with `https://example.com` to confirm browser/network path.
- Verify panel date/time is correct (TLS/HTTPS can fail silently when time is wrong).
- Confirm the panel is Samsung Signage/LFD in MDC mode (`1515`), not consumer TV WS mode (`8001/8002`).
