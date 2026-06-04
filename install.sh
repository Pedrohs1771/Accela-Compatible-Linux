#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DEFAULT_APP_SOURCE="$ROOT_DIR/app/LumaTools"
INSTALLED_APP_SOURCE="$ROOT_DIR"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/LumaTools"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/LumaTools"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/LumaTools"

APP_SOURCE=""
DEST_DIR=""
MODE=""
PORTABLE_DIR=""
NO_PROMPT=false
DIAGNOSE=false
JSON_OUTPUT=false
SOURCE_REVISION=""
SOURCE_VERSION=""
DRY_RUN=false
DOCTOR=false
SELF_TEST=false
PATHS_ONLY=false
USER_ONLY=false
FIX_ALL=false

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
        --fix-all)
            MODE="repair"
            NO_PROMPT=true
            FIX_ALL=true
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
        --dry-run)
            DRY_RUN=true
            ;;
        --doctor)
            DOCTOR=true
            ;;
        --self-test)
            SELF_TEST=true
            ;;
        --paths)
            PATHS_ONLY=true
            ;;
        --user-only)
            USER_ONLY=true
            ;;
    esac
    shift
done

log() {
    printf '[LumaTools] %s\n' "$1"
}

warn() {
    printf '[LumaTools] Aviso: %s\n' "$1" >&2
}

