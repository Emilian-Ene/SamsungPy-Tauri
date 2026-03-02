import asyncio
import json
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from samsung_mdc import MDC

POWER_MAP = {0: "OFF", 1: "ON", 2: "REBOOT"}
MUTE_MAP = {0: "OFF", 1: "ON", 255: "UNAVAILABLE"}
INPUT_SOURCE_MAP = {
    0x18: "DVI",
    0x21: "HDMI1",
    0x23: "HDMI2",
    0x25: "DISPLAY_PORT_1",
    0x31: "HDMI3",
    0x33: "HDMI4",
}
PICTURE_ASPECT_MAP = {
    0x10: "PC_16_9",
    0x18: "PC_4_3",
    0x20: "PC_ORIGINAL_RATIO",
    0x01: "VIDEO_16_9",
    0x0B: "VIDEO_4_3",
}

TIMER_INDEXED_COMMANDS = {"timer_13", "timer_15"}
DEFAULT_TIMEOUT_SECONDS = 20.0
MIN_TIMEOUT_SECONDS = 3.0
MAX_TIMEOUT_SECONDS = 60.0


def _field_placeholder(field) -> str:
    field_type = type(field).__name__
    range_ = getattr(field, "range", None)
    if field_type in ("Int", "Int+range"):
        if range_:
            return f"int ({range_.start}-{range_.stop - 1})"
        return "integer"
    if field_type == "Bool":
        return "ON | OFF (or 1 / 0)"
    if field_type in ("Time", "Time12H"):
        return "HH:MM"
    if field_type == "DateTime":
        return "YYYY-MM-DD HH:MM"
    if field_type == "IPAddress":
        return "192.168.1.50"
    if field_type == "VideoWallModel":
        return "X,Y"
    if field_type in ("Str", "StrCoded"):
        return "text string"
    if field_type == "Bitmask":
        return "comma-separated values"
    return "value"


def build_cli_catalog() -> list[dict]:
    def field_to_dict(field, idx: int) -> dict:
        enum = getattr(field, "enum", None)
        enum_names = [member.name for member in enum] if enum else []
        range_ = getattr(field, "range", None)
        field_info = {
            "name": getattr(field, "name", f"arg{idx}"),
            "type": type(field).__name__,
            "enum": enum_names,
            "placeholder": _field_placeholder(field),
        }
        if range_:
            field_info["range"] = {
                "min": range_.start,
                "max": range_.stop - 1,
            }
        return field_info

    commands = []
    for command_name in sorted(MDC._commands.keys()):
        command = MDC._commands.get(command_name)
        data_fields = list(getattr(command, "DATA", []) if command else [])
        response_fields = [field_to_dict(field, idx) for idx, field in enumerate(data_fields)]

        set_enabled = bool(getattr(command, "SET", False))
        fields = [field_to_dict(field, idx) for idx, field in enumerate(data_fields)] if set_enabled else []

        # timer_13 / timer_15 require TIMER_ID in CLI usage but timer_id is not in DATA
        if command_name in ("timer_13", "timer_15"):
            timer_id_field = {
                "name": "TIMER_ID",
                "type": "Int",
                "enum": [],
                "placeholder": "int (1-7)",
                "range": {"min": 1, "max": 7},
            }
            fields = [timer_id_field, *fields]

        commands.append(
            {
                "name": command_name,
                "get": bool(getattr(command, "GET", False)),
                "set": set_enabled,
                "fields": fields,
                "response_fields": response_fields,
            }
        )

    return commands


def _coerce_cli_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        try:
            return int(text)
        except Exception:
            return text
    return text


def _parse_cli_args(payload: dict) -> tuple:
    raw_args = payload.get("args", [])
    if raw_args is None:
        return tuple()
    if not isinstance(raw_args, list):
        return tuple(_coerce_cli_value(raw_args) for raw_args in [raw_args])
    return tuple(_coerce_cli_value(item) for item in raw_args)


def label(code, mapping):
    if code is None:
        return "UNKNOWN"
    try:
        return mapping.get(int(code), f"UNKNOWN ({code})")
    except Exception:
        return f"UNKNOWN ({code})"


def decode_status(raw_status):
    values = list(raw_status)
    power = values[0] if len(values) > 0 else None
    volume = values[1] if len(values) > 1 else None
    mute = values[2] if len(values) > 2 else None
    input_source = values[3] if len(values) > 3 else None
    picture_aspect = values[4] if len(values) > 4 else None

    return {
        "power": label(power, POWER_MAP),
        "volume": volume,
        "mute": label(mute, MUTE_MAP),
        "input_source": label(input_source, INPUT_SOURCE_MAP),
        "picture_aspect": label(picture_aspect, PICTURE_ASPECT_MAP),
    }


def resolve_protocol(protocol: str, port: int) -> str:
    normalized = str(protocol or "AUTO").strip().upper()
    if normalized == "SIGNAGE_MDC":
        return normalized
    return "SIGNAGE_MDC"


