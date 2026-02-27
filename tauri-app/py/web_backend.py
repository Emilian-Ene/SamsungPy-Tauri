import asyncio
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from bridge import main_async

HOST = "127.0.0.1"
PORT = 8765


def _probe_tcp(ip: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def auto_probe(ip: str) -> dict:
    ip = str(ip or "").strip()
    if not ip:
        return {"ok": False, "error": "IP is required"}

    candidates = [
        (1515, "SIGNAGE_MDC"),
        (8002, "SMART_TV_WS"),
        (8001, "SMART_TV_WS"),
    ]

    for port, protocol in candidates:
        if _probe_tcp(ip, port):
            return {"ok": True, "ip": ip, "port": port, "protocol": protocol}

    return {
        "ok": False,
        "ip": ip,
        "error": "No known ports open (1515, 8002, 8001)",
    }


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send_json(200, {"ok": True})

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True, "service": "samsung-web-backend"})
            return

        parsed = urlparse(self.path)
        if parsed.path == "/auto_probe":
            query = parse_qs(parsed.query)
            ip = (query.get("ip") or [""])[0]
            result = auto_probe(ip)
            self._send_json(200, result)
            return

        self._send_json(404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        if self.path != "/device_action":
            self._send_json(404, {"ok": False, "error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            payload = json.loads(body)
            action = str(payload.get("action", "")).strip()
            action_payload = payload.get("payload", {})

            if not action:
                self._send_json(400, {"ok": False, "error": "Missing action"})
                return
            if not isinstance(action_payload, dict):
                self._send_json(400, {"ok": False, "error": "payload must be an object"})
                return

            result = asyncio.run(main_async(action, action_payload))
            self._send_json(200, result)
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Samsung web backend listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