die() {
    printf '[LumaTools] Erro: %s\n' "$1" >&2
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

print_paths() {
    local app_dir="${PORTABLE_DIR:-$HOME/.local/share/LumaTools}"
    local launcher_path="$BIN_DIR/lumatools"
    local desktop_path="$APPS_DIR/lumatools.desktop"

    if [ "$JSON_OUTPUT" = true ]; then
        APP_DIR_NAME="$app_dir" \
        BIN_DIR_NAME="$BIN_DIR" \
        DESKTOP_PATH_NAME="$desktop_path" \
        ICON_DIR_NAME="$ICON_DIR" \
        CACHE_DIR_NAME="$CACHE_DIR" \
        STATE_DIR_NAME="$STATE_DIR" \
        CONFIG_DIR_NAME="$CONFIG_DIR" \
        LAUNCHER_PATH_NAME="$launcher_path" \
        python3 - <<'PY'
import json
import os

print(
    json.dumps(
        {
            "app_dir": os.environ["APP_DIR_NAME"],
            "launcher": os.environ["LAUNCHER_PATH_NAME"],
            "desktop_entry": os.environ["DESKTOP_PATH_NAME"],
            "bin_dir": os.environ["BIN_DIR_NAME"],
            "icon_dir": os.environ["ICON_DIR_NAME"],
            "cache_dir": os.environ["CACHE_DIR_NAME"],
            "state_dir": os.environ["STATE_DIR_NAME"],
            "config_dir": os.environ["CONFIG_DIR_NAME"],
        },
        ensure_ascii=False,
    )
)
PY
        return
    fi

    printf 'App: %s\n' "$app_dir"
    printf 'Launcher: %s\n' "$launcher_path"
    printf 'Desktop: %s\n' "$desktop_path"
    printf 'Binários: %s\n' "$BIN_DIR"
    printf 'Ícones: %s\n' "$ICON_DIR"
    printf 'Cache: %s\n' "$CACHE_DIR"
    printf 'Estado/logs: %s\n' "$STATE_DIR"
    printf 'Config: %s\n' "$CONFIG_DIR"
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

    die "Pacote inválido: não encontrei o diretório LumaTools."
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

    if [ -d "$HOME/.var/app/com.valvesoftware.Steam/data/Steam" ] || [ -d "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam" ]; then
        STEAM_MODE="Flatpak"
        return
    fi

    if need_cmd snap && snap list steam >/dev/null 2>&1; then
        STEAM_MODE="Snap"
        return
    fi

    if [ -d "$HOME/snap/steam/common/.local/share/Steam" ] || [ -d "$HOME/snap/steam/common/.steam/steam" ]; then
        STEAM_MODE="Snap"
        return
    fi

    if [ -d "$HOME/.local/share/Steam" ] || [ -d "$HOME/.steam/steam" ] || [ -d "$HOME/.steam/root" ] || [ -d "$HOME/.steam/debian-installation" ] || need_cmd steam; then
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

ensure_runtime_dirs() {
    mkdir -p "$CACHE_DIR" "$STATE_DIR" "$CONFIG_DIR"
}

collect_missing_deps() {
    missing_deps=()

    if ! has_dotnet_9; then
        missing_deps+=("dotnet 9")
    fi

    if ! need_cmd 7z; then
        missing_deps+=("p7zip")
    fi

    if ! need_cmd unrar && ! need_cmd unar && ! need_cmd bsdtar; then
        missing_deps+=("unrar/unar/bsdtar")
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

    if ! need_cmd rclone && [ ! -f "$APP_SOURCE/tools/rclone/rclone" ]; then
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

run_self_test() {
    local app_dir="${DEST_DIR:-$HOME/.local/share/LumaTools}"
    local base_dir="$app_dir/squashfs-root"
    local failures=()

    if [ ! -d "$base_dir" ]; then
        failures+=("Instalação não encontrada em $base_dir")
    else
        bash -n "$app_dir/install.sh" >/dev/null 2>&1 || failures+=("install.sh inválido")
        bash -n "$base_dir/AppRun" >/dev/null 2>&1 || failures+=("AppRun inválido")
        bash -n "$base_dir/bin/run.sh" >/dev/null 2>&1 || failures+=("run.sh inválido")
        python3 -m compileall "$base_dir/bin/src" >/dev/null 2>&1 || failures+=("Python source não compila")
        if [ -x "$base_dir/bin/.venv/bin/python" ]; then
            "$base_dir/bin/.venv/bin/python" - <<'PY' >/dev/null 2>&1 || failures+=("Dependências Python principais falharam")
import importlib
for module in ("PyQt6", "requests", "bs4", "cachetools", "httpx", "ruamel.yaml"):
    importlib.import_module(module)
PY
        else
            failures+=(".venv ausente")
        fi
        if need_cmd desktop-file-validate && [ -f "$APPS_DIR/lumatools.desktop" ]; then
            desktop-file-validate "$APPS_DIR/lumatools.desktop" >/dev/null 2>&1 || failures+=(".desktop inválido")
        fi
    fi

    if [ "${#failures[@]}" -eq 0 ]; then
        printf 'SELF_TEST=OK\n'
        return 0
    fi

    printf 'SELF_TEST=FAIL\n'
    printf '%s\n' "${failures[@]}"
    return 1
}

run_doctor() {
    print_diagnostics
    printf '\n'
    print_paths
    printf '\n'
    run_self_test
}

repair_existing_lumatools_state() {
    if [ "$DRY_RUN" = true ]; then
        log "Dry-run: repararia appmanifests e sincronizaria AdditionalApps do SLSsteam."
        return
    fi

    local src_dir py_bin
    src_dir="$DEST_DIR/squashfs-root/bin/src"
    py_bin="$DEST_DIR/squashfs-root/bin/.venv/bin/python"
    if [ ! -x "$py_bin" ]; then
        py_bin="python3"
    fi

    if [ ! -d "$src_dir" ]; then
        warn "Fonte Python instalada não encontrada; pulando repair de Steam."
        return
    fi

    log "Reparando estado Steam dos jogos LumaTools..."
    if ! LUMATOOLS_SRC="$src_dir" "$py_bin" - <<'PY'
import logging
import os
import re
import sys
from pathlib import Path

src = os.environ["LUMATOOLS_SRC"]
sys.path.insert(0, src)

from core import steam_helpers
from utils.steam_manifest import (
    _is_lumatools_managed_game,
    _parse_acf_value,
    repair_lumatools_library_manifests,
)
from utils.yaml_config_manager import (
    _append_to_additional_apps,
    _atomic_write,
    _default_slssteam_config,
    _fix_additional_apps_indentation,
    _merge_duplicate_additional_apps,
    get_user_config_path,
)

logging.basicConfig(level=logging.INFO, format="[LumaTools repair] %(message)s")
logger = logging.getLogger("lumatools.repair")

libraries = steam_helpers.get_steam_libraries() or []
repair_result = repair_lumatools_library_manifests(libraries, logger=logger)

managed_apps: list[tuple[str, str]] = []
seen: set[str] = set()
for library in libraries:
    steamapps = Path(library).expanduser() / "steamapps"
    common = steamapps / "common"
    if not steamapps.is_dir():
        continue

    for acf_path in sorted(steamapps.glob("appmanifest_*.acf")):
        appid = acf_path.stem.replace("appmanifest_", "", 1)
        if not appid or appid in seen:
            continue
        try:
            content = acf_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        installdir = _parse_acf_value(content, "installdir")
        if not installdir:
            continue

        game_dir = common / installdir
        if not _is_lumatools_managed_game(game_dir):
            continue

        name = _parse_acf_value(content, "name") or installdir
        managed_apps.append((appid, name))
        seen.add(appid)

synced = 0
if managed_apps:
    config_path = get_user_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        content = config_path.read_text(encoding="utf-8", errors="ignore")
    else:
        content = _default_slssteam_config()

    content, _ = _fix_additional_apps_indentation(content)
    content, _ = _merge_duplicate_additional_apps(content)
    if not re.search(r"^AdditionalApps:\s*$", content, re.MULTILINE):
        content += "\nAdditionalApps:\n"

    for appid, name in managed_apps:
        match = re.search(r"^AdditionalApps:\s*$", content, re.MULTILINE)
        section_start = match.end() if match else len(content)
        next_key = re.compile(r"^[A-Za-z]", re.MULTILINE)
        next_match = next_key.search(content, section_start)
        section_end = next_match.start() if next_match else len(content)
        section = content[section_start:section_end]
        if re.search(rf"^\s*-\s*{re.escape(appid)}\b", section, re.MULTILINE):
            continue
        content = _append_to_additional_apps(content, appid, name, match)
        synced += 1

    if synced:
        _atomic_write(config_path, content)

print(
    "FIX_ALL_REPAIRED={repaired} FIX_ALL_FAILED={failed} ADDITIONAL_APPS_SYNCED={synced}".format(
        repaired=len(repair_result.get("repaired", [])),
        failed=len(repair_result.get("failed", [])),
        synced=synced,
    )
)
PY
    then
        warn "Repair de estado Steam falhou."
        return
    fi
}

show_dry_run_plan() {
    printf 'Dry-run LumaTools\n'
    printf 'Modo: %s\n' "$MODE"
    printf 'Origem: %s\n' "$APP_SOURCE"
    printf 'Destino: %s\n' "$DEST_DIR"
    printf 'Criaria/atualizaria:\n'
    printf ' - %s\n' "$DEST_DIR"
    if [ "$MODE" != "portable" ]; then
        printf ' - %s/lumatools\n' "$BIN_DIR"
        printf ' - %s/lumatools.desktop\n' "$APPS_DIR"
        printf ' - %s/lumatools.png\n' "$ICON_DIR"
    else
        printf ' - %s/lumatools-portable\n' "$DEST_DIR"
    fi
    printf ' - %s\n' "$CACHE_DIR"
    printf ' - %s\n' "$STATE_DIR"
    printf ' - .venv local do app\n'
    printf ' - SLSsteam (se Steam detectada)\n'
}

download_to_file() {
    local url="$1"
    local target="$2"

    mkdir -p "$(dirname "$target")"
    if need_cmd curl; then
        curl -fL --retry 3 -C - "$url" -o "$target"
        return
    fi
    if need_cmd wget; then
        wget -c -O "$target" "$url"
        return
    fi
    die "Nem curl nem wget estão disponíveis."
}

ensure_local_bin_in_path() {
    if printf '%s' ":$PATH:" | grep -q ":$BIN_DIR:"; then
        return
    fi

    warn "$BIN_DIR não está no PATH atual. Vou adicionar para shells comuns."
    local export_line='export PATH="$HOME/.local/bin:$PATH"'
    local shell_file=""
    for shell_file in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
        touch "$shell_file"
        if ! grep -Fq "$export_line" "$shell_file"; then
            printf '\n%s\n' "$export_line" >> "$shell_file"
        fi
    done

    export PATH="$BIN_DIR:$PATH"
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
            DEST_DIR="$HOME/Applications/LumaTools-Portable"
        fi
    else
        DEST_DIR="$HOME/.local/share/LumaTools"
    fi
}

write_runtime_wrapper() {
    if [ "$DRY_RUN" = true ]; then
        return
    fi

    cat > "$DEST_DIR/LumaTools.AppImage" <<'SH'
#!/usr/bin/env bash
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec -a lumatools "$HERE/squashfs-root/AppRun" "$@"
SH
    chmod +x "$DEST_DIR/LumaTools.AppImage"
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

write_version_metadata() {
    VERSION_TARGET="$DEST_DIR/VERSION.json" \
    VERSION_LABEL="${SOURCE_VERSION:-unknown}" \
    REVISION_LABEL="${SOURCE_REVISION:-}" \
    python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

target = Path(os.environ["VERSION_TARGET"])
payload = {
    "version": os.environ.get("VERSION_LABEL", "unknown"),
    "commit_sha": os.environ.get("REVISION_LABEL", ""),
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
}
target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

sync_tree() {
    if [ "$DRY_RUN" = true ]; then
        show_dry_run_plan
        return
    fi

    mkdir -p "$DEST_DIR"

    if [ "$MODE" != "portable" ]; then
        create_backup
    fi

    rsync -a --delete --exclude '.venv' "$APP_SOURCE/squashfs-root/" "$DEST_DIR/squashfs-root/"
    rsync -a --delete "$APP_SOURCE/tools/" "$DEST_DIR/tools/"
    if [ -f "$DEST_DIR/tools/rclone/rclone" ]; then
        chmod +x "$DEST_DIR/tools/rclone/rclone" || true
    fi

    if [ -d "$ROOT_DIR/release" ]; then
        rsync -a --delete "$ROOT_DIR/release/" "$DEST_DIR/release/"
    fi

    install -Dm644 "$APP_SOURCE/.version" "$DEST_DIR/.version"
    install -Dm755 "$ROOT_DIR/install.sh" "$DEST_DIR/install.sh"

    write_runtime_wrapper

    if [ -z "$SOURCE_REVISION" ] && [ -d "$ROOT_DIR/.git" ]; then
        SOURCE_REVISION="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || true)"
        if [ -n "$SOURCE_REVISION" ] && {
            ! git -C "$ROOT_DIR" diff --quiet --ignore-submodules -- 2>/dev/null \
            || ! git -C "$ROOT_DIR" diff --cached --quiet --ignore-submodules -- 2>/dev/null;
        }; then
            SOURCE_REVISION="local-${SOURCE_REVISION}-dirty"
        fi
    fi

    if [ -z "$SOURCE_VERSION" ] && [ -n "$SOURCE_REVISION" ]; then
        if printf '%s' "$SOURCE_REVISION" | grep -q '^local-'; then
            SOURCE_VERSION="local-$(printf '%s' "$SOURCE_REVISION" | sed -E 's/^local-([0-9a-f]+).*$/\1/' | cut -c1-8)-dirty"
        else
            SOURCE_VERSION="main-$(printf '%s' "$SOURCE_REVISION" | cut -c1-8)"
        fi
    fi

    if [ -z "$SOURCE_REVISION" ] && [ -f "$ROOT_DIR/release/latest.json" ]; then
        SOURCE_REVISION="$(python3 - "$ROOT_DIR/release/latest.json" <<'PY'
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(str(payload.get("commit_sha", "")).strip())
except Exception:
    print("")
PY
)"
    fi

    if [ -z "$SOURCE_VERSION" ] && [ -f "$ROOT_DIR/release/latest.json" ]; then
        SOURCE_VERSION="$(python3 - "$ROOT_DIR/release/latest.json" <<'PY'
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(str(payload.get("version", "")).strip())
except Exception:
    print("")
PY
)"
    fi

    if [ -n "$SOURCE_REVISION" ]; then
        printf '%s\n' "$SOURCE_REVISION" > "$DEST_DIR/.repo_revision"
    fi

    if [ -n "$SOURCE_VERSION" ]; then
        printf '%s\n' "$SOURCE_VERSION" > "$DEST_DIR/.version"
        printf '%s\n' "$SOURCE_VERSION" > "$DEST_DIR/squashfs-root/bin/src/res/version"
    fi

    write_version_metadata

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

    if [ "$DRY_RUN" = true ]; then
        log "Dry-run: instalaria .NET 9 em $HOME/.dotnet"
        return
    fi

    local tmp_dir install_script
    tmp_dir="$(mktemp -d)"
    install_script="$tmp_dir/dotnet-install.sh"
    mkdir -p "$HOME/.dotnet"

    log "Instalando .NET 9 em $HOME/.dotnet ..."
    download_to_file "https://dot.net/v1/dotnet-install.sh" "$install_script"

    chmod +x "$install_script"
    DOTNET_ROOT="$HOME/.dotnet" bash "$install_script" --channel 9.0 --runtime dotnet
}

install_system_packages() {
    local packages=()

    if [ "$USER_ONLY" = true ]; then
        warn "Modo user-only ativo: pulando instalação de pacotes do sistema."
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        log "Dry-run: pularia a instalação de pacotes do sistema."
        return
    fi

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
                unrar
                unarchiver
                libarchive
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
                unar
                libarchive-tools
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
                unrar
                unar
                libarchive
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
                unar
                libarchive-tools
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
                app-arch/unrar
                app-arch/libarchive
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

install_slscheevo() {
    if [ "$DRY_RUN" = true ]; then
        log "Dry-run: verificaria/instalaria o SLScheevo."
        return
    fi

    local target_dir target_bin release_json asset_url tmp_dir archive
    target_dir="$DEST_DIR/squashfs-root/bin/src/deps/SLScheevo"
    target_bin="$target_dir/SLScheevo"

    if [ -x "$target_bin" ]; then
        log "SLScheevo já está instalado."
        return
    fi

    tmp_dir="$(mktemp -d)"
    release_json="$tmp_dir/slscheevo-release.json"
    archive="$tmp_dir/SLScheevo-Linux.tar.gz"

    log "Baixando SLScheevo oficial..."
    if need_cmd curl; then
        curl -fsSL \
            "https://api.github.com/repos/xamionex/SLScheevo/releases/latest" \
            -H "Accept: application/vnd.github+json" \
            -H "User-Agent: LumaTools" \
            -o "$release_json"
    elif need_cmd wget; then
        wget -qO "$release_json" \
            --header="Accept: application/vnd.github+json" \
            --header="User-Agent: LumaTools" \
            "https://api.github.com/repos/xamionex/SLScheevo/releases/latest"
    else
        warn "Nem curl nem wget disponíveis para baixar SLScheevo."
        return 1
    fi

    asset_url="$(python3 - "$release_json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    release = json.load(handle)

for asset in release.get("assets", []):
    if asset.get("name") == "SLScheevo-Linux.tar.gz":
        print(asset["browser_download_url"])
        raise SystemExit(0)

raise SystemExit(1)
PY
)"

    download_to_file "$asset_url" "$archive"
    mkdir -p "$target_dir"
    tar -xzf "$archive" -C "$tmp_dir"
    install -m 755 "$tmp_dir/SLScheevo-Linux" "$target_bin"
    log "SLScheevo instalado em $target_bin."
}

setup_python_env() {
    local venv_dir="$DEST_DIR/squashfs-root/bin/.venv"
    local req_file="$DEST_DIR/squashfs-root/bin/requirements.txt"
    local hash_file="$DEST_DIR/.requirements.sha256"
    local req_hash=""

    if ! need_cmd python3; then
        die "python3 não encontrado."
    fi

    if [ "$DRY_RUN" = true ]; then
        log "Dry-run: prepararia/reutilizaria o ambiente Python em $venv_dir"
        return
    fi

    req_hash="$(sha256sum "$req_file" | awk '{print $1}')"
    if [ -x "$venv_dir/bin/python" ] \
        && [ -f "$hash_file" ] \
        && [ "$(cat "$hash_file")" = "$req_hash" ]; then
        if "$venv_dir/bin/python" - <<'PY' >/dev/null 2>&1
import importlib
for module in ("PyQt6", "requests", "bs4", "cachetools"):
    importlib.import_module(module)
PY
        then
            log "Ambiente Python já está íntegro; reutilizando .venv."
            return
        fi
        warn "A .venv existe, mas falhou na validação. Vou recriá-la."
    fi

    rm -rf "$venv_dir"
    mkdir -p "$CACHE_DIR/pip"

    log "Preparando ambiente Python..."
    python3 -m venv "$venv_dir"
    PIP_CACHE_DIR="$CACHE_DIR/pip" "$venv_dir/bin/pip" install --upgrade pip setuptools wheel
    PIP_CACHE_DIR="$CACHE_DIR/pip" "$venv_dir/bin/pip" install -r "$req_file"
    printf '%s\n' "$req_hash" > "$hash_file"
}

install_slssteam() {
    if [ "$MODE" = "portable" ] && [ "$STEAM_MODE" = "Ausente" ]; then
        warn "Steam não detectada; pulando SLSsteam no modo portátil."
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        log "Dry-run: verificaria/instalaria o SLSsteam."
        return
    fi

    local tmp_dir archive release_json asset_url latest_version setup_script setup_mode
    local version_file="$HOME/.local/share/SLSsteam/VERSION"

    if [ "$STEAM_MODE" = "Flatpak" ]; then
        setup_mode="flatpak-install"
        version_file="$HOME/.var/app/com.valvesoftware.Steam/.local/share/SLSsteam/VERSION"
    else
        setup_mode="install"
    fi

    tmp_dir="$(mktemp -d)"
    archive="$tmp_dir/SLSsteam-Any.7z"
    release_json="$tmp_dir/release.json"

    log "Baixando SLSsteam oficial..."
    if need_cmd curl; then
        curl -fsSL \
            "https://api.github.com/repos/AceSLS/SLSsteam/releases/latest" \
            -H "Accept: application/vnd.github+json" \
            -H "User-Agent: LumaTools" \
            -o "$release_json"
    elif need_cmd wget; then
        wget -qO "$release_json" \
            --header="Accept: application/vnd.github+json" \
            --header="User-Agent: LumaTools" \
            "https://api.github.com/repos/AceSLS/SLSsteam/releases/latest"
    else
        die "Nem curl nem wget estão disponíveis para baixar o SLSsteam."
    fi

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

    if [ -n "$latest_version" ] && [ -f "$version_file" ] && [ "$(cat "$version_file")" = "$latest_version" ]; then
        log "SLSsteam já está atualizado em $latest_version."
        return
    fi

    download_to_file "$asset_url" "$archive"
    mkdir -p "$tmp_dir/extract"
    7z x "$archive" "-o$tmp_dir/extract" -y >/dev/null

    if [ -f "$tmp_dir/extract/setup.sh" ]; then
        chmod +x "$tmp_dir/extract/setup.sh"
        (
            cd "$tmp_dir/extract"
            bash "./setup.sh" "$setup_mode"
        )
    else
        setup_script="$tmp_dir/setup.sh"
        curl -fsSL \
            "https://raw.githubusercontent.com/AceSLS/SLSsteam/main/setup.sh" \
            -o "$setup_script"
        chmod +x "$setup_script"
        (
            cd "$tmp_dir/extract"
            bash "$setup_script" "$setup_mode"
        )
    fi

    if [ -n "$latest_version" ]; then
        mkdir -p "$(dirname "$version_file")"
        printf '%s\n' "$latest_version" > "$version_file"
    fi
}

install_launchers() {
    if [ "$MODE" = "portable" ]; then
        cat > "$DEST_DIR/lumatools-portable" <<'SH'
#!/usr/bin/env bash
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec -a lumatools "$HERE/squashfs-root/AppRun" "$@"
SH
        chmod +x "$DEST_DIR/lumatools-portable"
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        log "Dry-run: instalaria launchers globais em $BIN_DIR"
        return
    fi

    log "Instalando launchers..."
    mkdir -p "$BIN_DIR"

    cat > "$BIN_DIR/lumatools" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$HOME/.local/share/LumaTools"
INSTALLER="$APP_DIR/install.sh"
APP_RUN="$APP_DIR/squashfs-root/AppRun"

case "${1:-}" in
    --doctor|--self-test|--paths|--diagnose|--json|--dry-run)
        exec "$INSTALLER" "$@"
        ;;
    --fix-all)
        exec "$INSTALLER" --fix-all
        ;;
    --repair)
        exec "$INSTALLER" --repair --no-prompt
        ;;
esac

exec -a lumatools "$APP_RUN" "$@"
SH
    chmod +x "$BIN_DIR/lumatools"

    python3 - "$BIN_DIR" <<'PY'
import itertools
import pathlib
import sys

bin_dir = pathlib.Path(sys.argv[1])
target = bin_dir / "lumatools"
name = "lumatools"
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

portable_name = bin_dir / "lumatools-linux"
if portable_name.exists() or portable_name.is_symlink():
    portable_name.unlink()
portable_name.symlink_to(target.name)
PY
}

