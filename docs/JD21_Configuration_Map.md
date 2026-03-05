# Just Dance 2021 PC - Complete Configuration File Map

## 1. Top-Level Configuration

| File | Format | Purpose |
|------|--------|---------|
| `jd21/data/config.xml` | XML | **Main game config** - resolution (1280x720), fullscreen, safe frame, XInput requirement |
| `jd21/engine/RUNNER.bat` | BAT | **Startup parameters** - resolution override (1920x1080), language, debug flags |
| `jd21/engine/projectinfo.xml` | XML | Project ID (JD2021_TU1), branch info |
| `jd21/engine/bloomberg_settings.ini` | INI | Crash reporting servers, logging level, build numbers |
| `installer_paths.json` | JSON | Install directory paths, SKU scene reference |
| `installer_settings.json` | JSON | Global installer settings: default video quality, audio offset, and other defaults |

## 2. EngineData/GameConfig - Lua-Based Configs (84 files)

All these files are **plain-text Lua table syntax** and editable with any text editor. `gameconfig.isg` is the master hub that includes everything else.

### Core Gameplay (.isg files - 17)

| File | Controls |
|------|----------|
| `gameconfig.isg` | Master config - includes all subsystem configs |
| `quickplayrules.isg` | Difficulty sequencing, song selection rules, coach matching |
| `achievements.isg` | 35 achievements across all platforms (Xbox, PS4, Switch, PC) |
| `soundconfig.isg` | Full audio bus system (25+ buses, 2700 lines), ducking, limiters |
| `vibration.isg` | 28 HD Rumble effects for controllers |
| `padrumbleconfig.isg` | Light/Heavy/Medium rumble presets with durations |
| `camerashakeconfig.isg` | 7+ camera shake effects (Quake1-3, etc.) |
| `objectives.isg` | Progression objective definitions |
| `scheduledquests.isg` | Daily/weekly quest system |
| `ftuesteps.isg` | First-time user experience / onboarding |
| `carousel.isg` | 300+ UI carousel item definitions |
| `gachacontent.isg` | Gift machine / loot system content |
| `fonteffectpreset.isg` | Font rendering effects |
| `portrait_borders.isg` | Player portrait border customization |
| `localisationTRC.isg` | Localization & content rating compliance |
| `zinput.isg` | Input/controller configuration |

### Feature Configs (.ilu files - 67+)

#### Scoring & Progression

| File | Controls |
|------|----------|
| `gc_scoring.ilu` | Scoring params: max 13,333 pts, on-fire multiplier, kids mode |
| `gc_scoring_camera.ilu` | Camera-based scoring mechanics |
| `gc_scoring_movespace.ilu` | Movement space scoring |
| `gc_jdrank_data.ilu` | **200-level rank system** with XP thresholds per level |
| `gc_coop.ilu` | Coop scoring diamond multipliers (0.187 - 3.0) |
| `gc_rating.ilu` | Age rating screens (ESRB, PEGI) |
| `gacha_config.ilu` | Gift machine: 100 pt cost, rarity, thresholds |
| `aliasesObjectives.ilu` | Alias/title unlock conditions |
| `mapsObjectives.ilu` | Map unlock objectives |

#### UI & Menus

| File | Controls |
|------|----------|
| `gc_hud_ui.ilu` | In-game HUD (players, raceline, pictoline, lyrics, gold moves) |
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

#### Collectibles & Customization

| File | Controls |
|------|----------|
| `collectible_album.ilu` | Sticker album (6 pages, 60+ stickers) |
| `collectible_sticker_items.ilu` | Individual sticker definitions |
| `gc_customizable_item_config.ilu` | Customizable items |
| `gc_item_color_lookup.ilu` | Color palette for items |
| `gc_uplay_rewards.ilu` | Ubisoft account rewards |
| `gc_unlimited_upsell_songlist.ilu` | JD Unlimited song list |
| `gc_redeem_maps.ilu` | Redeemable map content |

## 3. EngineData/GameConfig - JSON Files (4)

| File | Controls |
|------|----------|
| `alias_db.json` | 150+ player titles/aliases with difficulty colors |
| `playlists.json` | 15 offline playlists with song assignments |
| `gc_carousel_rules.json` | Menu carousel behavior, platform-specific rules, filters |
| `wdf_linear_rewards.json` | 16 WDF online reward tiers |

## 4. Other EngineData Directories

