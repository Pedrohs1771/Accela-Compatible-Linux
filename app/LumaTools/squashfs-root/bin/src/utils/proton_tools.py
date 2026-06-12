import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core import steam_helpers

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProtonTool:
    internal_name: str
    display_name: str
    install_path: str
    source: str
    priority: int


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _parse_vdf_value(text: str, key: str) -> Optional[str]:
    match = re.search(rf'"{re.escape(key)}"\s*"([^"]+)"', text)
    if match:
        return match.group(1).strip()
    return None


def _get_steam_root() -> Optional[Path]:
    steam_path = steam_helpers.find_steam_install()
    if not steam_path:
        return None
    return Path(steam_path).expanduser().resolve()


def _get_library_paths() -> List[Path]:
    libraries = []
    for path in steam_helpers.get_steam_libraries():
        try:
            libraries.append(Path(path).expanduser().resolve())
        except OSError:
            continue
    return libraries


def _priority_for_official_name(internal_name: str) -> int:
    if internal_name == "proton_experimental":
        return 0
    if internal_name == "proton_hotfix":
        return 1
    version_match = re.fullmatch(r"proton_(\d+)", internal_name)
    if version_match:
        version = int(version_match.group(1))
        return 100 - version
    return 200


def _infer_official_tool_name(folder_name: str) -> Optional[str]:
    folder_name = folder_name.strip()
    lowered = folder_name.lower()

    if folder_name == "Proton - Experimental":
        return "proton_experimental"
    if folder_name == "Proton Hotfix":
        return "proton_hotfix"

    version_match = re.match(r"^Proton\s+(\d+)(?:\.\d+)?", folder_name)
    if version_match:
        return f"proton_{version_match.group(1)}"

    if lowered.startswith("proton"):
        normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
        return normalized or None

    return None


