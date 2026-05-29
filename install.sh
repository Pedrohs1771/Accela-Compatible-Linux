#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DEFAULT_APP_SOURCE="$ROOT_DIR/app/ACCELA"
INSTALLED_APP_SOURCE="$ROOT_DIR"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

APP_SOURCE=""
DEST_DIR=""
MODE=""
PORTABLE_DIR=""
NO_PROMPT=false
DIAGNOSE=false
JSON_OUTPUT=false
SOURCE_REVISION=""
SOURCE_VERSION=""

OS_ID=""
OS_LIKE=""
OS_PRETTY=""
OS_FAMILY=""
OS_VARIANT=""
STEAM_MODE=""
GPU_INFO=""
RECOMMENDED_MODE=""
IS_IMMUTABLE=false

missing_deps=()

while [ "$#" -gt 0 ]; do
    arg="$1"
    case "$arg" in
        --no-prompt)
            NO_PROMPT=true
            ;;
        --diagnose)
            DIAGNOSE=true
            ;;
        --json)
            JSON_OUTPUT=true
            ;;
        --portable)
            MODE="portable"
            ;;
        --repair)
            MODE="repair"
            ;;
        --mode)
            MODE="${2:-}"
            shift
            ;;
        --portable-dir)
            PORTABLE_DIR="${2:-}"
            shift
            ;;
        --source-revision)
            SOURCE_REVISION="${2:-}"
            shift
            ;;
        --source-version)
            SOURCE_VERSION="${2:-}"
            shift
            ;;
    esac
    shift
done

log() {
    printf '[ACCELA] %s\n' "$1"
}

warn() {
    printf '[ACCELA] Aviso: %s\n' "$1" >&2
}

die() {
    printf '[ACCELA] Erro: %s\n' "$1" >&2
    exit 1
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

join_by() {
    local delimiter="$1"
    shift || true
    local first=true
    for item in "$@"; do
        if [ "$first" = true ]; then
            printf '%s' "$item"
            first=false
        else
            printf '%s%s' "$delimiter" "$item"
        fi
    done
}

resolve_app_source() {
    if [ -d "$DEFAULT_APP_SOURCE/squashfs-root" ]; then
        APP_SOURCE="$DEFAULT_APP_SOURCE"
        return
    fi

    if [ -d "$INSTALLED_APP_SOURCE/squashfs-root" ]; then
        APP_SOURCE="$INSTALLED_APP_SOURCE"
        return
    fi

    die "Pacote inválido: não encontrei o diretório ACCELA."
}

detect_os() {
    local os_release="/etc/os-release"
    if [ -f "$os_release" ]; then
        # shellcheck disable=SC1091
        . "$os_release"
        OS_ID="${ID:-linux}"
        OS_LIKE="${ID_LIKE:-}"
        OS_PRETTY="${PRETTY_NAME:-${NAME:-Linux}}"
        OS_VARIANT="${VARIANT_ID:-}"
    else
        OS_ID="linux"
        OS_LIKE=""
        OS_PRETTY="Linux"
        OS_VARIANT=""
    fi

    case "$OS_ID" in
        arch|manjaro|endeavouros)
            OS_FAMILY="arch"
            ;;
        ubuntu|debian|linuxmint|pop|neon|elementary|zorin)
            OS_FAMILY="debian"
            ;;
        fedora|nobara|bazzite|ultramarine|rhel|centos)
            OS_FAMILY="fedora"
            ;;
        opensuse*|sles)
            OS_FAMILY="suse"
            ;;
        gentoo)
            OS_FAMILY="gentoo"
            ;;
        nixos)
            OS_FAMILY="nix"
            ;;
        steamos|holoiso)
            OS_FAMILY="steamos"
            ;;
        *)
            case " $OS_LIKE " in
                *" arch "*) OS_FAMILY="arch" ;;
                *" debian "*) OS_FAMILY="debian" ;;
                *" ubuntu "*) OS_FAMILY="debian" ;;
                *" fedora "*) OS_FAMILY="fedora" ;;
                *" rhel "*) OS_FAMILY="fedora" ;;
                *" suse "*) OS_FAMILY="suse" ;;
                *" gentoo "*) OS_FAMILY="gentoo" ;;
                *)
                    OS_FAMILY="linux"
                    ;;
            esac
            ;;
    esac

    if [ "$OS_FAMILY" = "steamos" ] || [ "$OS_ID" = "steamos" ]; then
        IS_IMMUTABLE=true
    fi

    if [ "$OS_ID" = "bazzite" ] || [ "$OS_VARIANT" = "bazzite" ]; then
        IS_IMMUTABLE=true
    fi

    if need_cmd rpm-ostree; then
        IS_IMMUTABLE=true
    fi
}

