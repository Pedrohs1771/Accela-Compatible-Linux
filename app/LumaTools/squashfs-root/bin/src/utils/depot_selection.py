import re
from typing import Any, Dict, Iterable


def platform_family(os_value: Any) -> str:
    value = str(os_value or "").strip().lower()
    if "windows" in value or value in {"win", "win32", "win64"}:
        return "windows"
    if "linux" in value or "steamos" in value:
        return "linux"
    if "mac" in value or "osx" in value:
        return "macos"
    return ""


def extract_base_depot_ids(lua_content: str) -> list[str]:
    section_match = re.search(
        r"--\s*MAIN APP DEPOTS(?P<body>.*?)(?:--\s*SHARED DEPOTS|--\s*DLCS|\Z)",
        lua_content,
        re.IGNORECASE | re.DOTALL,
    )
    if not section_match:
        return []
    return [
        match.group(1)
        for match in re.finditer(
            r"addappid\(\s*(\d+)\s*,\s*1\s*,\s*\"[^\"]+\"\s*\)",
            section_match.group("body"),
            re.IGNORECASE,
        )
    ]


def complete_base_depot_selection(
    selected_depots: Iterable[Any],
    all_depots: Dict[str, Any],
    base_depot_ids: Iterable[Any],
) -> list[str]:
    selected = [str(depot_id) for depot_id in selected_depots]
    selected_set = set(selected)
    base_ids = [str(depot_id) for depot_id in base_depot_ids]
    selected_platforms = {
        platform_family((all_depots.get(depot_id) or {}).get("oslist"))
        for depot_id in base_ids
        if depot_id in selected_set
    }
    selected_platforms.discard("")
    if not selected_platforms:
        return selected

    for depot_id in base_ids:
        family = platform_family((all_depots.get(depot_id) or {}).get("oslist"))
        if family not in selected_platforms or depot_id in selected_set:
            continue
        selected.append(depot_id)
        selected_set.add(depot_id)
    return selected
