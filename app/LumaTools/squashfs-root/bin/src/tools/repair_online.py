"""Repair Online-Fix state for an already installed game."""

from __future__ import annotations

import argparse
import json
import logging
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-repair Online-Fix state for an installed game."
    )
    parser.add_argument("--appid", required=True, help="Steam AppID to repair.")
    parser.add_argument(
        "--library",
        default="",
        help="Optional Steam library path. If omitted, detected libraries are searched.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Apply repairs automatically, including Steam restart when needed.",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Repair files/config but do not restart Steam.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable repair result.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not args.auto:
        print("Use --auto to apply the Online-Fix repair backend.")
        return 2

    try:
        from core.online_fix_doctor import repair_online_fix
    except ModuleNotFoundError as exc:
        print(f"Missing LumaTools runtime dependency: {exc}", file=sys.stderr)
        return 2

    result = repair_online_fix(
        args.appid,
        library_path=args.library or None,
        auto=True,
        restart_steam=not args.no_restart,
    )
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        status = "OK" if result.ok else "FAILED"
        print(f"Online-Fix Repair {status} for AppID {args.appid}")
        print(f"Status: {result.status}")
        print(f"Profile: {result.profile_path or 'not written'}")
        print(f"Report: {result.report_path or 'not written'}")
        for action in result.actions:
            print(f"- {action}")
        if result.warnings:
            print("Warnings:")
            for warning in result.warnings:
                print(f"- {warning}")
        if result.errors:
            print("Errors:")
            for error in result.errors:
                print(f"- {error}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
