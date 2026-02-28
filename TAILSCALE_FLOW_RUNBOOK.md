# SamsungPy Tailscale Flow Runbook

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
- So most intermittent failures are network state (route/ARP/cache), not app logic.

## 3) Per-hop checks (fast)

## Hop A: UI -> backend local health

Run on the machine where app is running:

```bash
curl http://127.0.0.1:8765/health
```

Expected: `{"ok": true, ...}`

If fail: start backend (`py tauri-app/py/web_backend.py`).

## Hop B: backend host -> target TV reachability

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

## Hop C: Pi routing correctness (critical)

On Pi:

```bash
ip -4 addr
ip route get 192.168.1.166
```

Healthy output should show direct LAN dev (example `dev wlan0`) and ideally no unstable redirect behavior.

## Hop D: protocol sanity

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
- Keep backend timeout tuning (already increased in this project).

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
