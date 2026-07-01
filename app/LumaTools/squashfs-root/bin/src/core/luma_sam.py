import os
import sys
import ctypes
import time
import logging

logger = logging.getLogger(__name__)

class LumaSAM:
    def __init__(self, app_id: str, game_path: str):
        self.app_id = str(app_id)
        self.game_path = game_path
        self.steam_api = None
        
    def _find_steam_api_lib(self):
        """Find libsteam_api.so in the game path or system."""
        # Typically ships with games, check the game directory
        possible_paths = [
            os.path.join(self.game_path, "libsteam_api.so"),
            os.path.join(self.game_path, "libsteam_api64.so"),
        ]
        
        # Search recursively in the game path (limit depth to avoid long searches)
        for root, dirs, files in os.walk(self.game_path):
            if "libsteam_api.so" in files:
                return os.path.join(root, "libsteam_api.so")
            if "libsteam_api64.so" in files:
                return os.path.join(root, "libsteam_api64.so")
                
        # Fallback to loading it from standard paths or assume it's in LD_LIBRARY_PATH
        return "libsteam_api.so"

    def unlock_all_achievements(self, achievements_list=None):
        """
        Unlocks all achievements using the Steamworks API.
        If achievements_list is None, it attempts to unlock some generic ones or 
        relies on a provided list of achievement names.
        """
        logger.info(f"Starting LumaSAM for AppID {self.app_id} in {self.game_path}")
        
        # 1. Create steam_appid.txt
        appid_path = os.path.join(self.game_path, "steam_appid.txt")
        try:
            with open(appid_path, "w") as f:
                f.write(self.app_id)
            logger.debug(f"Created steam_appid.txt with {self.app_id}")
        except Exception as e:
            logger.error(f"Failed to create steam_appid.txt: {e}")
            return False

        # 2. Change working directory to game path so libsteam_api finds the text file
        original_cwd = os.getcwd()
        os.chdir(self.game_path)

        try:
            # 3. Load Steam API Library
            lib_path = self._find_steam_api_lib()
            logger.debug(f"Loading Steam API from {lib_path}")
            
            try:
                self.steam_api = ctypes.cdll.LoadLibrary(lib_path)
            except OSError as e:
                logger.error(f"Could not load Steam API library: {e}. Is the game 32-bit or missing the lib?")
                return False

            # 4. Initialize Steam API
            self.steam_api.SteamAPI_Init.restype = ctypes.c_bool
            if not self.steam_api.SteamAPI_Init():
                logger.error("SteamAPI_Init failed. Make sure Steam is running.")
                return False
                
            logger.info("Steam API initialized successfully!")

            # 5. Get ISteamUserStats interface
            # The interface getters can be tricky in ctypes without the C++ vtable,
            # but standard C flat API usually exports SteamAPI_SteamUserStats_v012 or similar.
            # Using SteamAPI_SteamUserStats() flat wrapper if available.
            try:
                self.steam_api.SteamAPI_SteamUserStats_v012.restype = ctypes.c_void_p
                user_stats = self.steam_api.SteamAPI_SteamUserStats_v012()
            except AttributeError:
                try:
                    self.steam_api.SteamAPI_SteamUserStats_v011.restype = ctypes.c_void_p
                    user_stats = self.steam_api.SteamAPI_SteamUserStats_v011()
                except AttributeError:
                    logger.error("Could not find SteamUserStats interface in the loaded library.")
                    self.steam_api.SteamAPI_Shutdown()
                    return False
                    
            if not user_stats:
                logger.error("SteamUserStats interface returned null.")
                self.steam_api.SteamAPI_Shutdown()
                return False

            # 6. Request current stats
            self.steam_api.SteamAPI_ISteamUserStats_RequestCurrentStats.argtypes = [ctypes.c_void_p]
            self.steam_api.SteamAPI_ISteamUserStats_RequestCurrentStats.restype = ctypes.c_bool
            if not self.steam_api.SteamAPI_ISteamUserStats_RequestCurrentStats(user_stats):
                logger.error("Failed to request current stats.")
                self.steam_api.SteamAPI_Shutdown()
                return False
                
            # Wait a moment for callbacks (hacky but simple for a Python script without full callback implementation)
            time.sleep(2)
            self.steam_api.SteamAPI_RunCallbacks()

            # 7. Unlock achievements
            self.steam_api.SteamAPI_ISteamUserStats_SetAchievement.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            self.steam_api.SteamAPI_ISteamUserStats_SetAchievement.restype = ctypes.c_bool
            
            unlocked_count = 0
            if achievements_list:
                for ach in achievements_list:
                    ach_bytes = ach.encode('utf-8')
                    if self.steam_api.SteamAPI_ISteamUserStats_SetAchievement(user_stats, ach_bytes):
                        unlocked_count += 1
                        logger.debug(f"Unlocked achievement: {ach}")
            else:
                # If no list is provided, try common generic IDs or iterate if possible
                # Without Steamworks SDK headers, iterating is complex.
                # Usually we need the achievement names. We can read them from a local achievements.json if available
                logger.warning("No achievement list provided, cannot unlock specific achievements.")

            # 8. Store stats
            self.steam_api.SteamAPI_ISteamUserStats_StoreStats.argtypes = [ctypes.c_void_p]
            self.steam_api.SteamAPI_ISteamUserStats_StoreStats.restype = ctypes.c_bool
            if self.steam_api.SteamAPI_ISteamUserStats_StoreStats(user_stats):
                logger.info(f"Successfully stored stats! Unlocked {unlocked_count} achievements.")
            else:
                logger.error("Failed to store stats.")

            # 9. Shutdown
            self.steam_api.SteamAPI_Shutdown()
            return True

        except Exception as e:
            logger.error(f"Error during achievement unlock: {e}", exc_info=True)
            return False
        finally:
            os.chdir(original_cwd)
            # Cleanup steam_appid.txt
            if os.path.exists(appid_path):
                try:
                    os.remove(appid_path)
                except OSError:
                    pass

# Example usage function for the UI
def run_luma_sam(app_id, game_path, achievements_list=None):
    sam = LumaSAM(app_id, game_path)
    return sam.unlock_all_achievements(achievements_list)
