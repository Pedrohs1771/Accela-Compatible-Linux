# QA REPORT

- PASS `shell-syntax`
  bash -n passou
- PASS `compileall`
  Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/api'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/api/backend'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/api/backend/locales'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/api/backend/settings'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/api/backend/temp_dl'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/components'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/core'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/core/diagnostics'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/core/platform'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/core/tasks'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/core/utils'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/deps'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/deps/Goldberg'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/deps/Goldberg/genints'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/deps/Goldberg/linux'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/deps/Goldberg/steam_settings'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/deps/Goldberg/windows'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/deps/Steamless'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/deps/Steamless/Plugins'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/managers'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/gif'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/logo'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/sonic'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/sonic/gifs'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/sonic/sounds'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/sounds'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/theme'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/theme/hellgirl'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/visual_presets'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/visual_presets/clock_homura'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/visual_presets/clock_homura/gif'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/visual_presets/ghoul_touka'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/visual_presets/ghoul_touka/gif'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/visual_presets/wired_lain'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/res/visual_presets/wired_lain/gif'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/ui'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/ui/dialogs'...
Listing '/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src/utils'...
- PASS `unit-tests`
  ============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/pedrohs/Luma-Tools
plugins: anyio-4.14.1
collecting ... collected 105 items

tests/test_anticheat_guard.py::test_guard_detects_anticheat PASSED       [  0%]
tests/test_anticheat_guard.py::test_guard_restores_state PASSED          [  1%]
tests/test_anticheat_guard.py::test_apply_protection_writes_to_pipe PASSED [  2%]
tests/test_anticheat_guard.py::test_restore_protection PASSED            [  3%]
tests/test_depot_install_helpers.py::DepotInstallHelpersTests::test_completes_split_base_depots_for_selected_platform PASSED [  4%]
tests/test_depot_install_helpers.py::DepotInstallHelpersTests::test_detects_terraria_dotnet_xna_redists PASSED [  5%]
tests/test_depot_install_helpers.py::DepotInstallHelpersTests::test_extracts_only_main_app_depots PASSED [  6%]
tests/test_depot_install_helpers.py::DepotInstallHelpersTests::test_marks_encrypted_depot_output_as_failure PASSED [  7%]
tests/test_depot_install_helpers.py::DepotInstallHelpersTests::test_recovers_manifest_from_source_zip PASSED [  8%]
tests/test_depotselection_dialog.py::DepotSelectionDialogTests::test_linux_depot_hides_proton_and_onlinefix_controls PASSED [  9%]
tests/test_depotselection_dialog.py::DepotSelectionDialogTests::test_windows_depot_shows_proton_and_onlinefix_controls PASSED [ 10%]
tests/test_dlc_engine.py::test_auto_detect_dlc_method PASSED             [ 11%]
tests/test_dlc_engine.py::test_generate_cream_api_config PASSED          [ 12%]
tests/test_dlc_engine.py::test_generate_goldberg_dlc_txt PASSED          [ 13%]
tests/test_dlc_engine.py::test_batch_activate_all_dlcs_creamapi PASSED   [ 14%]
tests/test_dlc_engine.py::test_verify_dlc_files_exist PASSED             [ 15%]
tests/test_download_slssteam_task.py::DownloadSLSsteamTaskTests::test_blocking_install_does_not_write_version_when_incompatible PASSED [ 16%]
tests/test_download_slssteam_task.py::DownloadSLSsteamTaskTests::test_flatpak_override_accepts_official_override_with_different_paths PASSED [ 17%]
tests/test_game_manager_appid.py::GameManagerAppIDTests::test_prefers_real_appid_over_fake_appid PASSED [ 18%]
tests/test_game_manager_appid.py::GameManagerAppIDTests::test_reads_lumatools_profile_and_marker PASSED [ 19%]
tests/test_game_manager_appid.py::GameManagerAppIDTests::test_reads_nested_steam_appid PASSED [ 20%]
tests/test_gif_assets.py::GifAssetTests::test_default_theme_has_recolorable_pixels 
tests/test_gif_assets.py::GifAssetTests::test_default_theme_has_recolorable_pixels PASSED [ 20%]
tests/test_gif_assets.py::GifAssetTests::test_default_theme_uses_animated_gifs_only 
tests/test_gif_assets.py::GifAssetTests::test_default_theme_uses_animated_gifs_only PASSED [ 21%]
tests/test_gif_assets.py::GifAssetTests::test_visual_preset_main_gifs_are_visible 
tests/test_gif_assets.py::GifAssetTests::test_visual_preset_main_gifs_are_visible PASSED [ 22%]
tests/test_gif_assets.py::GifAssetTests::test_visual_presets_have_complete_recolorable_gif_sets 
tests/test_gif_assets.py::GifAssetTests::test_visual_presets_have_complete_recolorable_gif_sets PASSED [ 23%]
tests/test_gif_colorization.py::GifColorizationTests::test_cache_key_separates_copy_and_colorization_modes PASSED [ 24%]
tests/test_gif_colorization.py::GifColorizationTests::test_gif_is_colorized_before_atomic_publish PASSED [ 25%]
tests/test_gif_colorization.py::GifColorizationTests::test_palette_colorization_preserves_entry_brightness PASSED [ 26%]
tests/test_gif_colorization.py::GifColorizationTests::test_rgba_colorization_preserves_pixel_brightness PASSED [ 27%]
tests/test_health_monitor.py::test_check_slssteam_health PASSED          [ 28%]
tests/test_health_monitor.py::test_check_lua_script_validity PASSED      [ 29%]
tests/test_health_monitor.py::test_check_online_fix_integrity PASSED     [ 30%]
tests/test_health_monitor.py::test_auto_repair PASSED                    [ 31%]
tests/test_health_monitor.py::test_generate_diagnostic_report PASSED     [ 32%]
tests/test_hot_reload.py::test_watcher_detects_new_file PASSED           [ 33%]
tests/test_hot_reload.py::test_watcher_detects_modification PASSED       [ 34%]
tests/test_hot_reload.py::test_handle_modification_config PASSED         [ 35%]
tests/test_hot_reload.py::test_handle_modification_acf PASSED            [ 36%]
tests/test_linux_paths_and_config.py::LinuxSteamModeTests::test_finds_running_steam_root_outside_standard_locations PASSED [ 37%]
tests/test_linux_paths_and_config.py::LinuxSteamModeTests::test_finds_steam_root_from_compat_environment PASSED [ 38%]
tests/test_linux_paths_and_config.py::LinuxSteamModeTests::test_native_root_wins_when_flatpak_is_only_installed PASSED [ 39%]
tests/test_linux_paths_and_config.py::LinuxSteamModeTests::test_plain_flatpak_command_unsets_audit_environment PASSED [ 40%]
tests/test_linux_paths_and_config.py::LinuxSteamModeTests::test_plain_native_command_does_not_use_slssteam_wrapper PASSED [ 40%]
tests/test_linux_paths_and_config.py::LinuxSteamModeTests::test_process_classifier_detects_flatpak_steam_binary_path PASSED [ 41%]
tests/test_linux_paths_and_config.py::LinuxSteamModeTests::test_process_classifier_detects_flatpak_steam_launcher PASSED [ 42%]
tests/test_linux_paths_and_config.py::LinuxSteamModeTests::test_process_classifier_ignores_file_managers_opening_steam_paths PASSED [ 43%]
tests/test_linux_paths_and_config.py::LinuxSteamModeTests::test_running_flatpak_overrides_native_root PASSED [ 44%]
tests/test_linux_paths_and_config.py::LinuxSteamModeTests::test_snap_slssteam_is_explicitly_unsupported PASSED [ 45%]
tests/test_linux_paths_and_config.py::SteamPlainLaunchTests::test_plain_launch_sanitizes_inherited_audit_environment PASSED [ 46%]
tests/test_linux_paths_and_config.py::SteamPlainLaunchTests::test_slssteam_launch_uses_steam_launcher_and_verifies_loaded PASSED [ 47%]
tests/test_linux_paths_and_config.py::LinuxBackendLibraryTests::test_detects_library_on_another_mounted_drive PASSED [ 48%]
tests/test_linux_paths_and_config.py::LinuxBackendLibraryTests::test_normalizes_common_folder_to_external_library_root PASSED [ 49%]
tests/test_linux_paths_and_config.py::LinuxBackendLibraryTests::test_normalizes_game_folder_to_library_root_even_without_known_libraries PASSED [ 50%]
tests/test_linux_paths_and_config.py::LinuxBackendLibraryTests::test_preserves_non_steam_destination PASSED [ 51%]
tests/test_linux_paths_and_config.py::SLSsteamConfigPathTests::test_flatpak_config_path_is_returned_even_when_missing PASSED [ 52%]
tests/test_linux_paths_and_config.py::SLSsteamConfigPathTests::test_snap_config_path_is_not_native_config_path PASSED [ 53%]
tests/test_linux_paths_and_config.py::SLSsteamAppTokenTests::test_accepts_decimal_uint64_token PASSED [ 54%]
tests/test_linux_paths_and_config.py::SLSsteamAppTokenTests::test_rejects_hex_depot_key_without_modifying_config PASSED [ 55%]
tests/test_linux_paths_and_config.py::SLSsteamAppTokenTests::test_sanitizes_invalid_app_tokens_while_preserving_valid_tokens PASSED [ 56%]
tests/test_linux_paths_and_config.py::RyuuPostDownloadTests::test_task_manager_never_auto_offers_ryuu_after_download PASSED [ 57%]
tests/test_lua_generator_v2.py::test_generate_with_auto_tokens PASSED    [ 58%]
tests/test_lua_generator_v2.py::test_merge_lua_scripts PASSED            [ 59%]
tests/test_lua_generator_v2.py::test_diff_and_update PASSED              [ 60%]
tests/test_luma_doctor.py::LumaDoctorTests::test_inspect_appmanifest_flags_pending_update_state PASSED [ 60%]
tests/test_luma_doctor.py::LumaDoctorTests::test_run_doctor_marks_missing_onlinefix_launch_options PASSED [ 61%]
tests/test_online_fix_extractor.py::OnlineFixExtractorTests::test_extracts_zip_through_temp_dir PASSED [ 62%]
tests/test_online_fix_extractor.py::OnlineFixExtractorTests::test_normalizes_onlinefix_language_to_brazilian PASSED [ 63%]
tests/test_online_fix_extractor.py::OnlineFixExtractorTests::test_rejects_zip_path_traversal PASSED [ 64%]
tests/test_ryuu_client.py::RyuuClientLocalSecretsTests::test_save_load_and_mask_key_without_repo_secret PASSED [ 65%]
tests/test_settings_dialog.py::SettingsDialogTests::test_settings_tabs_are_scrollable_and_cleanly_titled PASSED [ 66%]
tests/test_steam_config_helper.py::SteamConfigHelperTests::test_preserves_extra_launch_flags_while_replacing_dll_entries PASSED [ 67%]
tests/test_steam_config_helper.py::SteamConfigHelperTests::test_preserves_wined3d_fallback_when_refreshing_onlinefix_options PASSED [ 68%]
tests/test_steam_config_helper.py::SteamConfigHelperTests::test_repairs_old_semicolon_broken_onlinefix_overrides PASSED [ 69%]
tests/test_steam_config_helper.py::SteamConfigHelperTests::test_repairs_online_fix_launch_options_from_game_info PASSED [ 70%]
tests/test_steam_config_helper.py::SteamConfigHelperTests::test_replaces_old_64_bit_onlinefix_overrides_with_32_bit_set PASSED [ 71%]
tests/test_steam_config_helper.py::SteamConfigHelperTests::test_set_launch_options_updates_all_user_configs PASSED [ 72%]
tests/test_steam_library_destination.py::SteamLibraryDestinationTests::test_existing_install_path_preserves_real_install_directory PASSED [ 73%]
tests/test_steam_library_destination.py::SteamLibraryDestinationTests::test_multiple_libraries_open_selector_instead_of_forcing_primary PASSED [ 74%]
tests/test_steam_library_destination.py::SteamLibraryDestinationTests::test_single_library_keeps_existing_automatic_behavior PASSED [ 75%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_active_steam_owner_uses_most_recent_login_user PASSED [ 76%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_detects_content_still_encrypted_message PASSED [ 77%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_generate_download_trigger_acf PASSED [ 78%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_onlinefix_windows_game_gets_proton_platform_override PASSED [ 79%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_repair_uses_main_steam_owner_for_external_library PASSED [ 80%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_repairs_lumatools_managed_update_state PASSED [ 80%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_reports_decryption_key_block_without_hiding_repair PASSED [ 81%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_skips_unmanaged_games PASSED [ 82%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_stress_repairs_only_managed_games_across_libraries PASSED [ 83%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_validate_acf_integrity PASSED [ 84%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_write_acf_uses_active_steam_owner PASSED [ 85%]
tests/test_steam_manifest_repair.py::SteamManifestRepairTests::test_write_acf_uses_main_steam_owner_for_external_library PASSED [ 86%]
tests/test_ui_gif_selection.py::DefaultDownloadGifSelectionTests::test_colorized_cache_marker_must_match_selected_preset PASSED [ 87%]
tests/test_ui_gif_selection.py::DefaultDownloadGifSelectionTests::test_colorized_cache_without_marker_only_matches_default_preset PASSED [ 88%]
tests/test_ui_gif_selection.py::DefaultDownloadGifSelectionTests::test_prefers_colorized_download_gifs_when_available PASSED [ 89%]
tests/test_ui_gif_selection.py::DefaultDownloadGifSelectionTests::test_uses_bundled_download_gifs_when_colorized_cache_is_empty PASSED [ 90%]
tests/test_update_manager_windows.py::UpdateManagerWindowsManifestTests::test_prefers_windows_platform_payload PASSED [ 91%]
tests/test_update_manager_windows.py::UpdateManagerWindowsManifestTests::test_rejects_manifest_without_windows_package PASSED [ 92%]
tests/test_windows_backend.py::WindowsBackendTests::test_detects_registry_root_and_libraries PASSED [ 93%]
tests/test_windows_backend.py::WindowsBackendTests::test_falls_back_to_program_files_candidates PASSED [ 94%]
tests/test_windows_helpers.py::WindowsHelperTests::test_windows_launcher_target_prefers_cmd_wrapper PASSED [ 95%]
tests/test_windows_helpers.py::WindowsHelperTests::test_windows_program_root_uses_localappdata PASSED [ 96%]
tests/test_windows_offline_mode.py::WindowsOfflineModeTests::test_fix_offline_mode_clears_flag_for_autologin_user PASSED [ 97%]
tests/test_windows_offline_mode.py::WindowsOfflineModeTests::test_fix_offline_mode_keeps_manual_offline_user_unchanged PASSED [ 98%]
tests/test_windows_offline_mode.py::WindowsOfflineModeTests::test_windows_manifest_cache_targets_steam_root_depotcache PASSED [ 99%]
tests/test_windows_offline_mode.py::WindowsOfflineModeTests::test_windows_restart_repairs_managed_state_before_relaunch PASSED [100%]

=================== 105 passed, 71 subtests passed in 6.41s ====================
- PASS `desktop-file`
  ok

Resultado final: APROVADO
