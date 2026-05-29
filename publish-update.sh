#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

MESSAGE="${1:-update}"

git add .
if git diff --cached --quiet; then
    echo "Sem mudanças para publicar."
    exit 0
fi

git commit -m "$MESSAGE"
git push origin main