install_desktop_entry() {
    if [ "$MODE" = "portable" ]; then
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        log "Dry-run: instalaria o atalho .desktop e o ícone."
        return
    fi

    log "Instalando atalhos..."
    mkdir -p "$APPS_DIR" "$ICON_DIR"

    if [ -L "$APPS_DIR/lumatools.desktop" ]; then
        rm -f "$APPS_DIR/lumatools.desktop"
    fi

    install -Dm644 \
        "$DEST_DIR/squashfs-root/bin/src/res/logo/icon.png" \
        "$ICON_DIR/lumatools.png"

    cat > "$APPS_DIR/lumatools.desktop.tmp" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=LumaTools
Comment=Launcher LumaTools universal para Linux
Exec=$BIN_DIR/lumatools
Icon=lumatools
Terminal=false
Categories=Game;
StartupNotify=true
StartupWMClass=lumatools
X-GNOME-SingleWindow=true
MimeType=x-scheme-handler/lumatools;
EOF
    mv "$APPS_DIR/lumatools.desktop.tmp" "$APPS_DIR/lumatools.desktop"

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
    install_slscheevo || warn "Falha ao instalar SLScheevo automaticamente."
    install_launchers
    install_desktop_entry
    write_runtime_wrapper
    if [ "$MODE" != "portable" ] && [ "$DRY_RUN" != true ]; then
        ensure_local_bin_in_path
    fi

    if [ "$FIX_ALL" = true ] && [ "$DRY_RUN" != true ]; then
        repair_existing_lumatools_state
        run_self_test
    fi
}

main() {
    resolve_app_source
    ensure_runtime_dirs
    detect_os
    detect_steam_mode
    detect_gpu
    detect_recommended_mode
    collect_missing_deps

    if [ "$DIAGNOSE" = true ]; then
        print_diagnostics
        exit 0
    fi

    if [ "$PATHS_ONLY" = true ]; then
        print_paths
        exit 0
    fi

    if [ "$DOCTOR" = true ] || [ "$SELF_TEST" = true ]; then
        MODE="${MODE:-install}"
        resolve_dest_dir
        if [ "$DOCTOR" = true ]; then
            run_doctor
            exit $?
        fi
        run_self_test
        exit $?
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
        log "Abra com: $DEST_DIR/lumatools-portable"
    else
        log "Instalação concluída."
        log "Abra com: lumatools"
    fi
}

main "$@"
