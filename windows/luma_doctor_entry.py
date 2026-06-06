from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _src_root() -> Path:
    return Path(__file__).resolve().parents[1] / "bin" / "src"


def main() -> int:
    src = _src_root()
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

    parser = argparse.ArgumentParser(description="LumaTools Windows Doctor")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    from platforms import get_backend

    backend = get_backend("win32")
    payload = {
        "ok": True,
        "tool": "LumaDoctor",
        "platform": "windows",
        "self_test": bool(args.self_test),
        "backend": backend.health(),
    }
    if args.json or args.self_test:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("LumaDoctor Windows OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