def _discover_official_protons(library_paths: Sequence[Path]) -> List[ProtonTool]:
    tools: List[ProtonTool] = []
    seen: set[str] = set()

    for library_path in library_paths:
        common_dir = library_path / "steamapps" / "common"
        if not common_dir.is_dir():
            continue

        try:
            entries = sorted(common_dir.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue

        for entry in entries:
            if not entry.is_dir():
                continue

            manifest_path = entry / "toolmanifest.vdf"
            if not manifest_path.is_file():
                continue

            manifest_text = _read_text(manifest_path)
            if not manifest_text:
                continue

            layer_name = (_parse_vdf_value(manifest_text, "compatmanager_layer_name") or "").strip()
            if layer_name != "proton":
                continue

            internal_name = _infer_official_tool_name(entry.name)
            if not internal_name or internal_name in seen:
                continue

            seen.add(internal_name)
            tools.append(
                ProtonTool(
                    internal_name=internal_name,
                    display_name=entry.name,
                    install_path=str(entry),
                    source="official",
                    priority=_priority_for_official_name(internal_name),
                )
            )

    return tools


def _extract_custom_tool_block(vdf_text: str) -> Optional[Tuple[str, str]]:
    block_match = re.search(
        r'"compat_tools"\s*\{\s*"([^"]+)"\s*\{(.*?)\}\s*\}',
        vdf_text,
        re.DOTALL,
    )
    if not block_match:
        return None

    internal_name = block_match.group(1).strip()
    block_body = block_match.group(2)
    display_name = _parse_vdf_value(block_body, "display_name") or internal_name
    return internal_name, display_name


def _discover_custom_protons(steam_root: Optional[Path]) -> List[ProtonTool]:
    if steam_root is None:
        return []

    compat_dir = steam_root / "compatibilitytools.d"
    if not compat_dir.is_dir():
        return []

    tools: List[ProtonTool] = []
    seen: set[str] = set()

    try:
        entries = sorted(compat_dir.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return []

    for entry in entries:
        if not entry.is_dir():
            continue

        compat_vdf = entry / "compatibilitytool.vdf"
        tool_manifest = entry / "toolmanifest.vdf"
        if not compat_vdf.is_file() and not tool_manifest.is_file():
            continue

        internal_name = entry.name
        display_name = entry.name

        if compat_vdf.is_file():
            compat_text = _read_text(compat_vdf)
            parsed = _extract_custom_tool_block(compat_text)
            if parsed:
                internal_name, display_name = parsed

        if internal_name in seen:
            continue

        seen.add(internal_name)
        tools.append(
            ProtonTool(
                internal_name=internal_name,
                display_name=display_name,
                install_path=str(entry),
                source="custom",
                priority=300,
            )
        )

    return tools


def discover_proton_tools() -> List[ProtonTool]:
    steam_root = _get_steam_root()
    library_paths = _get_library_paths()

    tools = _discover_official_protons(library_paths)
    tools.extend(_discover_custom_protons(steam_root))
    deduped: Dict[str, ProtonTool] = {}

    for tool in sorted(tools, key=lambda item: (item.priority, item.display_name.lower())):
        deduped.setdefault(tool.internal_name, tool)

    return list(deduped.values())


def choose_default_proton_tool(tools: Optional[Sequence[ProtonTool]] = None) -> Optional[ProtonTool]:
    available = list(tools) if tools is not None else discover_proton_tools()
    if not available:
        return None
    return sorted(available, key=lambda item: (item.priority, item.display_name.lower()))[0]


def depot_selection_requires_proton(
    selected_depots: Iterable[Any], all_depots: Dict[str, Any]
) -> bool:
    if sys.platform != "linux":
        return False

    has_windows = False
    has_linux = False

    for depot_id in selected_depots:
        depot_info = all_depots.get(str(depot_id), {})
        platform = str(depot_info.get("oslist") or "").strip().lower()
        if platform == "windows":
            has_windows = True
        elif platform == "linux":
            has_linux = True

    return has_windows and not has_linux


def build_default_proton_selection(
    selected_depots: Iterable[Any], all_depots: Dict[str, Any]
) -> Dict[str, Any]:
    requires_proton = depot_selection_requires_proton(selected_depots, all_depots)
    default_tool = choose_default_proton_tool() if requires_proton else None
    return {
        "force_proton": bool(requires_proton and default_tool),
        "proton_tool_name": default_tool.internal_name if default_tool else "",
        "proton_tool_display_name": default_tool.display_name if default_tool else "",
    }


def _find_named_block_span(content: str, key: str, start_pos: int = 0) -> Optional[Tuple[int, int]]:
    pattern = re.compile(rf'^(?P<indent>\s*)"{re.escape(key)}"\s*$', re.MULTILINE)
    match = pattern.search(content, start_pos)
    if not match:
        return None

    brace_start = content.find("{", match.end())
    if brace_start == -1:
        return None

    depth = 0
    for index in range(brace_start, len(content)):
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return match.start(), index + 1
    return None


def _ensure_compat_mapping_section(content: str) -> Tuple[str, Tuple[int, int]]:
    compat_span = _find_named_block_span(content, "CompatToolMapping")
    if compat_span:
        return content, compat_span

    steam_span = _find_named_block_span(content, "Steam")
    if not steam_span:
        raise ValueError("CompatToolMapping block and Steam block were not found in config.vdf")

    steam_block_start, steam_block_end = steam_span
    steam_block = content[steam_block_start:steam_block_end]
    steam_indent_match = re.match(r'(?P<indent>\s*)"Steam"\s*', steam_block)
    steam_indent = steam_indent_match.group("indent") if steam_indent_match else ""

    insertion = (
        f'\n{steam_indent}\t"CompatToolMapping"\n'
        f"{steam_indent}\t{{\n"
        f"{steam_indent}\t}}"
    )
    insert_at = steam_block_end - 1
    updated = content[:insert_at] + insertion + content[insert_at:]
    new_span = _find_named_block_span(updated, "CompatToolMapping")
    if not new_span:
        raise ValueError("Failed to create CompatToolMapping block in config.vdf")
    return updated, new_span


def _upsert_compat_tool_mapping(
    content: str, appid: str, tool_name: str
) -> str:
    content, compat_span = _ensure_compat_mapping_section(content)
    compat_start, compat_end = compat_span
    compat_block = content[compat_start:compat_end]
    section_indent_match = re.match(r'(?P<indent>\s*)"CompatToolMapping"\s*', compat_block)
    section_indent = section_indent_match.group("indent") if section_indent_match else ""

    existing_span = _find_named_block_span(compat_block, appid)
    entry_text = (
        f'\n{section_indent}\t"{appid}"\n'
        f"{section_indent}\t{{\n"
        f'{section_indent}\t\t"name"\t\t"{tool_name}"\n'
        f'{section_indent}\t\t"config"\t\t""\n'
        f'{section_indent}\t\t"priority"\t\t"250"\n'
        f"{section_indent}\t}}"
    )

    if existing_span:
        local_start, local_end = existing_span
        compat_block = compat_block[:local_start] + entry_text + compat_block[local_end:]
    else:
        insert_at = compat_block.rfind("}")
        compat_block = compat_block[:insert_at] + entry_text + "\n" + compat_block[insert_at:]

    return content[:compat_start] + compat_block + content[compat_end:]


def _remove_compat_tool_mapping(content: str, appid: str, _tool_name: str = "") -> str:
    compat_span = _find_named_block_span(content, "CompatToolMapping")
    if not compat_span:
        return content

    compat_start, compat_end = compat_span
    compat_block = content[compat_start:compat_end]
    existing_span = _find_named_block_span(compat_block, appid)
    if not existing_span:
        return content

    local_start, local_end = existing_span
    block_before = compat_block[:local_start].rstrip("\n")
    block_after = compat_block[local_end:]
    if block_after.startswith("\n"):
        block_after = block_after[1:]
    compat_block = block_before + ("\n" if block_after else "") + block_after
    return content[:compat_start] + compat_block + content[compat_end:]


def _write_steam_config(transformer, appid: str, tool_name: str = "") -> bool:
    steam_root = _get_steam_root()
    if steam_root is None:
        logger.warning("Steam root not found; skipping Proton compatibility mapping")
        return False

    config_path = steam_root / "config" / "config.vdf"
    if not config_path.is_file():
        logger.warning(f"Steam config.vdf not found at {config_path}")
        return False

    appid_str = str(appid or "").strip()
    tool_name = str(tool_name or "").strip()
    if not appid_str:
        return False

    try:
        original = _read_text(config_path)
        if not original:
            logger.warning(f"Steam config.vdf is empty or unreadable at {config_path}")
            return False

        updated = transformer(original, appid_str, tool_name)
        if updated == original:
            logger.info(f"Steam CompatToolMapping already up to date for AppID {appid_str}")
            return True

        temp_path = config_path.with_suffix(".vdf.tmp")
        temp_path.write_text(updated, encoding="utf-8")
        os.replace(temp_path, config_path)
        return True
    except (OSError, ValueError) as exc:
        logger.error(f"Failed to update Steam CompatToolMapping: {exc}", exc_info=True)
        return False


def apply_steam_compat_tool(appid: Any, tool_name: str) -> bool:
    tool_name = str(tool_name or "").strip()
    if not tool_name:
        return False

    ok = _write_steam_config(_upsert_compat_tool_mapping, str(appid), tool_name)
    if ok:
        logger.info(
            f"Configured Steam compatibility tool '{tool_name}' for AppID {appid}"
        )
    return ok


def clear_steam_compat_tool(appid: Any) -> bool:
    ok = _write_steam_config(_remove_compat_tool_mapping, str(appid))
    if ok:
        logger.info(f"Cleared Steam compatibility tool override for AppID {appid}")
    return ok
