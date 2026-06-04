#!/usr/bin/env bash
set -euo pipefail

REPO_SLUG="${LUMATOOLS_REPO:-Pedrohs1771/Luma-Tools}"
WORK_DIR="${LUMATOOLS_BOOTSTRAP_DIR:-${XDG_DOWNLOAD_DIR:-$HOME/Downloads}/LumaTools-Install}"
API_URL="https://api.github.com/repos/$REPO_SLUG/releases/latest"

log() {
    printf '[LumaTools bootstrap] %s\n' "$1"
}

die() {
    printf '[LumaTools bootstrap] Erro: %s\n' "$1" >&2
    exit 1
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1
}

download_to_file() {
    local url="$1"
    local target="$2"
    if need_cmd curl; then
        curl -fL --retry 3 -o "$target" "$url"
        return
    fi
    if need_cmd wget; then
        wget -O "$target" "$url"
        return
    fi
    die "Preciso de curl ou wget para baixar o LumaTools."
}

extract_zip() {
    local archive="$1"
    local target="$2"
    mkdir -p "$target"
    if need_cmd unzip; then
        unzip -q "$archive" -d "$target"
        return
    fi
    if need_cmd python3; then
        python3 -m zipfile -e "$archive" "$target"
        return
    fi
    if need_cmd bsdtar; then
        bsdtar -xf "$archive" -C "$target"
        return
    fi
    die "Preciso de unzip, python3 ou bsdtar para extrair o ZIP."
}

pick_asset_url() {
    local releases_json="$1"
    if need_cmd python3; then
        python3 - "$releases_json" <<'PY'
import json
import sys
from pathlib import Path

releases = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if isinstance(releases, dict):
    releases = [releases]

for release in releases:
    for asset in release.get("assets", []):
        name = str(asset.get("name", ""))
        lower = name.lower()
        if lower.endswith(".zip") and "linux" in lower and "windows" not in lower:
            print(asset["browser_download_url"])
            raise SystemExit(0)
raise SystemExit(1)
PY
        return
    fi

    grep -Eo 'https://[^"]+LumaTools[^"]*Linux[^"]*\.zip' "$releases_json" | head -n 1
}

main() {
    mkdir -p "$WORK_DIR"
    rm -rf "$WORK_DIR/extract"
    mkdir -p "$WORK_DIR/extract"

    local releases_json archive asset_url install_dir
    local installer_args=("$@")
    releases_json="$WORK_DIR/releases.json"
    archive="$WORK_DIR/LumaTools-Linux.zip"

    log "Consultando a release mais recente em $REPO_SLUG..."
    download_to_file "$API_URL" "$releases_json"

    asset_url="$(pick_asset_url "$releases_json" || true)"
    if [ -z "$asset_url" ]; then
        die "Não encontrei asset Linux .zip na release mais recente."
    fi

    log "Baixando pacote Linux completo..."
    download_to_file "$asset_url" "$archive"

    log "Extraindo pacote..."
    extract_zip "$archive" "$WORK_DIR/extract"

    install_dir="$(find "$WORK_DIR/extract" -maxdepth 3 -type f -name install.sh -printf '%h\n' | head -n 1)"
    if [ -z "$install_dir" ]; then
        die "Pacote inválido: install.sh não encontrado."
    fi

    log "Executando instalador..."
    (
        cd "$install_dir"
        if [ "${#installer_args[@]}" -gt 0 ]; then
            bash install.sh "${installer_args[@]}"
        else
            bash install.sh --no-prompt
        fi
    )

    if command -v lumatools >/dev/null 2>&1; then
        log "Instalação concluída. Abra com: lumatools"
    else
        log "Instalação concluída. Se o comando não abrir, reinicie o terminal e rode: lumatools"
    fi
}

main "$@"