| Directory | Format | Purpose |
|-----------|--------|---------|
| `Achievements/RewardsConfig.xml` | XML | PS4 trophy config (48 trophies, 18 languages) |
| `Shaders/Unified/ShaderConfig.xml` | XML | Cross-platform shader compilation (DX, Vulkan, NX, Orbis, Prospero) |
| `Localisation/Saves/ConsoleSave.json` | JSON | 17-language localization string database |
| `UserConfig/screencapture.xml` | XML | Screenshot capture settings |
| `UserConfig/capturevideousingfraps.xml` | XML | FRAPS video capture automation |
| `GameToolPackageTask/*.xml` | XML | Asset packaging and build order (5 files) |
| `ActorTemplates/` | Binary .tpl | Actor/entity templates |
| `Sound/` | Various | Audio engine configs |
| `LightPresets/` | Various | Lighting environment presets |

## 5. World/Content Data

| Path | Format | Purpose |
|------|--------|---------|
| `World/ui/textures/quests/unlimited/*/quest_metadata.json` | JSON | 28 quest definitions (title, locked status, song playlist) |
| `World/AUDIO/Music/*.xml` | XML | Audio track timing, sample rate (48kHz), markers |
| `World/SkuScenes/SkuScene_Maps_PC_All.isc` | ISC | Scene definitions for PC map loading |
| `World/_COMMON/Graphic_Component_Templates/` | TPL | Visual component templates |

## 6. Key Gameplay Systems (Details)

### Scoring System
- Max song score: 13,333 points
- Star progression: 0-7 stars (Superstar @ 11,000, Megastar @ 12,000)
- Kids mode has special scoring ratios and charity mechanics
- "On-fire" mode multiplier for sustained combos

### Achievement System (35 achievements)
- Play progression: Play 3, 25 songs in QuickPlay mode
- Score milestones: Superstar/Megastar ranks on songs
- Skill challenges: Perfect combos, gold moves, "good" or better accuracy
- Endurance: 7-day streak in daily challenges
- Collectibles: Skins (10, 20), stickers (60, all), gift machine rewards

### Rank Progression
- 200 levels with exponential XP scaling
- 7 visual tiers based on level brackets
- Progression from Level 1 (40 XP) to Level 200 (~97,436 XP)

### Vibration/Haptics
- 28 HD Rumble effects (BigPulse, goldmove effects, kicks, snares)
- Pad rumble: Light/Heavy with durations (0.1-1.0 seconds)
- Intensity levels: 0.0-1.0 scale

### Audio Mixing
- 25+ audio buses including: MUSIC, OFFLINE_MUSIC, ONLINE_MUSIC, HUD, CROWD, WDF_CROWD
- Dynamic volume ducking (lowering music during video/narration)
- Fade curves and limiters for audio instance management

### QuickPlay Rules
- Enforces difficulty progression (Easy start)
- Prevents consecutive extreme/intense difficulties
- Promotes never-played songs
- Matches coach count to player count

### Multiplayer (Coop)
- Scoring diamonds scale: 0.187-3.0 based on performance tiers
- Max 4 local or 10 online players
- Special coop feedback HUD

### Progression Systems
- Objectives: Play X songs, launch from search tab, gather stars
- Daily quests with 7+ day streak rewards
- Map/avatar/sticker unlocks via objectives
- FTUE (First-Time User Experience) with 3+ onboarding steps

### Gacha/Loot System
- Cost: 100 JD currency per roll
- Thresholds: Triggers after 4 maps (skip once) or 7 maps (skip more)
- Max 9 plays before guaranteed map reward
- Only "Normal" rarity in 2021 version

### Game Modes
- Kids Mode (simplified mechanics)
- QuickPlay (randomized song selection)
- Exposition (career/story mode)
- World Dance Floor (online battles/tournaments)
- AutoDance (auto-choreography playback)
- Sweat Mode (fitness tracking with calories)

## 7. Modding-Relevant Notes

- **All `.isg` and `.ilu` files are plain-text Lua** - directly editable, no decompilation needed
- **JSON and XML files** are standard formats - fully editable
- **`.tpl` and `.isc` files** are binary/structured - may need Ubisoft-specific tools
- **Scoring** can be tuned (max 13,333 pts, star thresholds, on-fire multiplier)
- **Rank progression** XP curve is fully defined across 200 levels
- **Achievement conditions** are text-editable
- **Playlists** can be modified to add/remove/reorder songs
- **Audio mixing** is highly configurable (25+ buses, volume, effects)
- **Resolution/fullscreen** via `config.xml` or `RUNNER.bat`
- **Gacha system** costs and thresholds are tunable
- **Quest playlists** can be remapped to different songs
- **The game references PS4/PS5/Xbox/Switch/Stadia** platforms across configs - only PC paths are active
