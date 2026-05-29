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
REQUIREMENTS_FILE="$ROOT_DIR/app/ACCELA/squashfs-root/bin/requirements.txt"
TEST_REPORT="$ROOT_DIR/TEST_REPORT.md"

run_test() {
    local label="$1"
    shift
    echo "==> $label"
    "$@"
}

append_report() {
    printf '%s\n' "$1" >> "$TEST_REPORT"
}

validate_json_file() {
    local target="$1"
    python3 - "$target" <<'PY'
import json
import sys
from pathlib import Path

json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
PY
}

generate_test_report() {
    : > "$TEST_REPORT"
    append_report "# TEST REPORT"
    append_report ""
    append_report "- Date: $(date -Iseconds)"
    append_report "- Host: $(uname -srvmo)"
    append_report "- Python: $(python3 --version 2>&1)"
    append_report ""
    append_report "## Checks"
    append_report "- bash -n: install.sh, dev-install.sh, publish-update.sh, AppRun, run.sh"
    append_report "- python compileall: app/ACCELA/squashfs-root/bin/src"
    append_report "- fresh venv install: requirements.txt"
    append_report "- desktop-file-validate: accela.desktop (when tool is available)"
    append_report "- JSON validation: release/latest.json"
}

run_preflight() {
    local tmp_venv
    tmp_venv="$(mktemp -d /tmp/accela-preflight-XXXXXX)"
    trap 'rm -rf "$tmp_venv"' RETURN

    generate_test_report

    run_test "bash -n install.sh" bash -n "$ROOT_DIR/install.sh"
    run_test "bash -n dev-install.sh" bash -n "$ROOT_DIR/dev-install.sh"
    run_test "bash -n publish-update.sh" bash -n "$ROOT_DIR/publish-update.sh"
    run_test "bash -n AppRun" bash -n "$ROOT_DIR/app/ACCELA/squashfs-root/AppRun"
    run_test "bash -n run.sh" bash -n "$ROOT_DIR/app/ACCELA/squashfs-root/bin/run.sh"

    if command -v shellcheck >/dev/null 2>&1; then
        run_test "shellcheck shell scripts" shellcheck \
            "$ROOT_DIR/install.sh" \
            "$ROOT_DIR/dev-install.sh" \
            "$ROOT_DIR/publish-update.sh" \
            "$ROOT_DIR/app/ACCELA/squashfs-root/AppRun" \
            "$ROOT_DIR/app/ACCELA/squashfs-root/bin/run.sh"
        append_report "- shellcheck: passed"
    else
        append_report "- shellcheck: skipped (not installed)"
    fi

    run_test "python compileall" python3 -m compileall "$ROOT_DIR/app/ACCELA/squashfs-root/bin/src"
    append_report "- compileall: passed"

    run_test "python -m venv preflight" python3 -m venv "$tmp_venv"
    run_test "pip upgrade in fresh venv" "$tmp_venv/bin/pip" install --upgrade pip setuptools wheel
    run_test "pip install requirements in fresh venv" "$tmp_venv/bin/pip" install -r "$REQUIREMENTS_FILE"
    run_test "import smoke test" "$tmp_venv/bin/python" - <<'PY'
import importlib
for module in ("PyQt6", "requests", "bs4", "cachetools"):
    importlib.import_module(module)
print("deps ok")
PY
    append_report "- fresh venv: passed"

    if command -v desktop-file-validate >/dev/null 2>&1; then
        run_test "desktop-file-validate" desktop-file-validate "$ROOT_DIR/app/ACCELA/squashfs-root/ACCELA.desktop"
        append_report "- desktop file: passed"
    else
        append_report "- desktop file: skipped (desktop-file-validate not installed)"
    fi

    if [ -f "$RELEASE_DIR/latest.json" ]; then
        run_test "validate release/latest.json" validate_json_file "$RELEASE_DIR/latest.json"
        append_report "- release/latest.json: valid"
    fi
}

write_manifest() {
    local display_name="$1"
    local commit_sha="$2"
    local package_url="$3"
    local sha_url="$4"
    local sig_url="$5"
    local html_url="$6"

    python3 - "$RELEASE_DIR/latest.json" "$display_name" "$commit_sha" "$package_url" "$sha_url" "$sig_url" "$html_url" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
payload = {
    "version": sys.argv[2],
    "display_name": sys.argv[2],
    "commit_sha": sys.argv[3],
    "package_url": sys.argv[4],
    "sha256_url": sys.argv[5],
    "signature_url": sys.argv[6],
    "html_url": sys.argv[7],
    "notes": "Canal rolling do ACCELA.",
}
target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
    validate_json_file "$RELEASE_DIR/latest.json"
}

main() {
    if [ ! -f "$PRIVATE_KEY" ]; then
        echo "Chave privada ausente em $PRIVATE_KEY" >&2
        exit 1
    fi

    mkdir -p "$DIST_DIR" "$RELEASE_DIR/signing"

    if [ ! -f "$PUBLIC_KEY" ]; then
        openssl pkey -in "$PRIVATE_KEY" -pubout -out "$PUBLIC_KEY"
    fi

    run_preflight

    git add .
    if ! git diff --cached --quiet; then
        git commit -m "$MESSAGE"
    fi

    git push origin main

    local commit_sha short_sha display_name
    commit_sha="$(git rev-parse HEAD)"
    short_sha="$(printf '%s' "$commit_sha" | cut -c1-8)"
    display_name="main-$short_sha"

    rm -f "$ARCHIVE_PATH" "$SHA_PATH" "$SIG_PATH"
    git archive --format zip --output "$ARCHIVE_PATH" HEAD
    sha256sum "$ARCHIVE_PATH" | awk '{print $1}' > "$SHA_PATH"
    openssl dgst -sha256 -sign "$PRIVATE_KEY" -out "$SIG_PATH" "$ARCHIVE_PATH"

    if ! gh release view "$RELEASE_TAG" >/dev/null 2>&1; then
        gh release create "$RELEASE_TAG" --title "ACCELA Rolling" --notes "Canal rolling do ACCELA"
    fi

    gh release upload "$RELEASE_TAG" "$ARCHIVE_PATH" "$SHA_PATH" "$SIG_PATH" --clobber

    local package_url sha_url sig_url html_url
    package_url="https://github.com/$REPO_SLUG/releases/download/$RELEASE_TAG/$ARCHIVE_NAME"
    sha_url="https://github.com/$REPO_SLUG/releases/download/$RELEASE_TAG/$SHA_NAME"
    sig_url="https://github.com/$REPO_SLUG/releases/download/$RELEASE_TAG/$SIG_NAME"
    html_url="https://github.com/$REPO_SLUG/releases/tag/$RELEASE_TAG"

    write_manifest "$display_name" "$commit_sha" "$package_url" "$sha_url" "$sig_url" "$html_url"

    git add "$RELEASE_DIR/latest.json" "$PUBLIC_KEY" "$TEST_REPORT"
    if ! git diff --cached --quiet; then
        git commit -m "update rolling manifest $display_name"
        git push origin main
    fi

    echo "Publicado: $display_name"
    echo "Asset: $package_url"
}

main "$@"
