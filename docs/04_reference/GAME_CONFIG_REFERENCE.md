# Game Configuration Reference

> **Last Updated:** April 2026 | **Applies to:** JD2021 Map Installer v2

This document maps the configuration files inside the JD2021 PC game data directory. It is a reference for understanding what each file controls and which files are relevant to modding.

This replaces the previous `JD21_Configuration_Map.md`.

Scope note for V2: this document focuses on game/runtime configuration surfaces and installer-generated config artifacts. Workflow details for Fetch/HTML/IPK/Batch/Manual install modes and readjust UX live in pipeline and operator docs.

---

## 1. Top-Level Configuration

| File | Format | Purpose |
|------|--------|---------|
| `jd21/data/config.xml` | XML | Main game config: resolution (1280x720), fullscreen, safe frame, XInput |
| `jd21/engine/RUNNER.bat` | BAT | Startup parameters: resolution override (1920x1080), language, debug flags |
| `jd21/engine/projectinfo.xml` | XML | Project ID (JD2021_TU1), branch info |
| `jd21/engine/bloomberg_settings.ini` | INI | Crash reporting servers, logging level, build numbers |

---

## 2. Installer-Generated Configuration

These files are created by the installer pipeline, not part of the base game.

| File | Format | Purpose |
|------|--------|---------|
| `installer_paths.json` | JSON | Cached game-data directory paths and SkuScene reference |
| `installer_settings.json` | JSON | Global installer settings: default_quality, a_offset, v_override, marker_preroll_ms |
| `map_readjust_index.json` | JSON | Persistent readjust index linking installed maps to source roots for post-install offset workflows |

---

## 3. EngineData/GameConfig (Lua Files)

All `.isg` and `.ilu` files are plain-text Lua table syntax, directly editable with any text editor. `gameconfig.isg` is the master hub that includes all subsystem configs.

### Core Gameplay (.isg files)

| File | Controls |
|------|----------|
| `gameconfig.isg` | Master config: includes all subsystem configs |
| `quickplayrules.isg` | Difficulty sequencing, song selection rules, coach matching |
| `achievements.isg` | 35 achievements across all platforms |
| `soundconfig.isg` | Full audio bus system (25+ buses), ducking, limiters |
| `vibration.isg` | 28 HD Rumble effects for controllers |
| `padrumbleconfig.isg` | Light/Heavy/Medium rumble presets with durations |
| `camerashakeconfig.isg` | Camera shake effects |
| `objectives.isg` | Progression objective definitions |
| `scheduledquests.isg` | Daily/weekly quest system |
| `ftuesteps.isg` | First-time user experience / onboarding |
| `carousel.isg` | 300+ UI carousel item definitions |
| `gachacontent.isg` | Gift machine / loot system content |
| `fonteffectpreset.isg` | Font rendering effects |
| `portrait_borders.isg` | Player portrait border customization |
| `localisationTRC.isg` | Localization and content rating compliance |
| `zinput.isg` | Input/controller configuration |

### Feature Configs (.ilu files)

#### Scoring and Progression

| File | Controls |
|------|----------|
| `gc_scoring.ilu` | Scoring parameters: max 13,333 pts, on-fire multiplier, kids mode |
| `gc_scoring_camera.ilu` | Camera-based scoring mechanics |
| `gc_scoring_movespace.ilu` | Movement space scoring |
| `gc_jdrank_data.ilu` | 200-level rank system with XP thresholds per level |
| `gc_coop.ilu` | Coop scoring diamond multipliers (0.187 - 3.0) |
| `gc_rating.ilu` | Age rating screens (ESRB, PEGI) |
| `gacha_config.ilu` | Gift machine: 100 pt cost, rarity, thresholds |
| `aliasesObjectives.ilu` | Alias/title unlock conditions |
| `mapsObjectives.ilu` | Map unlock objectives (relevant to Status override) |

#### UI and Menus

| File | Controls |
|------|----------|
| `gc_hud_ui.ilu` | In-game HUD: players, raceline, pictoline, lyrics, gold moves |
| `gc_common_ui.ilu` | Common UI screen layouts |
| `gc_menuassets.ilu` | Menu asset database |
| `gc_menumusics.ilu` | Menu background music |
| `cr_core_navigation.ilu` | Core menu navigation structure |
| `cr_game_mode_selection.ilu` | Game mode selector |
| `cr_lobby.ilu` | Lobby screen |
| `cr_device_selection.ilu` | Input device selection (phone, camera, motion) |
| `cr_dancer_card_edition.ilu` | Dancer card editor |
| `cr_search_symbol.ilu` | Search UI symbols |
| `popups.ilu` | Popup window configs |
| `on_fly_notifications.ilu` | In-game notification system |
| `home_data_config.ilu` | Home screen content layout |
| `home_tips_config.ilu` | Tips/help system |

#### Game Modes

