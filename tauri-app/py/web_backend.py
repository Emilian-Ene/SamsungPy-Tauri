import asyncio
import json
import os
import socket
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from uuid import uuid4
from urllib.parse import parse_qs, urlparse

from bridge import main_async

HOST = "127.0.0.1"
PORT = 8765

REMOTE_AUTH_REQUIRED = os.getenv("REMOTE_AUTH_REQUIRED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CLOUD_API_KEY = os.getenv("CLOUD_API_KEY", "").strip()
AGENT_SHARED_SECRET = os.getenv("AGENT_SHARED_SECRET", "").strip()

_remote_lock = Lock()
_remote_jobs: dict[str, dict] = {}
_remote_queue_by_agent: dict[str, list[str]] = {}
_agent_state: dict[str, dict] = {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("JSON payload must be an object")
        return payload

    def _assert_cloud_api_key(self) -> tuple[bool, int, str]:
        provided = self.headers.get("x-api-key")
        if REMOTE_AUTH_REQUIRED and not CLOUD_API_KEY:
            return (
                False,
                503,
                "Remote API auth is required but CLOUD_API_KEY is not configured.",
            )
        if CLOUD_API_KEY and provided != CLOUD_API_KEY:
            return (False, 401, "Invalid API key.")
        return (True, 200, "ok")

    def _assert_agent_token(self) -> tuple[bool, int, str]:
        provided = self.headers.get("x-agent-token")
        if REMOTE_AUTH_REQUIRED and not AGENT_SHARED_SECRET:
            return (
                False,
                503,
                "Remote agent auth is required but AGENT_SHARED_SECRET is not configured.",
            )
        if AGENT_SHARED_SECRET and provided != AGENT_SHARED_SECRET:
            return (False, 401, "Invalid agent token.")
        return (True, 200, "ok")

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-api-key, x-agent-token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send_json(200, {"ok": True})

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._send_json(200, {"ok": True, "service": "samsung-web-backend"})
            return

        if parsed.path == "/auto_probe":
            query = parse_qs(parsed.query)
            ip = (query.get("ip") or [""])[0]
            result = auto_probe(ip)
            self._send_json(200, result)
            return

        if parsed.path == "/api/remote/agents":
            ok, status, detail = self._assert_cloud_api_key()
            if not ok:
                self._send_json(status, {"ok": False, "error": detail})
                return

            agents = []
            with _remote_lock:
                for agent_id, info in sorted(_agent_state.items(), key=lambda item: item[0]):
                    queue_depth = len(_remote_queue_by_agent.get(agent_id, []))
                    agents.append(
                        {
                            "agent_id": agent_id,
                            "last_seen": info.get("last_seen"),
                            "version": info.get("version"),
                            "hostname": info.get("hostname"),
                            "local_backend_url": info.get("local_backend_url"),
                            "queue_depth": queue_depth,
                        }
                    )

            self._send_json(200, {"ok": True, "agents": agents})
            return

        if parsed.path.startswith("/api/remote/jobs/"):
            ok, status, detail = self._assert_cloud_api_key()
            if not ok:
                self._send_json(status, {"ok": False, "error": detail})
                return

            job_id = parsed.path.rsplit("/", 1)[-1].strip()
            if not job_id:
                self._send_json(400, {"ok": False, "error": "Invalid job_id."})
                return

            with _remote_lock:
                job = _remote_jobs.get(job_id)

            if job is None:
                self._send_json(404, {"ok": False, "error": "Job not found."})
                return

            self._send_json(200, {"ok": True, **job})
            return

        self._send_json(404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/remote/jobs":
            ok, status, detail = self._assert_cloud_api_key()
            if not ok:
                self._send_json(status, {"ok": False, "error": detail})
                return

            try:
                payload = self._read_json()
                agent_id = str(payload.get("agent_id", "")).strip()
                kind = str(payload.get("kind", "")).strip().lower()
                job_payload = payload.get("payload")
                if not agent_id:
                    self._send_json(400, {"ok": False, "error": "agent_id is required."})
                    return
                if not kind:
                    self._send_json(400, {"ok": False, "error": "kind is required."})
                    return
                if not isinstance(job_payload, dict):
                    self._send_json(400, {"ok": False, "error": "payload must be an object."})
                    return

                job_id = str(uuid4())
                created_at = _utcnow_iso()
                job = {
                    "job_id": job_id,
                    "agent_id": agent_id,
                    "kind": kind,
                    "payload": job_payload,
                    "status": "queued",
                    "created_at": created_at,
                    "dispatched_at": None,
                    "finished_at": None,
                    "result": None,
                    "error": None,
                }

                with _remote_lock:
                    _remote_jobs[job_id] = job
                    _remote_queue_by_agent.setdefault(agent_id, []).append(job_id)

                self._send_json(
                    200,
                    {
                        "ok": True,
                        "status": "queued",
                        "job_id": job_id,
                        "agent_id": agent_id,
                        "kind": kind,
                        "created_at": created_at,
                    },
                )
                return
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return

        if parsed.path.startswith("/api/agent/") and parsed.path.endswith("/heartbeat"):
            ok, status, detail = self._assert_agent_token()
            if not ok:
                self._send_json(status, {"ok": False, "error": detail})
                return

            try:
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 4 or parts[0] != "api" or parts[1] != "agent" or parts[3] != "heartbeat":
                    self._send_json(404, {"ok": False, "error": "Not found"})
                    return
                agent_id = parts[2].strip()
                if not agent_id:
                    self._send_json(400, {"ok": False, "error": "Invalid agent_id."})
                    return

                payload = self._read_json()
                with _remote_lock:
                    _agent_state[agent_id] = {
                        "last_seen": _utcnow_iso(),
                        "version": payload.get("version"),
                        "hostname": payload.get("hostname"),
                        "local_backend_url": payload.get("local_backend_url"),
                    }

                self._send_json(200, {"ok": True, "status": "ok", "agent_id": agent_id})
                return
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return

        if parsed.path.startswith("/api/agent/") and parsed.path.endswith("/poll"):
            ok, status, detail = self._assert_agent_token()
            if not ok:
                self._send_json(status, {"ok": False, "error": detail})
                return

            try:
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 4 or parts[0] != "api" or parts[1] != "agent" or parts[3] != "poll":
                    self._send_json(404, {"ok": False, "error": "Not found"})
                    return
                agent_id = parts[2].strip()
                if not agent_id:
                    self._send_json(400, {"ok": False, "error": "Invalid agent_id."})
                    return

                payload = self._read_json()
                max_jobs = int(payload.get("max_jobs", 5))
                if max_jobs < 1:
                    max_jobs = 1
                if max_jobs > 50:
                    max_jobs = 50

                jobs = []
                with _remote_lock:
                    queue = _remote_queue_by_agent.get(agent_id, [])
                    take = min(max_jobs, len(queue))
                    job_ids = queue[:take]
                    del queue[:take]

                    if not queue and agent_id in _remote_queue_by_agent:
                        _remote_queue_by_agent.pop(agent_id, None)

                    for job_id in job_ids:
                        job = _remote_jobs.get(job_id)
                        if job is None or job.get("status") != "queued":
                            continue
                        job["status"] = "dispatched"
                        job["dispatched_at"] = _utcnow_iso()
                        jobs.append(job)

                    _agent_state[agent_id] = {
                        **_agent_state.get(agent_id, {}),
                        "last_seen": _utcnow_iso(),
                    }

                self._send_json(200, {"ok": True, "agent_id": agent_id, "jobs": jobs})
                return
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return

        if parsed.path.startswith("/api/agent/") and "/jobs/" in parsed.path and parsed.path.endswith("/result"):
            ok, status, detail = self._assert_agent_token()
            if not ok:
                self._send_json(status, {"ok": False, "error": detail})
                return

            try:
                parts = parsed.path.strip("/").split("/")
                if (
                    len(parts) != 6
                    or parts[0] != "api"
                    or parts[1] != "agent"
                    or parts[3] != "jobs"
                    or parts[5] != "result"
                ):
                    self._send_json(404, {"ok": False, "error": "Not found"})
                    return

                agent_id = parts[2].strip()
                job_id = parts[4].strip()
                if not agent_id:
                    self._send_json(400, {"ok": False, "error": "Invalid agent_id."})
                    return
                if not job_id:
                    self._send_json(400, {"ok": False, "error": "Invalid job_id."})
                    return

                payload = self._read_json()
                status_text = str(payload.get("status", "")).strip().lower()
                if status_text not in {"success", "error"}:
                    self._send_json(400, {"ok": False, "error": "status must be success or error."})
                    return

                with _remote_lock:
                    job = _remote_jobs.get(job_id)
                    if job is None:
                        self._send_json(404, {"ok": False, "error": "Job not found."})
                        return

                    if job.get("agent_id") != agent_id:
                        self._send_json(403, {"ok": False, "error": "Job does not belong to this agent."})
                        return

                    job["status"] = "completed" if status_text == "success" else "failed"
                    job["finished_at"] = _utcnow_iso()
                    job["result"] = payload.get("result") if status_text == "success" else None
                    job["error"] = payload.get("error") if status_text == "error" else None

                    _agent_state[agent_id] = {
                        **_agent_state.get(agent_id, {}),
                        "last_seen": _utcnow_iso(),
                    }

                self._send_json(
                    200,
                    {
                        "ok": True,
                        "status": "recorded",
                        "job_id": job_id,
                        "job_status": "completed" if status_text == "success" else "failed",
                    },
                )
                return
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return

        if parsed.path != "/device_action":
            self._send_json(404, {"ok": False, "error": "Not found"})
            return

        try:
            payload = self._read_json()
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
