"""Repair an already installed LumaTools game without reinstalling it."""

from __future__ import annotations

import argparse
import json
import logging
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-repair Steam/LumaTools state for an installed game."
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
        print("Use --auto to apply the repair backend.")
        return 2

    try:
        from core.auto_fix_backend import repair_existing_game
    except ModuleNotFoundError as exc:
        print(f"Missing LumaTools runtime dependency: {exc}", file=sys.stderr)
        return 2

    result = repair_existing_game(
        args.appid,
        library_path=args.library or None,
        auto_restart_steam=not args.no_restart,
    )
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        status = "OK" if result.ok else "FAILED"
        print(f"Auto-Fix {status} for AppID {args.appid}")
        for action in result.actions:
            print(
                f"- attempted={action.auto_fix_attempted} "
                f"success={action.auto_fix_success} "
                f"reason={action.reason} action={action.action_taken}"
            )
        if result.issues:
            print("Issues:")
            for issue in result.issues:
                print(f"- {issue}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
