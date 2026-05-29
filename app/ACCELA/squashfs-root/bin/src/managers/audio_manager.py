import os
import logging
import time
from PyQt6.QtWidgets import QApplication
from just_playback import Playback

from utils.paths import Paths
from utils.settings import get_settings

logger = logging.getLogger(__name__)


class AudioManager:
    # Constants for sound types
    SOUND_ETW = "etw"
    SOUND_LALL = "lall"
    SOUND_LOOP = "loop"

    def __init__(self, main_window):
        self.main_window = main_window
        self.settings = get_settings()
        self.exit_sound_played = False
        self.start_sound_played = False
        self.open_playback = None
        self.close_playback = None
        self.loop_playback = None
        self.audio_available = False

        # Store current preview values
        self.preview_master_volume = self.settings.value("master_volume", 80, type=int)
        self.preview_effects_volume = self.settings.value(
            "effects_volume", 50, type=int
        )
        self.preview_hum_volume = self.settings.value("hum_volume", 20, type=int)

        self.setup_sounds()

    @staticmethod
    def apply_volume(volume_slider_value):
        """Convert slider value to linear volume"""
        linear_volume = volume_slider_value / 100.0
        logger.debug(f"Converting volume: {volume_slider_value} -> {linear_volume:.3f}")
        return linear_volume

    def validate_audio_files(self):
        """Validate that audio files exist and are accessible"""
        logger.debug("Validating audio files...")
        # Prefer WAV files but accept MP3 for the loop hum if present
        audio_files = [
            str(self._resolve_sound_path("etw.wav")),
            str(self._resolve_sound_path("lall.wav")),
        ]

        # Check for loop with multiple extensions
        hz_wav = self._resolve_sound_path("loop.wav")
        hz_mp3 = self._resolve_sound_path("loop.mp3")
        if hz_wav.exists():
            audio_files.append(str(hz_wav))
        elif hz_mp3.exists():
            audio_files.append(str(hz_mp3))
        else:
            # include the expected path for clearer logging even if missing
            audio_files.append(str(hz_wav))

        all_files_valid = True
        for file_path in audio_files:
            if not os.path.exists(file_path):
                logger.error(f"Audio file not found: {file_path}")
                all_files_valid = False
            elif os.path.getsize(file_path) == 0:
                logger.error(f"Audio file is empty: {file_path}")
                all_files_valid = False
            else:
                logger.debug(f"Audio file found: {file_path}")

        return all_files_valid

    def setup_sounds(self, play_open_sound: bool = True):
        """Setup all audio effects with volume control"""
        logger.debug("Setting up audio sounds...")
        self.open_playback = None
        self.close_playback = None
        self.loop_playback = None

        if not self.audio_available:
            logger.info("Audio disabled in this local build; skipping sound setup.")
            return

        # Deprecated (To be replaced if needed, used QT before which fails on SteamDeck and similar.)
        # Check for audio devices first
        # if not self.check_audio_devices():
        #     logger.warning("Audio setup aborted - no audio devices available")
        #     self.open_playback = self.close_playback = self.loop_playback = None
        #     self.audio_available = False
        #     return

        # Validate audio files
        if not self.validate_audio_files():
            logger.warning("Some audio files are missing or invalid")

        try:
            # Open sound (ETW)
            logger.debug("Setting up open sound...")
            open_sound_path = self._resolve_sound_path("etw.wav")
            if open_sound_path.exists():
                logger.debug(f"Loading open sound: {str(open_sound_path)}")
                self.open_playback = Playback(str(open_sound_path))
                if (
                    play_open_sound
                    and self.settings.value("play_etw", True, type=bool)
                    and not self.open_playback.playing
                ):
                    logger.debug("Playing open sound (ETW)")
                    self.play_sound(self.SOUND_ETW)
            else:
                logger.warning(f"Could not find open sound: {str(open_sound_path)}")
                self.open_playback = None

            # Close sound (LALL)
            logger.debug("Setting up close sound...")
            close_sound_path = self._resolve_sound_path("lall.wav")
            if close_sound_path.exists():
                logger.debug(f"Loading close sound: {str(close_sound_path)}")
                self.close_playback = Playback(str(close_sound_path))
                app = QApplication.instance()
                if app is not None:
                    app.aboutToQuit.connect(self.on_app_about_to_quit)
            else:
                logger.warning(f"Could not find close sound: {str(close_sound_path)}")
                self.close_playback = None

            # Loop sound (loop hum)
            logger.debug("Setting up loop sound...")
            # Try WAV first, then MP3 for the loop hum
            loop_sound_path = None
            for ext in ("wav", "mp3"):
                candidate = self._resolve_sound_path(f"loop.{ext}")
                if candidate.exists():
                    loop_sound_path = candidate
                    break

            if loop_sound_path and loop_sound_path.exists():
                logger.debug(f"Loading loop sound: {str(loop_sound_path)}")
                self.loop_playback = Playback(str(loop_sound_path))

                # Only play if enabled in settings
                if (
                    self.settings.value("play_50hz_hum", True, type=bool)
                    and not self.loop_playback.playing
                ):
                    logger.debug("Starting loop sound playback (muted initially)")
                    self.play_sound(self.SOUND_LOOP)
            else:
                logger.warning(f"Could not find loop sound: {str(loop_sound_path)}")
                self.loop_playback = None

            # Apply initial audio settings
            logger.debug("Applying initial audio settings...")
            self.apply_audio_settings()
            logger.debug("Audio setup completed successfully")

        except Exception as e:
            logger.error(f"Error during audio setup: {e}")
            self.open_playback = None
            self.close_playback = None
            self.loop_playback = None

    def _resolve_sound_path(self, filename: str):
        """Resolve sound path, preferring Sonic overrides when enabled."""
        ui_mode = self.settings.value("ui_mode", "default")
        return Paths.sound_path(filename, ui_mode)

    def reload_sounds_for_ui_mode(self):
        """Reload sounds when UI mode changes (Sonic mode toggle)."""
        logger.debug("Reloading sounds for UI mode change")
        self.stop_all_sounds()

        # Clear current playbacks
        self.open_playback = None
        self.close_playback = None
        self.loop_playback = None

        # Recreate sounds without auto-playing the open sound
        self.setup_sounds(play_open_sound=False)

    def apply_audio_settings(self):
        """Applies all audio settings including volumes using saved settings"""
        if not self.audio_available:
            logger.debug("Audio not available, skipping settings application")
            return

        if not any([self.open_playback, self.close_playback, self.loop_playback]):
            logger.debug("No audio playbacks available, skipping settings application")
            return

        logger.debug("Applying audio settings...")

        # Get slider values from settings
        master_volume = self.apply_volume(
            self.settings.value("master_volume", 80, type=int)
        )
        effects_volume = self.apply_volume(
            self.settings.value("effects_volume", 50, type=int)
        )
        hum_volume = self.apply_volume(self.settings.value("hum_volume", 20, type=int))

        logger.debug(
            f"Volume levels - Master: {master_volume:.3f}, Effects: {effects_volume:.3f}, Hum: {hum_volume:.3f}"
        )

        # Apply volumes to playbacks
        if self.open_playback:
            self.open_playback.set_volume(master_volume * effects_volume)
        if self.close_playback:
            self.close_playback.set_volume(master_volume * effects_volume)
        logger.debug(f"Effects volume applied: {master_volume * effects_volume:.3f}")

        if self.loop_playback:
            self.loop_playback.set_volume(master_volume * hum_volume)
            logger.debug(f"Hum volume applied: {master_volume * hum_volume:.3f}")

        # Handle loop sound playback state
        play_loop = self.settings.value("play_50hz_hum", True, type=bool)
        if play_loop:
            self.ensure_loop_playing()
        else:
            self.stop_loop()

    def sync_preview_values_from_settings(self):
        """Sync preview values with current pyqt settings"""
        self.preview_master_volume = self.settings.value("master_volume", 80, type=int)
        self.preview_effects_volume = self.settings.value(
            "effects_volume", 50, type=int
        )
        self.preview_hum_volume = self.settings.value("hum_volume", 20, type=int)
        logger.debug(
            f"Synced preview values from settings - Master: {self.preview_master_volume}, Effects: {self.preview_effects_volume}, Hum: {self.preview_hum_volume}"
        )

    def preview_volume(self, master, effects, hum):
        """
        Apply preview volumes for all three sliders at once.
        This is called whenever any volume slider moves.
        """
        # logger.debug(
        #     f"Preview volumes - Master: {master}, Effects: {effects}, Hum: {hum}"
        # )

        if not self.audio_available:
            logger.debug("Audio not available, skipping preview volume application")
            return

        self.preview_master_volume = master
        self.preview_effects_volume = effects
        self.preview_hum_volume = hum

        # Convert to linear
        master_linear = self.apply_volume(master)
        effects_linear = self.apply_volume(effects)
        hum_linear = self.apply_volume(hum)

        # Apply to playbacks
        if self.open_playback:
            self.open_playback.set_volume(master_linear * effects_linear)
        if self.close_playback:
            self.close_playback.set_volume(master_linear * effects_linear)
        if self.loop_playback:
            self.loop_playback.set_volume(master_linear * hum_linear)

    def on_app_about_to_quit(self):
        """Handle application about to quit event (wait for sound to finish)"""
        if not self.settings.value("play_lall", True, type=bool):
            logger.debug("Close sound is disabled.")
            return

        logger.debug("Playing exit sound")

        # Stop all sounds
        self.stop_all_sounds()

        # Play close sound and BLOCK until it finishes
        self.play_close_sound_and_wait()

    def play_close_sound_and_wait(self):
        """Play the close sound and wait with timeout protection"""
        if not self.close_playback:
            logger.debug("Close playback not available, skipping")
            return

        logger.debug("Starting close sound playback with blocking wait")
        self.play_sound(self.SOUND_LALL, preview=False, block=True)

    def play_sound(self, sound_type, preview=False, block=False):
        if not self.audio_available:
            logger.debug("Audio not available, cannot play sound")
            return

        match sound_type:
            case self.SOUND_ETW:
                if self.start_sound_played:
                    return
                playback = self.open_playback
                if preview:
                    master = self.preview_master_volume
                    secondary = self.preview_effects_volume
                else:
                    self.start_sound_played = True
                    master = self.settings.value("master_volume", 80, type=int)
                    secondary = self.settings.value("effects_volume", 50, type=int)

            case self.SOUND_LALL:
                if self.exit_sound_played:
                    return
                playback = self.close_playback
                if preview:
                    master = self.preview_master_volume
                    secondary = self.preview_effects_volume
                else:
                    self.exit_sound_played = True
                    master = self.settings.value("master_volume", 80, type=int)
                    secondary = self.settings.value("effects_volume", 50, type=int)

            case self.SOUND_LOOP:
                playback = self.loop_playback
                playback.loop_at_end(True)
                if preview:
                    master = self.preview_master_volume
                    secondary = self.preview_hum_volume
                else:
                    master = self.settings.value("master_volume", 80, type=int)
                    secondary = self.settings.value("hum_volume", 20, type=int)

            case _:
                logger.error(f"Unknown sound type: {sound_type}")
                return

        if not playback:
            logger.debug(f"Playback for {sound_type} not available")
            return

        if playback.playing:
            logger.debug(f"{sound_type} sound already playing, restarting")
            playback.stop()

        playback.play()
        volume = self.apply_volume(master) * self.apply_volume(secondary)
        playback.set_volume(volume)
        logger.debug(f"Set {sound_type} volume to {volume:.3f} (preview={preview})")

        if block:
            self._wait_for_playback(playback, sound_type)

    def _wait_for_playback(self, playback, sound_type):
        """Internal helper to wait for a playback to finish with timeout."""
        sound_length = playback.duration
        max_wait_time = sound_length
        start_time = time.time()

        while playback.playing:
            if time.time() - start_time > max_wait_time:
                logger.warning(f"{sound_type} playback timeout, continuing")
                break
            time.sleep(0.05)
        logger.debug(f"{sound_type} playback finished")

    def ensure_loop_playing(self):
        """Ensure loop sound is playing if it should be (per settings), restart if stopped."""
        if not self.audio_available or not self.loop_playback:
            return
        if not self.loop_playback.playing:
            logger.debug("Loop sound was stopped, restarting")
            self.play_sound(self.SOUND_LOOP, preview=False)

    def stop_loop(self):
        """Stop the loop sound if playing."""
        if not self.audio_available or not self.loop_playback:
            return
        if self.loop_playback and self.loop_playback.playing:
            logger.debug("Stopping loop sound")
            self.loop_playback.stop()

    def stop_all_sounds(self):
        """Stop all currently playing sounds."""
        logger.debug("Stopping all sounds")
        if self.open_playback and self.open_playback.playing:
            self.open_playback.stop()
        if self.close_playback and self.close_playback.playing:
            self.close_playback.stop()
        if self.loop_playback and self.loop_playback.playing:
            self.loop_playback.stop()