def resolve_action_timeout(action: str, payload: dict) -> float:
    explicit_timeout = payload.get("timeout_s")
    if explicit_timeout is not None:
        try:
            timeout = float(explicit_timeout)
            if timeout < MIN_TIMEOUT_SECONDS:
                return MIN_TIMEOUT_SECONDS
            if timeout > MAX_TIMEOUT_SECONDS:
                return MAX_TIMEOUT_SECONDS
            return timeout
        except Exception:
            pass

    if action in {"status", "cli_get", "cli_set"}:
        return 25.0
    if action in {"power", "set_volume", "set_brightness", "set_mute", "set_input"}:
        return 20.0
    return DEFAULT_TIMEOUT_SECONDS


async def do_signage_action(action: str, payload: dict):
    ip = payload["ip"]
    port = int(payload.get("port", 1515))
    display_id = int(payload.get("display_id", 0))

    async with MDC(f"{ip}:{port}") as mdc:
        if action == "status":
            return {"status": decode_status(await mdc.status(display_id))}
        if action == "power":
            await mdc.power(display_id, (payload["state"],))
            return {"sent": "power", "state": payload["state"]}
        if action == "set_volume":
            await mdc.volume(display_id, (int(payload["value"]),))
            return {"sent": "volume", "value": int(payload["value"])}
        if action == "set_brightness":
            await mdc.brightness(display_id, (int(payload["value"]),))
            return {"sent": "brightness", "value": int(payload["value"])}
        if action == "set_mute":
            await mdc.mute(display_id, (payload["state"],))
            return {"sent": "mute", "state": payload["state"]}
        if action == "set_input":
            await mdc.input_source(display_id, (payload["source"],))
            return {"sent": "input_source", "source": payload["source"]}
        if action == "cli_get":
            command_name = str(payload.get("command", "")).strip()
            if not command_name:
                raise ValueError("MDC CLI GET requires command")
            command = MDC._commands.get(command_name)
            if command and not getattr(command, "GET", False):
                raise ValueError(f"{command_name}: this command does not support GET")
            method = getattr(mdc, command_name, None)
            if method is None:
                raise ValueError(f"Unknown MDC command: {command_name}")

            args_tuple = _parse_cli_args(payload)
            if command_name in TIMER_INDEXED_COMMANDS:
                if not args_tuple:
                    raise ValueError(f"{command_name} GET requires timer_id (1-7)")
                timer_id = int(args_tuple[0])
                if timer_id < 1 or timer_id > 7:
                    raise ValueError(
                        f"{command_name} GET: timer_id must be between 1 and 7"
                    )
                result = await method(display_id, timer_id, ())
                return {"command": command_name, "args": [timer_id], "result": str(result)}

            result = await method(display_id)
            return {"command": command_name, "result": str(result)}

        if action == "cli_set":
            command_name = str(payload.get("command", "")).strip()
            if not command_name:
                raise ValueError("MDC CLI SET requires command")
            command = MDC._commands.get(command_name)
            if command and not getattr(command, "SET", False):
                raise ValueError(f"{command_name}: this command does not support SET")
            method = getattr(mdc, command_name, None)
            if method is None:
                raise ValueError(f"Unknown MDC command: {command_name}")

            args_tuple = _parse_cli_args(payload)
            if command_name in TIMER_INDEXED_COMMANDS:
                if not args_tuple:
                    raise ValueError(
                        f"{command_name} SET requires timer_id (1-7) plus values"
                    )
                timer_id = int(args_tuple[0])
                timer_data = tuple(args_tuple[1:])
                if timer_id < 1 or timer_id > 7:
                    raise ValueError(
                        f"{command_name} SET: timer_id must be between 1 and 7"
                    )
                if not timer_data:
                    raise ValueError(
                        f"{command_name} SET requires timer values after timer_id"
                    )
                result = await method(display_id, timer_id, timer_data)
                return {
                    "command": command_name,
                    "timer_id": timer_id,
                    "args": list(timer_data),
                    "result": str(result),
                }

            result = await method(display_id, args_tuple)
            return {"command": command_name, "args": list(args_tuple), "result": str(result)}

    raise ValueError(f"Unsupported signage action: {action}")


async def main_async(action: str, payload: dict):
    if action == "cli_catalog":
        return {"ok": True, "data": {"commands": build_cli_catalog()}}

    protocol = resolve_protocol(payload.get("protocol", "AUTO"), int(payload.get("port", 1515)))
    timeout_seconds = resolve_action_timeout(action, payload)
    try:
        data = await asyncio.wait_for(
            do_signage_action(action, payload),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            f"MDC action timeout after {timeout_seconds:.1f}s"
        ) from exc
    return {"ok": True, "protocol": protocol, "data": data}


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False, "error": "Usage: bridge.py <action> <json_payload>"}))
        raise SystemExit(2)

    action = sys.argv[1]
    payload = json.loads(sys.argv[2])

    try:
        result = asyncio.run(main_async(action, payload))
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