detect_steam_mode() {
    STEAM_MODE="Ausente"

    if need_cmd flatpak && flatpak info com.valvesoftware.Steam >/dev/null 2>&1; then
        STEAM_MODE="Flatpak"
        return
    fi

    if [ -d "$HOME/.local/share/flatpak/app/com.valvesoftware.Steam" ]; then
        STEAM_MODE="Flatpak"
        return
    fi

    if need_cmd snap && snap list steam >/dev/null 2>&1; then
        STEAM_MODE="Snap"
        return
    fi

    if [ -d "$HOME/snap/steam" ]; then
        STEAM_MODE="Snap"
        return
    fi

    if [ -d "$HOME/.local/share/Steam" ] || [ -d "$HOME/.steam/steam" ] || need_cmd steam; then
        STEAM_MODE="Nativa"
        return
    fi
}

detect_gpu() {
    GPU_INFO="Desconhecida"

    if need_cmd lspci; then
        GPU_INFO="$(
            lspci \
                | grep -Ei 'vga|3d|display' \
                | sed 's/^[0-9a-fA-F:. -]*//' \
                | paste -sd '; ' - \
                | sed 's/; $//' \
                || true
        )"
    fi

    if [ -z "$GPU_INFO" ] || [ "$GPU_INFO" = "Desconhecida" ]; then
        if [ -r /sys/class/drm/card0/device/uevent ]; then
            GPU_INFO="$(grep '^DRIVER=' /sys/class/drm/card0/device/uevent | cut -d= -f2 || true)"
        fi
    fi

    if [ -z "$GPU_INFO" ]; then
        GPU_INFO="Desconhecida"
    fi
}

has_dotnet_9() {
    local dotnet_bin=""

    if need_cmd dotnet; then
        dotnet_bin="$(command -v dotnet)"
    elif [ -x "$HOME/.dotnet/dotnet" ]; then
        dotnet_bin="$HOME/.dotnet/dotnet"
    fi

    if [ -z "$dotnet_bin" ]; then
        return 1
    fi

    "$dotnet_bin" --list-runtimes 2>/dev/null | grep -q 'Microsoft.NETCore.App 9\.'
}

detect_recommended_mode() {
    if [ "$STEAM_MODE" = "Flatpak" ]; then
        RECOMMENDED_MODE="flatpak-compatible"
        return
    fi

    if [ "$STEAM_MODE" = "Snap" ]; then
        RECOMMENDED_MODE="snap-compatible"
        return
    fi

    if [ "$OS_FAMILY" = "steamos" ] || [ "$OS_ID" = "steamos" ]; then
        RECOMMENDED_MODE="steamdeck"
        return
    fi

    if [ "$OS_FAMILY" = "nix" ] || [ "$IS_IMMUTABLE" = true ]; then
        RECOMMENDED_MODE="portable"
        return
    fi

    RECOMMENDED_MODE="system"
}

collect_missing_deps() {
    missing_deps=()

    if ! has_dotnet_9; then
        missing_deps+=("dotnet 9")
    fi

    if ! need_cmd 7z; then
        missing_deps+=("p7zip")
    fi

    if ! need_cmd rsync; then
        missing_deps+=("rsync")
    fi

    if ! need_cmd python3; then
        missing_deps+=("python3")
    fi

    if ! need_cmd curl && ! need_cmd wget; then
        missing_deps+=("curl/wget")
    fi

    if ! need_cmd openssl; then
        missing_deps+=("openssl")
    fi

    if ! need_cmd git; then
        missing_deps+=("git")
    fi

    if ! need_cmd rclone && [ ! -x "$APP_SOURCE/tools/rclone/rclone" ]; then
        missing_deps+=("rclone")
    fi
}

