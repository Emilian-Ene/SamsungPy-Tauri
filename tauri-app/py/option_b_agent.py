import json
import os
import socket
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

CLOUD_BASE_URL = os.getenv("CLOUD_BASE_URL", "").strip().rstrip("/")
AGENT_ID = os.getenv("AGENT_ID", "").strip()
AGENT_SHARED_SECRET = os.getenv("AGENT_SHARED_SECRET", "").strip()
LOCAL_BACKEND_URL = os.getenv("LOCAL_BACKEND_URL", "http://127.0.0.1:8765").strip().rstrip("/")
AGENT_POLL_INTERVAL_SECONDS = float(os.getenv("AGENT_POLL_INTERVAL_SECONDS", "2"))
AGENT_MAX_JOBS_PER_POLL = int(os.getenv("AGENT_MAX_JOBS_PER_POLL", "5"))
AGENT_REQUEST_TIMEOUT_SECONDS = float(os.getenv("AGENT_REQUEST_TIMEOUT_SECONDS", "20"))


class AgentConfigError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if AGENT_SHARED_SECRET:
        headers["x-agent-token"] = AGENT_SHARED_SECRET
    return headers


def _json_request(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = Request(url=url, data=body, headers=_headers(), method=method)
    try:
        with urlopen(request, timeout=AGENT_REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed {url}: {exc}") from exc


def _local_get(path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{LOCAL_BACKEND_URL}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"

    request = Request(url=url, headers={"Content-Type": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=AGENT_REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Local HTTP {exc.code} {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Local request failed {url}: {exc}") from exc


def _local_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{LOCAL_BACKEND_URL}{path}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=AGENT_REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Local HTTP {exc.code} {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Local request failed {url}: {exc}") from exc


def _status_to_power_state(command: str) -> str:
    normalized = str(command).strip().lower()
    if normalized == "on":
        return "ON"
    if normalized == "off":
        return "OFF"
    if normalized == "reboot":
        return "REBOOT"
    raise ValueError("tv payload command must be on|off|reboot")


def _target_ip(payload: dict[str, Any], kind: str) -> str:
    ip = str(payload.get("tv_ip") or payload.get("ip") or "").strip()
    if not ip:
        raise ValueError(f"{kind} payload requires tv_ip (or ip)")
    return ip


def _execute_local_job(job: dict[str, Any]) -> dict[str, Any]:
    kind = str(job.get("kind", "")).strip().lower()
    payload = job.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be object")

    if kind == "device_action":
        action = str(payload.get("action", "")).strip()
        action_payload = payload.get("payload")
        if not action or not isinstance(action_payload, dict):
            raise ValueError("device_action payload requires action and payload object")
        return _local_post("/device_action", {"action": action, "payload": action_payload})

    if kind == "probe":
        ip = _target_ip(payload, "probe")
        return _local_get("/auto_probe", {"ip": ip})

    if kind == "tv":
        ip = _target_ip(payload, "tv")
        action_payload = {
            "tv_ip": ip,
            "ip": ip,
            "port": int(payload.get("port", 1515)),
            "display_id": int(payload.get("display_id", 0)),
            "protocol": payload.get("protocol", "AUTO"),
            "state": _status_to_power_state(str(payload.get("command", ""))),
        }
        return _local_post("/device_action", {"action": "power", "payload": action_payload})

    if kind == "test":
        ip = _target_ip(payload, "test")
        action_payload = {
            "tv_ip": ip,
            "ip": ip,
            "port": int(payload.get("port", 1515)),
            "display_id": int(payload.get("display_id", 0)),
            "protocol": payload.get("protocol", "AUTO"),
        }
        return _local_post("/device_action", {"action": "status", "payload": action_payload})

    if kind == "mdc_execute":
        ip = _target_ip(payload, "mdc_execute")
        command = str(payload.get("command", "")).strip()
        if not command:
            raise ValueError("mdc_execute payload requires command")

        operation = str(payload.get("operation", "auto")).strip().lower()
        args = payload.get("args", [])
        if not isinstance(args, list):
            raise ValueError("mdc_execute args must be an array")

        if operation not in {"get", "set", "auto"}:
            raise ValueError("mdc_execute operation must be get|set|auto")

        if operation == "auto":
            action = "cli_set" if len(args) > 0 else "cli_get"
        elif operation == "get":
            action = "cli_get"
        else:
            action = "cli_set"

        action_payload = {
            "tv_ip": ip,
            "ip": ip,
            "port": int(payload.get("port", 1515)),
            "display_id": int(payload.get("display_id", 0)),
            "protocol": payload.get("protocol", "AUTO"),
            "command": command,
            "args": args,
        }
        return _local_post("/device_action", {"action": action, "payload": action_payload})

    raise ValueError(f"Unsupported job kind: {kind}")


def _heartbeat() -> None:
    payload = {
        "version": "option-b-agent-1",
        "hostname": socket.gethostname(),
        "local_backend_url": LOCAL_BACKEND_URL,
    }
    _json_request("POST", f"{CLOUD_BASE_URL}/api/agent/{quote(AGENT_ID)}/heartbeat", payload)


def _poll_once() -> int:
    data = _json_request(
        "POST",
        f"{CLOUD_BASE_URL}/api/agent/{quote(AGENT_ID)}/poll",
        {"max_jobs": AGENT_MAX_JOBS_PER_POLL},
    )
    jobs = data.get("jobs") or []
    if not isinstance(jobs, list):
        return 0

    for job in jobs:
        job_id = str(job.get("job_id", "")).strip()
        if not job_id:
            continue

        try:
            result = _execute_local_job(job)
            _json_request(
                "POST",
                f"{CLOUD_BASE_URL}/api/agent/{quote(AGENT_ID)}/jobs/{quote(job_id)}/result",
                {"status": "success", "result": result, "error": None},
            )
            print(f"[agent] completed job {job_id} ({job.get('kind')})")
        except Exception as exc:
            _json_request(
                "POST",
                f"{CLOUD_BASE_URL}/api/agent/{quote(AGENT_ID)}/jobs/{quote(job_id)}/result",
                {"status": "error", "result": None, "error": str(exc)},
            )
            print(f"[agent] failed job {job_id}: {exc}")

    return len(jobs)


def _validate_config() -> None:
    missing: list[str] = []
    if not CLOUD_BASE_URL:
        missing.append("CLOUD_BASE_URL")
    if not AGENT_ID:
        missing.append("AGENT_ID")

    if missing:
        raise AgentConfigError("Missing required env vars: " + ", ".join(missing))


def main() -> None:
    _validate_config()
    print(f"[agent] starting: agent_id={AGENT_ID} cloud={CLOUD_BASE_URL} local={LOCAL_BACKEND_URL}")

    last_heartbeat = 0.0
    while True:
        now = time.time()
        try:
            if now - last_heartbeat >= 15:
                _heartbeat()
                last_heartbeat = now

            jobs_count = _poll_once()
            if jobs_count == 0:
                time.sleep(AGENT_POLL_INTERVAL_SECONDS)
        except Exception as exc:
            print(f"[agent] loop error: {exc}")
            time.sleep(max(AGENT_POLL_INTERVAL_SECONDS, 2))


if __name__ == "__main__":
    main()
