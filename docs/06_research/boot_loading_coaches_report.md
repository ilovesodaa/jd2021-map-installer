# Boot Loading Coaches Reference Report

Date: 2026-04-08  
Workspace: JD2021 multi-root

## Objective
Document where boot loading coach textures are referenced, how they are loaded at runtime, and what to change when customizing or extending them.

## Executive Summary
The boot loading coaches are driven by a fixed UI scene and animation chain:

1. Game config registers the BootLoading UI key.
2. BootLoading key points to a specific scene file.
3. That scene file references coach texture files from World/ui/textures/coaches.
4. The scene template links to loop animations that animate coach actors.

For normal customization, replacing the existing 14 files (bootloading_01.tga ... bootloading_14.tga) is the safest approach and requires no config changes.

## Reference Chain

### 1) UI Scene Registration
- File: d:/jd2021pc/jd21/data/EngineData/GameConfig/gc_common_ui.ilu
- Entry:
  - KEY = BootLoading
  - VAL = World/ui/screens/boot_loading/boot_loading.isc

### 2) Runtime Inclusion in GameConfig
- File: d:/jd2021pc/jd21/data/EngineData/GameConfig/gameconfig.isg
- Relevant points:
  - includeReference("EngineData/GameConfig/gc_common_ui.ilu")
  - appendTable(params.JD_GameManagerConfig_Template.uiscenes, common_ui)

This is where BootLoading becomes part of runtime UI scenes.

### 3) Scene-Level Coach Texture Binding
- File: d:/jd2021pc/jd21/data/World/ui/screens/boot_loading/boot_loading.isc
- Actor set includes coach_01 through coach_14.
- Each coach actor has MaterialGraphicComponent texture binding to:
  - world/ui/textures/coaches/bootloading_01.tga ... bootloading_14.tga

### 4) Animation Wiring
- File: d:/jd2021pc/jd21/data/World/ui/screens/boot_loading/boot_loading.tpl
- Tape group includes:
  - loop_coaches -> World/ui/screens/boot_loading/animations/loop_coaches.tape

- File: d:/jd2021pc/jd21/data/World/ui/screens/boot_loading/animations/loop_coaches.tape
- Wraps content tape:
  - world/ui/screens/boot_loading/animations/loop_coaches_content.tape

- File: d:/jd2021pc/jd21/data/World/ui/screens/boot_loading/animations/loop_coaches_content.tape
- Uses actor paths coach_01 ... coach_14 across alpha/translation clips and transitions.

## Current Coach Texture Inventory
- Folder: d:/jd2021pc/jd21/data/World/ui/textures/coaches
- Present files:
  - bootloading_01.tga
  - bootloading_02.tga
  - bootloading_03.tga
  - bootloading_04.tga
  - bootloading_05.tga
  - bootloading_06.tga
  - bootloading_07.tga
  - bootloading_08.tga
  - bootloading_09.tga
  - bootloading_10.tga
  - bootloading_11.tga
  - bootloading_12.tga
  - bootloading_13.tga
  - bootloading_14.tga

## Recommended Customization Paths

### Path A (Recommended): Replace Existing 14 Slots
Use when you only want different artwork, not a larger coach count.

Steps:
1. Replace texture files in place using the exact same filenames.
2. Keep dimensions, alpha behavior, and format compatible with existing TGAs.
3. Test boot flow.

Advantages:
- No edits required in isc/tpl/tape/gameconfig.
- Lowest risk of animation breakage.

### Path B (Advanced): Add More Than 14 Coaches
Use only if you need additional coach actors beyond current slots.

Required edits:
1. Add new coach actors in boot_loading.isc (coach_15, coach_16, etc.).
2. Bind each new actor to a valid texture path in World/ui/textures/coaches.
3. Extend loop_coaches_content.tape to include new actor paths where group clips and transitions are defined.
4. Validate timing and layering to avoid overlap/flicker.

Risks:
- Missing actor path references in tape will cause non-animated or invisible elements.
- Inconsistent Z/depth or alpha curves can create visual artifacts.

## Validation Checklist
After any change, validate:

1. BootLoading screen appears normally with no missing materials.
2. All expected coaches are visible during the loop.
3. No texture fallback to white/blank.
4. No obvious clipping, popping, or alpha flicker.
5. Transition into next screen remains smooth.

## Troubleshooting
- Symptom: Some coaches do not appear.
  - Check actor USERFRIENDLY name in boot_loading.isc matches ActorPaths in loop_coaches_content.tape.

- Symptom: Coach appears static while others animate.
  - Check whether that actor is included in relevant AlphaClip/TranslationClip groups.

- Symptom: Wrong image shown.
  - Check diffuse path in boot_loading.isc points to intended file and spelling matches file name exactly.

## Practical Recommendation
For stability and fast iteration, keep the 14-slot layout and replace only the 14 existing texture files first. Move to actor-count expansion only if the design requirement explicitly needs more than 14 concurrent boot-loading coach assets.