| File | Controls |
|------|----------|
| `cr_kids.ilu` | Kids mode settings |
| `cr_wdf.ilu` | World Dance Floor (online) config |
| `gc_wdf_boss.ilu` | WDF boss challenge data |
| `gr_pause.ilu` | Pause menu options |
| `recap.ilu` | Score recap screen |
| `cr_recap_autodance.ilu` | AutoDance recap |
| `gc_autodance_effects.ilu` | AutoDance visual effects |
| `gc_tutorials.ilu` | Tutorial definitions |

#### Collectibles and Customization

| File | Controls |
|------|----------|
| `collectible_album.ilu` | Sticker album (6 pages, 60+ stickers) |
| `collectible_sticker_items.ilu` | Individual sticker definitions |
| `gc_customizable_item_config.ilu` | Customizable items |
| `gc_item_color_lookup.ilu` | Color palette for items |
| `gc_uplay_rewards.ilu` | Ubisoft account rewards |
| `gc_unlimited_upsell_songlist.ilu` | JD Unlimited song list |
| `gc_redeem_maps.ilu` | Redeemable map content |

---

## 4. JSON Configuration Files

| File | Controls |
|------|----------|
| `alias_db.json` | 150+ player titles/aliases with difficulty colors |
| `playlists.json` | 15 offline playlists with song assignments |
| `gc_carousel_rules.json` | Menu carousel behavior, platform-specific rules, filters |
| `wdf_linear_rewards.json` | 16 WDF online reward tiers |

---

## 5. Other EngineData Directories

| Path | Format | Purpose |
|------|--------|---------|
| `Achievements/RewardsConfig.xml` | XML | Trophy config (48 trophies, 18 languages) |
| `Shaders/Unified/ShaderConfig.xml` | XML | Cross-platform shader compilation |
| `Localisation/Saves/ConsoleSave.json` | JSON | 17-language localization string database |
| `UserConfig/screencapture.xml` | XML | Screenshot capture settings |
| `GameToolPackageTask/*.xml` | XML | Asset packaging and build order |

---

## 6. World/Content Data

| Path | Format | Purpose |
|------|--------|---------|
| `World/SkuScenes/SkuScene_Maps_PC_All.isc` | ISC/XML | Song database: Actor entries for each map + CoverflowSong entries |
| `World/SkuScenes/SkuScene_Maps_NX_All.isc` | ISC/XML | NX platform song database (exists but not used by pipeline) |
| `World/ui/textures/quests/unlimited/*/quest_metadata.json` | JSON | Quest definitions |

---

## 7. Key Gameplay Parameters

### Scoring
- Max song score: 13,333 points
- Star progression: 0-7 stars (Superstar at 11,000, Megastar at 12,000)
- Kids mode has special scoring ratios
- On-fire multiplier for sustained combos

### Rank Progression
- 200 levels with exponential XP scaling
- 7 visual tiers based on level brackets
- Level 1 requires 40 XP, Level 200 requires ~97,436 XP

### Audio
- 25+ audio buses
- Dynamic volume ducking during video/narration
- All game audio at 48kHz sample rate

---

## 8. Modding Notes

- All `.isg` and `.ilu` files are plain-text Lua, directly editable
- JSON and XML files are standard formats, fully editable
- Scoring parameters, rank XP curves, achievement conditions, and playlists can all be modified
- The game references PS4/PS5/Xbox/Switch/Stadia platforms across configs; only PC paths are active
- Resolution can be changed via `config.xml` or `RUNNER.bat`
- `mapsObjectives.ilu` controls map unlock conditions; the pipeline's Status override (`Status = 3`) bypasses these

---

## 9. V2 Installer Behavior and Limitations (Critical)

These points are current V2 behavior and should be treated as operational constraints when using this reference with mod installs.

### Ambient (AMB)
- Intro AMB handling is currently in a temporary mitigation state in V2.
- Intro AMB attempt logic is intentionally disabled globally; silent intro placeholder behavior is expected until redesign/parity validation is completed.
- AMB path resolution remains sensitive to source folder shape and casing conventions.

### Audio/Video Timing
- IPK-derived `videoStartTime` remains approximate by design because source metadata often does not reliably encode lead-in.
- Manual video offset tuning is expected for many IPK maps after installation.
- `installer_settings.json` timing controls (`a_offset`, `v_override`, `marker_preroll_ms`) are still the main global adjustment surface.

### Runtime Dependencies (Required for Full Functionality)
- FFmpeg/FFprobe are required for media conversion/probing paths.
- vgmstream runtime is required for X360/XMA2 decode paths.
- Missing or partial tool availability can produce degraded installs, preview limitations, or fallback behavior.

### Pipeline Context
- V2 supports multiple install input modes (Fetch, HTML, IPK, Batch directory, Manual source folder) and readjust workflows.
- This file remains valid as a config map across those modes, but mode-specific troubleshooting should be read alongside current operator/troubleshooting docs.
