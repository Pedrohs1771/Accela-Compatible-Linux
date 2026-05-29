#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_SOURCE="$ROOT_DIR/app/ACCELA"
DEST_DIR="$HOME/.local/share/ACCELA"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
NO_PROMPT=false

for arg in "$@"; do
    case "$arg" in
        --no-prompt)
            NO_PROMPT=true
            ;;
    esac
done

log() {
    printf '[ACCELA] %s\n' "$1"
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1
}

maybe_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
        return
    fi
    if need_cmd sudo; then
        if [ "$NO_PROMPT" = true ]; then
            sudo -n "$@" || return 1
            return
        fi
        sudo "$@"
        return
    fi
    return 1
}

install_arch_packages() {
    if ! need_cmd pacman; then
        return
    fi

    local packages=(
        curl
        wget
        git
        p7zip
        unzip
        rsync
        xdg-utils
        libnotify
        python
        steam
        lib32-glibc
        lib32-gcc-libs
    )

    if [ "$NO_PROMPT" = false ]; then
        log "Instalando dependências do Arch via pacman..."
    fi

    if ! maybe_sudo pacman -S --needed --noconfirm "${packages[@]}"; then
        log "Aviso: não foi possível instalar pacotes automaticamente. Continuando."
    fi
}

sync_tree() {
    mkdir -p "$DEST_DIR"

    rsync -a --delete "$APP_SOURCE/squashfs-root/" "$DEST_DIR/squashfs-root/"
    rsync -a --delete "$APP_SOURCE/tools/" "$DEST_DIR/tools/"

    install -Dm644 "$APP_SOURCE/.version" "$DEST_DIR/.version"

    cat > "$DEST_DIR/ACCELA.AppImage" <<'SH'
#!/usr/bin/env sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/squashfs-root/AppRun" "$@"
SH
    chmod +x "$DEST_DIR/ACCELA.AppImage"

    mkdir -p \
        "$DEST_DIR/logs" \
        "$DEST_DIR/depots" \
        "$DEST_DIR/hubcap_manifests" \
        "$DEST_DIR/SLScheevo"
}

setup_python_env() {
    local venv_dir="$DEST_DIR/squashfs-root/bin/.venv"
    local req_file="$DEST_DIR/squashfs-root/bin/requirements.txt"

    log "Preparando ambiente Python..."
    python3 -m venv "$venv_dir"
    "$venv_dir/bin/pip" install --upgrade pip setuptools wheel
    "$venv_dir/bin/pip" install -r "$req_file"
}

install_slssteam() {
    local tmp_dir
    local archive
    local release_json
    local asset_url
    local latest_version

    tmp_dir="$(mktemp -d)"
    archive="$tmp_dir/SLSsteam-Any.7z"
    release_json="$tmp_dir/release.json"

    log "Baixando SLSsteam oficial..."
    curl -fsSL \
        "https://api.github.com/repos/AceSLS/SLSsteam/releases/latest" \
        -H "Accept: application/vnd.github+json" \
        -H "User-Agent: ACCELA" \
        -o "$release_json"

    asset_url="$(python3 - "$release_json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    release = json.load(handle)

for asset in release.get("assets", []):
    name = str(asset.get("name", ""))
    if name.startswith("SLSsteam-Any") and name.endswith(".7z"):
        print(asset["browser_download_url"])
        raise SystemExit(0)

raise SystemExit(1)
PY
)"
    latest_version="$(python3 - "$release_json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    release = json.load(handle)

print(release.get("tag_name", "").strip())
PY
)"

    curl -fsSL "$asset_url" -o "$archive"
    mkdir -p "$tmp_dir/extract"
    7z x "$archive" "-o$tmp_dir/extract" -y >/dev/null

    if [ -f "$tmp_dir/extract/setup.sh" ]; then
        chmod +x "$tmp_dir/extract/setup.sh"
        (
            cd "$tmp_dir/extract"
            bash "./setup.sh" install
        )
    else
        local setup_script="$tmp_dir/setup.sh"
        curl -fsSL \
            "https://raw.githubusercontent.com/AceSLS/SLSsteam/main/setup.sh" \
            -o "$setup_script"
        chmod +x "$setup_script"
        (
            cd "$tmp_dir/extract"
            bash "$setup_script" install
        )
    fi

    if [ -n "$latest_version" ]; then
        mkdir -p "$HOME/.local/share/SLSsteam"
        printf '%s\n' "$latest_version" > "$HOME/.local/share/SLSsteam/VERSION"
    fi
}

install_launchers() {
    log "Instalando launchers..."
    mkdir -p "$BIN_DIR"

    cat > "$BIN_DIR/accela" <<'SH'
#!/usr/bin/env sh
exec "$HOME/.local/share/ACCELA/ACCELA.AppImage" "$@"
SH
    chmod +x "$BIN_DIR/accela"

    python3 - "$BIN_DIR" <<'PY'
import itertools
import os
import pathlib
import sys

bin_dir = pathlib.Path(sys.argv[1])
target = bin_dir / "accela"
name = "accela"
for bits in itertools.product((0, 1), repeat=len(name)):
    variant = "".join(
        char.upper() if bit else char.lower()
        for char, bit in zip(name, bits)
    )
    path = bin_dir / variant
    if path == target:
        continue
    if path.exists() or path.is_symlink():
        path.unlink()
    path.symlink_to(target.name)
PY
}

install_desktop_entry() {
    log "Instalando atalhos..."
    mkdir -p "$APPS_DIR" "$ICON_DIR"

    install -Dm644 \
        "$DEST_DIR/squashfs-root/bin/src/res/logo/icon.png" \
        "$ICON_DIR/accela.png"

    cat > "$APPS_DIR/accela.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=ACCELA
Comment=Launcher ACCELA para Linux
Exec=$BIN_DIR/accela
Icon=accela
Terminal=false
Categories=Game;Utility;
StartupNotify=true
MimeType=x-scheme-handler/accela;
EOF

    if need_cmd update-desktop-database; then
        update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
    fi
}

main() {
    if [ ! -d "$APP_SOURCE" ]; then
        log "Pacote inválido: app/ACCELA não encontrado."
        exit 1
    fi

    install_arch_packages
    sync_tree
    setup_python_env
    install_slssteam || log "Aviso: falha ao instalar SLSsteam automaticamente."
    install_launchers
    install_desktop_entry

    log "Instalação concluída."
    log "Abra com: accela"
}

main "$@"