print_diagnostics() {
    local deps_string
    if [ "${#missing_deps[@]}" -eq 0 ]; then
        deps_string="nenhuma"
    else
        deps_string="$(join_by ', ' "${missing_deps[@]}")"
    fi

    if [ "$JSON_OUTPUT" = true ]; then
        SYSTEM_NAME="$OS_PRETTY" \
        STEAM_NAME="$STEAM_MODE" \
        GPU_NAME="$GPU_INFO" \
        DEPS_NAME="$deps_string" \
        MODE_NAME="$RECOMMENDED_MODE" \
        OS_ID_NAME="$OS_ID" \
        OS_FAMILY_NAME="$OS_FAMILY" \
        IMMUTABLE_NAME="$IS_IMMUTABLE" \
        python3 - <<'PY'
import json
import os

deps = os.environ.get("DEPS_NAME", "nenhuma")
missing = [] if deps == "nenhuma" else [item.strip() for item in deps.split(",")]
print(
    json.dumps(
        {
            "system": os.environ.get("SYSTEM_NAME", "Linux"),
            "os_id": os.environ.get("OS_ID_NAME", "linux"),
            "os_family": os.environ.get("OS_FAMILY_NAME", "linux"),
            "steam_mode": os.environ.get("STEAM_NAME", "Ausente"),
            "gpu": os.environ.get("GPU_NAME", "Desconhecida"),
            "missing_dependencies": missing,
            "recommended_mode": os.environ.get("MODE_NAME", "system"),
            "immutable": os.environ.get("IMMUTABLE_NAME", "false") == "true",
        },
        ensure_ascii=False,
    )
)
PY
        return
    fi

    printf 'Sistema detectado: %s\n' "$OS_PRETTY"
    printf 'Steam detectada: %s\n' "$STEAM_MODE"
    printf 'GPU: %s\n' "$GPU_INFO"
    printf 'Dependências faltando: %s\n' "$deps_string"
    printf 'Modo recomendado: %s\n' "$RECOMMENDED_MODE"
}

prompt_for_mode() {
    if [ -n "$MODE" ]; then
        return
    fi

    if [ "$NO_PROMPT" = true ]; then
        case "$RECOMMENDED_MODE" in
            portable|steamdeck)
                MODE="portable"
                ;;
            *)
                MODE="install"
                ;;
        esac
        return
    fi

    print_diagnostics
    printf '\n'
    printf '[1] Instalar tudo\n'
    printf '[2] Modo portátil\n'
    printf '[3] Somente reparar\n'
    printf '\nEscolha um modo [1/2/3]: '

    local answer=""
    read -r answer
    case "$answer" in
        2)
            MODE="portable"
            ;;
        3)
            MODE="repair"
            ;;
        *)
            MODE="install"
            ;;
    esac
}

resolve_dest_dir() {
    if [ "$MODE" = "portable" ]; then
        if [ -n "$PORTABLE_DIR" ]; then
            DEST_DIR="$PORTABLE_DIR"
        else
            DEST_DIR="$HOME/Applications/ACCELA-Portable"
        fi
    else
        DEST_DIR="$HOME/.local/share/ACCELA"
    fi
}

write_runtime_wrapper() {
    cat > "$DEST_DIR/ACCELA.AppImage" <<'SH'
#!/usr/bin/env sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/squashfs-root/AppRun" "$@"
SH
    chmod +x "$DEST_DIR/ACCELA.AppImage"
}

