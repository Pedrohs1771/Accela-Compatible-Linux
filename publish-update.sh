#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

MESSAGE="${1:-update}"
REPO_SLUG="Pedrohs1771/Accela-Compatible-Linux"
RELEASE_TAG="rolling"
DIST_DIR="$ROOT_DIR/dist"
RELEASE_DIR="$ROOT_DIR/release"
PRIVATE_KEY="$HOME/.config/accela-release-signing/private.pem"
PUBLIC_KEY="$RELEASE_DIR/signing/public.pem"
ARCHIVE_NAME="ACCELA-Universal-latest.zip"
ARCHIVE_PATH="$DIST_DIR/$ARCHIVE_NAME"
SHA_NAME="$ARCHIVE_NAME.sha256"
SIG_NAME="$ARCHIVE_NAME.sig"
SHA_PATH="$DIST_DIR/$SHA_NAME"
SIG_PATH="$DIST_DIR/$SIG_NAME"

if [ ! -f "$PRIVATE_KEY" ]; then
    echo "Chave privada ausente em $PRIVATE_KEY" >&2
    exit 1
fi

mkdir -p "$DIST_DIR" "$RELEASE_DIR/signing"

if [ ! -f "$PUBLIC_KEY" ]; then
    openssl pkey -in "$PRIVATE_KEY" -pubout -out "$PUBLIC_KEY"
fi

git add .
if ! git diff --cached --quiet; then
    git commit -m "$MESSAGE"
fi

git push origin main

COMMIT_SHA="$(git rev-parse HEAD)"
SHORT_SHA="$(printf '%s' "$COMMIT_SHA" | cut -c1-8)"
DISPLAY_NAME="main-$SHORT_SHA"

rm -f "$ARCHIVE_PATH" "$SHA_PATH" "$SIG_PATH"
git archive --format zip --output "$ARCHIVE_PATH" HEAD
sha256sum "$ARCHIVE_PATH" | awk '{print $1}' > "$SHA_PATH"
openssl dgst -sha256 -sign "$PRIVATE_KEY" -out "$SIG_PATH" "$ARCHIVE_PATH"

if ! gh release view "$RELEASE_TAG" >/dev/null 2>&1; then
    gh release create "$RELEASE_TAG" --title "ACCELA Rolling" --notes "Canal rolling do ACCELA"
fi

gh release upload "$RELEASE_TAG" "$ARCHIVE_PATH" "$SHA_PATH" "$SIG_PATH" --clobber

PACKAGE_URL="https://github.com/$REPO_SLUG/releases/download/$RELEASE_TAG/$ARCHIVE_NAME"
SHA_URL="https://github.com/$REPO_SLUG/releases/download/$RELEASE_TAG/$SHA_NAME"
SIG_URL="https://github.com/$REPO_SLUG/releases/download/$RELEASE_TAG/$SIG_NAME"
HTML_URL="https://github.com/$REPO_SLUG/releases/tag/$RELEASE_TAG"

python3 - "$RELEASE_DIR/latest.json" "$DISPLAY_NAME" "$COMMIT_SHA" "$PACKAGE_URL" "$SHA_URL" "$SIG_URL" "$HTML_URL" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
target.write_text(
    json.dumps(
        {
            "version": sys.argv[2],
            "display_name": sys.argv[2],
            "commit_sha": sys.argv[3],
            "package_url": sys.argv[4],
            "sha256_url": sys.argv[5],
            "signature_url": sys.argv[6],
            "html_url": sys.argv[7],
            "notes": "Canal rolling do ACCELA.",
        },
        indent=2,
        ensure_ascii=False,
    )
    + "\n",
    encoding="utf-8",
)
PY

git add "$RELEASE_DIR/latest.json" "$PUBLIC_KEY"
if ! git diff --cached --quiet; then
    git commit -m "update rolling manifest $DISPLAY_NAME"
    git push origin main
fi

echo "Publicado: $DISPLAY_NAME"
echo "Asset: $PACKAGE_URL"
