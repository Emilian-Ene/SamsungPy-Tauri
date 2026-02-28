import json
from pathlib import Path

from bridge import build_cli_catalog


def main() -> None:
    out_file = Path(__file__).resolve().parents[1] / "src" / "cli_catalog.json"
    payload = {"commands": build_cli_catalog()}
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(payload['commands'])} commands to {out_file}")


if __name__ == "__main__":
    main()
