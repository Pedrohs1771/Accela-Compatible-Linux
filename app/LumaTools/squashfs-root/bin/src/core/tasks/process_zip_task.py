import zipfile
import re
import os
import sys
import logging
import tempfile
import threading

from ui.assets import DEPOT_BLACKLIST
from core.steam_api import get_depot_info_from_api
from core.ini_parser import parse_depots_ini
from utils.yaml_config_manager import (
    get_user_config_path,
    ensure_slssteam_config,
    add_app_token,
    is_slssteam_mode_enabled,
)
from core.appinfo_editor import get_appinfo_path, add_token_to_appinfo

logger = logging.getLogger(__name__)


class ProcessZipTask:
    API_ENRICH_TIMEOUT_SECONDS = 8

    def __init__(self):
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def _cancelled_result(self):
        return {"cancelled": True}

    def _ensure_not_stopped(self):
        if self._stop_requested:
            logger.info("Zip processing stop requested; aborting current task.")
            return False
        return True

    def _fetch_depot_info_with_timeout(self, app_id, access_token=None):
        result_holder = {"data": {}, "error": None}

        def worker():
            try:
                result_holder["data"] = get_depot_info_from_api(app_id, access_token)
            except Exception as exc:
                result_holder["error"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        deadline = threading.Event()
        deadline_wait = 0.1
        remaining = float(self.API_ENRICH_TIMEOUT_SECONDS)
        while thread.is_alive() and remaining > 0:
            if not self._ensure_not_stopped():
                logger.info("Skipping Steam API enrichment due to shutdown/cancel.")
                return {}
            deadline.wait(min(deadline_wait, remaining))
            remaining -= deadline_wait

        if thread.is_alive():
            logger.warning(
                "Steam API enrichment timed out after %ss for AppID %s; continuing with LUA data only.",
                self.API_ENRICH_TIMEOUT_SECONDS,
                app_id,
            )
            return {}

        if result_holder["error"] is not None:
            logger.warning(
                "Steam API enrichment failed for AppID %s: %s",
                app_id,
                result_holder["error"],
            )
            return {}

        return result_holder["data"] or {}

    @staticmethod
    def _parse_lua(content, game_data):
        logger.debug("Starting LUA content parsing...")
        game_data.setdefault("manifest_sizes", {})

        try:
            all_app_matches = list(
                re.finditer(r"addappid\((.*?)\)(.*)", content, re.IGNORECASE)
            )
            if not all_app_matches:
                raise ValueError("LUA file is invalid; no 'addappid' entries found.")

            first_app_match = all_app_matches.pop(0)
            first_app_args = first_app_match.group(1).strip()

            # Explicitly break down operation to help static analysis
            args_list = first_app_args.split(",")
            app_id_val = args_list[0]
            game_data["appid"] = app_id_val.strip()

            comment_part = first_app_match.group(2)
            game_name_match = re.search(r"--\s*(.*)", comment_part)
            game_data["game_name"] = (
                game_name_match.group(1).strip() if game_name_match else None
            )

            game_data["depots"] = {}
            game_data["dlcs"] = {}
            for match in all_app_matches:
                args_str = match.group(1).strip()
                args = [arg.strip() for arg in args_str.split(",")]
                app_id = args[0]

                comment_part = match.group(2)
                desc_match = re.search(r"--\s*(.*)", comment_part)
                desc = desc_match.group(1).strip() if desc_match else f"Depot {app_id}"

                if len(args) > 2 and args[2].strip('"'):
                    depot_key = args[2].strip('"')
                    game_data["depots"][app_id] = {"key": depot_key, "desc": desc}
                else:
                    game_data["dlcs"][app_id] = desc

            manifest_size_matches = list(
                re.finditer(
                    r'setManifestid\(\s*(\d+)\s*,\s*".*?"\s*,\s*(\d+)\s*\)',
                    content,
                    re.IGNORECASE,
                )
            )
            for match in manifest_size_matches:
                depot_id = match.group(1).strip()
                size_bytes = match.group(2).strip()
                game_data["manifest_sizes"][depot_id] = size_bytes
                logger.debug(
                    f"Found LUA manifest size for Depot {depot_id}: {size_bytes} bytes"
                )

        except Exception as e:
            logger.error(f"Critical error during LUA parsing: {e}", exc_info=True)
            raise

    @staticmethod
    def _extract_app_token(lua_content: str, app_id: str) -> str | None:
        if not app_id:
            logger.debug("No app_id provided, skipping token extraction")
            return None

        try:
            # Extract token from LUA content
            # Pattern: addtoken(<app_id>, "<token>") with optional whitespace
            token_pattern = r'addtoken\s*\(\s*\d+\s*,\s*"([^"]+)"\s*\)'
            match = re.search(token_pattern, lua_content, re.IGNORECASE)

            if not match:
                logger.debug(f"No addtoken pattern found for AppID {app_id}")
                return None

            app_token = match.group(1)
            logger.info(f"Found token for AppID {app_id}: {app_token[:10]}...")

            if is_slssteam_mode_enabled():
                if sys.platform == "win32":
                    # Windows: Add token to Steam's appinfo.vdf
                    appinfo_path = get_appinfo_path()

                    if not appinfo_path:
                        logger.warning(
                            "Could not find Steam appinfo.vdf, skipping token addition"
                        )
                        return app_token

                    success = add_token_to_appinfo(appinfo_path, app_id, app_token)

                    if success:
                        logger.info(
                            f"Successfully added token for AppID {app_id} to Steam appinfo.vdf"
                        )

                    return app_token
                else:
                    # Linux: Add token to SLSsteam config.yaml
                    config_path = get_user_config_path()

                    if not ensure_slssteam_config(config_path):
                        logger.warning(f"SLSsteam config not available at {config_path}")
                        return app_token

                    success = add_app_token(config_path, app_id, app_token)

                    if success:
                        logger.info(
                            f"Successfully added token for AppID {app_id} to SLSsteam config"
                        )

                    return app_token
            return app_token

        except Exception as e:
            logger.error(f"Failed to extract/configure app token: {e}", exc_info=True)
            return None

    def run(self, zip_path):
        logger.info(f"Starting zip processing task for: {zip_path}")

        if not self._ensure_not_stopped():
            return self._cancelled_result()

        try:
            known_depot_descriptions = parse_depots_ini()
            logger.info(
                f"Successfully loaded {len(known_depot_descriptions)} depot descriptions from .ini."
            )
        except Exception as e:
            logger.error(f"Failed to load depots.ini: {e}", exc_info=True)
            known_depot_descriptions = {}

        game_data = {}
        try:
            if not self._ensure_not_stopped():
                return self._cancelled_result()

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                lua_files = [f for f in zip_ref.namelist() if f.endswith(".lua")]
                if not lua_files:
                    raise FileNotFoundError("No .lua file found in the zip archive.")

                if not self._ensure_not_stopped():
                    return self._cancelled_result()

                manifest_files = {
                    os.path.basename(f): zip_ref.read(f)
                    for f in zip_ref.namelist()
                    if f.endswith(".manifest")
                }
                for depot_id_manifest in manifest_files:
                    parts = depot_id_manifest.replace(".manifest", "").split("_")
                    if len(parts) == 2:
                        game_data.setdefault("manifests", {})[parts[0]] = parts[1]

                lua_content = zip_ref.read(lua_files[0]).decode("utf-8")

                if not self._ensure_not_stopped():
                    return self._cancelled_result()

                self._parse_lua(lua_content, game_data)

                if not self._ensure_not_stopped():
                    return self._cancelled_result()

                token = self._extract_app_token(lua_content, game_data.get("appid"))
                if token:
                    game_data["app_token"] = token

                if game_data.get("dlcs"):
                    enriched_dlcs = {}
                    for dlc_id, lua_desc in game_data["dlcs"].items():
                        enriched_dlcs[dlc_id] = known_depot_descriptions.get(
                            dlc_id, lua_desc
                        )
                    game_data["dlcs"] = enriched_dlcs

                unfiltered_depots = game_data.get("depots", {})
                if not unfiltered_depots:
                    logger.warning("LUA parsing did not identify any depots with keys.")
                else:
                    logger.info(
                        f"LUA parsing found {len(unfiltered_depots)} depots before filtering."
                    )

                    string_blacklist = {str(item) for item in DEPOT_BLACKLIST}
                    filtered_depots = {
                        depot_id: data
                        for depot_id, data in unfiltered_depots.items()
                        if depot_id not in string_blacklist
                    }
                    if len(unfiltered_depots) > len(filtered_depots):
                        logger.info(
                            f"Removed {len(unfiltered_depots) - len(filtered_depots)} depots based on blacklist."
                        )

                    game_data["depots"] = filtered_depots

                    if not filtered_depots:
                        logger.warning(
                            "All depots were filtered out. No depots to download."
                        )
                    else:
                        if not self._ensure_not_stopped():
                            return self._cancelled_result()

                        api_data = (
                            self._fetch_depot_info_with_timeout(
                                game_data["appid"], game_data.get("app_token")
                            )
                            if game_data.get("appid")
                            else {}
                        )

                        if api_data.get("installdir"):
                            game_data["installdir"] = api_data["installdir"]
                            logger.info(
                                f"Found official install directory: {game_data['installdir']}"
                            )

                        if api_data.get("buildid"):
                            game_data["buildid"] = api_data["buildid"]
                            logger.info(
                                f"Found official buildid: {game_data['buildid']}"
                            )

                        if api_data.get("header_url"):
                            game_data["header_url"] = api_data["header_url"]
                        if not game_data.get("game_name") and api_data.get("name"):
                            game_data["game_name"] = api_data["name"]
                            logger.info(
                                f"Resolved game name from Steam API: {game_data['game_name']}"
                            )

                        api_details = api_data.get("depots", {})
                        logger.debug(
                            f"Received API details for processing: {api_details}"
                        )

                        if not api_details:
                            logger.warning(
                                "Could not retrieve supplementary details from Steam API."
                            )

                        enriched_depots = {}
                        for depot_id, lua_data in filtered_depots.items():
                            if not self._ensure_not_stopped():
                                return self._cancelled_result()

                            final_depot_data = {"key": lua_data["key"]}
                            details = api_details.get(str(depot_id))

                            base_description = known_depot_descriptions.get(
                                depot_id, lua_data["desc"]
                            )

                            if details:
                                tags = []
                                if details.get("oslist"):
                                    tags.append(f"[{details['oslist'].upper()}]")
                                if details.get("steamdeck"):
                                    tags.append("[DECK]")

                                if details.get("language"):
                                    base_description += (
                                        f" ({details['language'].capitalize()})"
                                    )

                                final_description = (
                                    " ".join(tags) + " " + base_description
                                    if tags
                                    else base_description
                                )

                                final_depot_data["oslist"] = details.get("oslist")
                                final_depot_data["language"] = details.get("language")
                            else:
                                final_description = base_description

                            lower_desc = final_description.lower()
                            if "soundtrack" in lower_desc or re.search(
                                r"\bost\b", lower_desc
                            ):
                                logger.info(
                                    f"Filtering out soundtrack depot {depot_id} ('{final_description}')."
                                )
                                continue

                            api_size = details.get("size") if details else None
                            if api_size:
                                final_depot_data["size"] = api_size
                                logger.debug(
                                    f"Using API size for depot {depot_id}: {api_size}"
                                )
                            else:
                                lua_size = game_data.get("manifest_sizes", {}).get(
                                    depot_id
                                )
                                if lua_size:
                                    final_depot_data["size"] = lua_size
                                    logger.debug(
                                        f"Using LUA fallback size for depot {depot_id}: {lua_size}"
                                    )
                                else:
                                    logger.debug(
                                        f"No size found for depot {depot_id} in API or LUA."
                                    )

                            final_depot_data["desc"] = final_description
                            enriched_depots[depot_id] = final_depot_data

                        game_data["depots"] = enriched_depots

                if not game_data.get("game_name"):
                    game_data["game_name"] = f"App_{game_data['appid']}"
                    logger.warning(
                        f"Could not determine game name from Lua or API. Fallback to {game_data['game_name']}"
                    )

                manifest_dir = os.path.join(
                    tempfile.gettempdir(), "mistwalker_manifests"
                )
                os.makedirs(manifest_dir, exist_ok=True)
                for name, content in manifest_files.items():
                    if not self._ensure_not_stopped():
                        return self._cancelled_result()
                    with open(os.path.join(manifest_dir, name), "wb") as f:
                        f.write(content)

            logger.info("Zip processing task completed successfully.")
            return game_data
        except Exception as e:
            logger.error(f"Zip processing failed: {e}", exc_info=True)
            raise