create_backup() {
    if [ ! -d "$DEST_DIR/squashfs-root" ]; then
        return
    fi

    local backup_root="$DEST_DIR/backups"
    local current_version="unknown"
    if [ -f "$DEST_DIR/.version" ]; then
        current_version="$(tr -cd '[:alnum:]. _-' < "$DEST_DIR/.version" | tr ' ' '_')"
        current_version="${current_version:-unknown}"
    fi

    local timestamp
    timestamp="$(date '+%Y%m%d-%H%M%S')"
    local backup_dir="$backup_root/${timestamp}__${current_version}"

    mkdir -p "$backup_dir"
    log "Criando backup de rollback em $backup_dir ..."

    if need_cmd rsync; then
        rsync -a --delete --exclude 'backups' "$DEST_DIR/" "$backup_dir/"
    else
        BACKUP_SOURCE="$DEST_DIR" BACKUP_TARGET="$backup_dir" python3 - <<'PY'
import os
import shutil
from pathlib import Path

source = Path(os.environ["BACKUP_SOURCE"])
target = Path(os.environ["BACKUP_TARGET"])
for child in source.iterdir():
    if child.name == "backups":
        continue
    destination = target / child.name
    if child.is_dir():
        shutil.copytree(child, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(child, destination)
PY
    fi
}

sync_tree() {
    mkdir -p "$DEST_DIR"

    if [ "$MODE" != "portable" ]; then
        create_backup
    fi

    rsync -a --delete "$APP_SOURCE/squashfs-root/" "$DEST_DIR/squashfs-root/"
    rsync -a --delete "$APP_SOURCE/tools/" "$DEST_DIR/tools/"

    if [ -d "$ROOT_DIR/release" ]; then
        rsync -a --delete "$ROOT_DIR/release/" "$DEST_DIR/release/"
    fi

    install -Dm644 "$APP_SOURCE/.version" "$DEST_DIR/.version"
    install -Dm755 "$ROOT_DIR/install.sh" "$DEST_DIR/install.sh"

    write_runtime_wrapper

    if [ -z "$SOURCE_REVISION" ] && [ -d "$ROOT_DIR/.git" ]; then
        SOURCE_REVISION="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || true)"
    fi

    if [ -z "$SOURCE_VERSION" ] && [ -n "$SOURCE_REVISION" ]; then
        SOURCE_VERSION="main-$(printf '%s' "$SOURCE_REVISION" | cut -c1-8)"
    fi

    if [ -n "$SOURCE_REVISION" ]; then
        printf '%s\n' "$SOURCE_REVISION" > "$DEST_DIR/.repo_revision"
    fi

    if [ -n "$SOURCE_VERSION" ]; then
        printf '%s\n' "$SOURCE_VERSION" > "$DEST_DIR/.version"
        printf '%s\n' "$SOURCE_VERSION" > "$DEST_DIR/squashfs-root/bin/src/res/version"
    fi

    mkdir -p \
        "$DEST_DIR/logs" \
        "$DEST_DIR/depots" \
        "$DEST_DIR/hubcap_manifests" \
        "$DEST_DIR/SLScheevo" \
        "$DEST_DIR/backups"
}

install_dotnet_9_local() {
    if has_dotnet_9; then
        return
    fi

    local tmp_dir install_script
    tmp_dir="$(mktemp -d)"
    install_script="$tmp_dir/dotnet-install.sh"
    mkdir -p "$HOME/.dotnet"

    log "Instalando .NET 9 em $HOME/.dotnet ..."
    if need_cmd curl; then
        curl -fsSL "https://dot.net/v1/dotnet-install.sh" -o "$install_script"
    elif need_cmd wget; then
        wget -qO "$install_script" "https://dot.net/v1/dotnet-install.sh"
    else
        die "Nem curl nem wget estão disponíveis para instalar o .NET 9."
    fi

    chmod +x "$install_script"
    DOTNET_ROOT="$HOME/.dotnet" bash "$install_script" --channel 9.0 --runtime dotnet
}

install_system_packages() {
    local packages=()

    if [ "$IS_IMMUTABLE" = true ] || [ "$OS_FAMILY" = "nix" ]; then
        warn "Seu sistema é imutável. Vou usar o modo portátil/local sempre que possível."
        return
    fi

    case "$OS_FAMILY" in
        arch)
            packages=(
                curl
                wget
                git
                p7zip
                unzip
                rsync
                xdg-utils
                libnotify
                python
                python-pip
                python-setuptools
                python-virtualenv
                openssl
            )
            if ! has_dotnet_9; then
                packages+=(dotnet-runtime-9.0)
            fi
            ;;
        debian)
            packages=(
                curl
                wget
                git
                p7zip-full
                unzip
                rsync
                xdg-utils
                libnotify-bin
                python3
                python3-pip
                python3-venv
                openssl
                ca-certificates
            )
            ;;
        fedora)
            packages=(
                curl
                wget
                git
                p7zip
                p7zip-plugins
                unzip
                rsync
                xdg-utils
                libnotify
                python3
                python3-pip
                openssl
                ca-certificates
            )
            ;;
        suse)
            packages=(
                curl
                wget
                git
                p7zip
                unzip
                rsync
                xdg-utils
                libnotify-tools
                python3
                python3-pip
                python3-virtualenv
                openssl
            )
            ;;
        gentoo)
            packages=(
                net-misc/curl
                net-misc/wget
                dev-vcs/git
                app-arch/p7zip
                app-arch/unzip
                sys-apps/rsync
                x11-misc/xdg-utils
                x11-libs/libnotify
                dev-lang/python
                dev-python/virtualenv
                app-crypt/openssl
            )
            ;;
        *)
            warn "Família Linux não reconhecida para auto-instalação de pacotes."
            return
            ;;
    esac

    if [ "${#packages[@]}" -eq 0 ]; then
        return
    fi

    log "Instalando dependências do sistema para $OS_PRETTY ..."

    case "$OS_FAMILY" in
        arch)
            maybe_sudo pacman -S --needed --noconfirm "${packages[@]}" || warn "Pacman falhou; seguindo com o que já existe."
            ;;
        debian)
            maybe_sudo apt-get update || warn "apt-get update falhou."
            maybe_sudo apt-get install -y "${packages[@]}" || warn "apt-get install falhou; seguindo com o que já existe."
            ;;
        fedora)
            if need_cmd dnf; then
                maybe_sudo dnf install -y "${packages[@]}" || warn "dnf falhou; seguindo com o que já existe."
            elif need_cmd yum; then
                maybe_sudo yum install -y "${packages[@]}" || warn "yum falhou; seguindo com o que já existe."
            fi
            ;;
        suse)
            maybe_sudo zypper --non-interactive install --no-recommends "${packages[@]}" || warn "zypper falhou; seguindo com o que já existe."
            ;;
        gentoo)
            maybe_sudo emerge --noreplace "${packages[@]}" || warn "emerge falhou; seguindo com o que já existe."
            ;;
    esac
}

setup_python_env() {
    local venv_dir="$DEST_DIR/squashfs-root/bin/.venv"
    local req_file="$DEST_DIR/squashfs-root/bin/requirements.txt"

    if ! need_cmd python3; then
        die "python3 não encontrado."
    fi

    log "Preparando ambiente Python..."
    python3 -m venv "$venv_dir"
    "$venv_dir/bin/pip" install --upgrade pip setuptools wheel
    "$venv_dir/bin/pip" install -r "$req_file"
}

install_slssteam() {
    if [ "$MODE" = "portable" ] && [ "$STEAM_MODE" = "Ausente" ]; then
        warn "Steam não detectada; pulando SLSsteam no modo portátil."
        return
    fi

    local tmp_dir archive release_json asset_url latest_version setup_script

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
        setup_script="$tmp_dir/setup.sh"
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
    if [ "$MODE" = "portable" ]; then
        cat > "$DEST_DIR/accela-portable" <<'SH'
#!/usr/bin/env sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/squashfs-root/AppRun" "$@"
SH
        chmod +x "$DEST_DIR/accela-portable"
        return
    fi

    log "Instalando launchers..."
    mkdir -p "$BIN_DIR"

    cat > "$BIN_DIR/accela" <<'SH'
#!/usr/bin/env sh
exec "$HOME/.local/share/ACCELA/squashfs-root/AppRun" "$@"
SH
    chmod +x "$BIN_DIR/accela"

    python3 - "$BIN_DIR" <<'PY'
import itertools
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
    if [ "$MODE" = "portable" ]; then
        return
    fi

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
Comment=Launcher ACCELA universal para Linux
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

run_installation() {
    install_system_packages
    install_dotnet_9_local
    sync_tree
    setup_python_env
    install_slssteam || warn "Falha ao instalar SLSsteam automaticamente."
    install_launchers
    install_desktop_entry
    write_runtime_wrapper
}

main() {
    resolve_app_source
    detect_os
    detect_steam_mode
    detect_gpu
    detect_recommended_mode
    collect_missing_deps

    if [ "$DIAGNOSE" = true ]; then
        print_diagnostics
        exit 0
    fi

    prompt_for_mode
    resolve_dest_dir

    case "$MODE" in
        install|portable|repair)
            ;;
        *)
            die "Modo inválido: $MODE"
            ;;
    esac

    log "Sistema detectado: $OS_PRETTY"
    log "Steam detectada: $STEAM_MODE"
    log "GPU detectada: $GPU_INFO"
    log "Modo selecionado: $MODE"

    run_installation

    if [ "$MODE" = "portable" ]; then
        log "Instalação portátil concluída em $DEST_DIR."
        log "Abra com: $DEST_DIR/accela-portable"
    else
        log "Instalação concluída."
        log "Abra com: accela"
    fi
}

main "$@"
