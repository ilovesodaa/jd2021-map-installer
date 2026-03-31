# Audio Timing, Pre-Roll Silence, and AMB Status (V2)

> **Last Updated:** April 2026 | **Applies to:** JD2021 Map Installer v2

This document explains the UbiArt engine's audio/video synchronization model, the pre-roll silence problem that affects most ported maps, the AMB-based strategy, and IPK-specific audio handling.

> **Critical current-state note (V2):** Intro AMB generation/playback attempts are temporarily disabled globally as a mitigation. The installer currently forces silent intro placeholders rather than generating active intro AMB audio. See Sections 3, 7, and 8.

---

## 1. How the Engine Synchronizes Audio and Video

Every map has a `.trk` (MusicTrack) file that defines the beat grid. The two most critical fields are:

| Field | Type | Meaning |
|---|---|---|
| `videoStartTime` | float (seconds) | Where in the video file beat 0 appears. Negative = video has a pre-roll intro before beat 0. |
| `startBeat` | int | The beat index of the first marker (e.g. `-5` = the first marker is beat -5). |
| `markers` | array (samples @ 48 kHz) | Sample position for each beat marker. For maps with negative `startBeat`, beat 0 is typically at `markers[abs(startBeat)]`. |

The engine couples two behaviors to `videoStartTime`:

1. **Video alignment**: The video player seeks to `videoStartTime` seconds when the map starts. For a negative value like `-2.145`, the video starts 2.145 seconds before beat 0, showing the pre-roll intro frames.

2. **WAV delay**: The engine delays WAV playback by exactly `abs(videoStartTime)` seconds. With `videoStartTime = -2.145`, the WAV does not start playing until `t = 2.145s` from game start.

These two behaviors are **inseparably coupled** through a single parameter. There is no mechanism to set them independently.

This timing model applies across active V2 install/update flows (Fetch, HTML, IPK, Batch, Manual, and readjust) whenever MusicTrack timing is generated, preserved, or re-applied.

---

## 2. The Pre-Roll Silence Problem

For any map where `videoStartTime < 0`, the following happens:

- `t = 0.000s` - Game starts. Video begins playing from the intro frames. **No audio.**
- `t = 2.145s` - WAV begins playing (sample 0 = beat -5 in the song).
- `t ≈ 4.489s` - Beat 0 of the song. Choreography and scoring begin.

The interval from `t=0` to `t=abs(vst)` is inherently silent. The video shows the coach's intro animation but the audio has not started yet. This produces a noticeable silence of typically 1-4 seconds at the start of many maps.

### Why vst=0 Does Not Fix This

Setting `videoStartTime = 0.000000` eliminates the WAV delay and plays audio immediately, but it also eliminates the video pre-roll: the video starts at beat-0 frame rather than at the intro frame. This means:

- The coach's pre-roll animation is skipped (visual desync)
- Pictos and karaoke, which are driven by the video timeline, appear too early relative to the audio
- The only JD2021 map that legitimately uses `vst=0` is JustDance, which also has `startBeat=0` (no pre-roll)

For maps with `startBeat < 0`, forcing `vst=0` breaks the visual timeline. The negative `videoStartTime` value from source metadata should generally be preserved.

---

## 3. AMB Strategy and Current Runtime Policy

The engine loads `SoundComponent` actors from the audio `.isc` at `t=0`, before the WAV delay kicks in. In principle, an ambient actor can play immediately at game start and cover the silence window.

### Intended strategy (design behavior)

The intended intro AMB strategy is:
- Play from `t=0`, covering the pre-roll silence window
- Source audio from the same song asset path used by the main track
- Fade out near the handoff to avoid hard cuts

### Current V2 runtime policy (April 2026)

- Intro AMB attempts are temporarily disabled globally in the installer pipeline.
- Intro AMB WAV outputs are forced to silent placeholders for both Fetch/HTML and IPK flows.
- This is an intentional mitigation while AMB reliability/parity issues are being redesigned.

### Why same-source overlap remains useful theory

When AMB is eventually re-enabled, overlap theory still applies: two phase-coherent sources reading the same audio segment overlap as a louder single source rather than echo/doubling. The design formulas in Sections 5-6 are retained as technical reference for that intended behavior.

---

## 4. Two Sync Variables

The pipeline tracks two independent timing values:

| Variable | Source | Meaning |
|---|---|---|
| `v_override` | `videoStartTime` from `musictrack.tpl.ckd` (or synthesized for IPK) | How far before beat 0 the video file starts. Usually negative. |
| `a_offset` | Marker-based calculation (preferred), `0.0` for IPK maps, or fallback behavior depending on source | How far before beat 0 the audio file starts. Controls audio trimming/padding. |

### HTML/Fetch Maps

For server-fetched maps, both `v_override` and `a_offset` are typically negative. The OGG audio contains the full song and `a_offset` trims it to start at the expected beat alignment.

Marker-based formula for `a_offset`:
```
idx               = abs(startBeat)
marker_preroll_ms = markers[idx] / 48.0 + 85.0   # markers are 48 kHz samples; 85ms = OGG decode latency calibration
a_offset          = -(marker_preroll_ms / 1000.0)
```

`markers[idx]` is the sample position of beat 0 in the audio. Dividing by 48 converts 48 kHz samples to milliseconds.

### IPK Maps (Xbox 360 Binary Mode)

For IPK maps extracted from Xbox 360 archives, handling differs:

1. **`a_offset` is `0.0`** in the current path - decoded XMA2-derived audio is treated as already containing preroll.

2. **`v_override` is synthesized from markers** because many binary CKDs carry `videoStartTime = 0.0`:
   ```
   v_override = -(markers[abs(startBeat)] / 48.0 / 1000.0)
   ```
   No `+85ms` compensation is added here; that calibration applies to OGG trimming logic, not direct video timing.

3. **Video lead-in is not encoded in binary metadata** - synthesized `v_override` only accounts for marker-derived preroll timing. Additional per-map video lead-in must be tuned manually.

### Community Tool Validation

The marker formula `markers[abs(startBeat)] / 48` (milliseconds) is validated by multiple community tools:
- **MediaTool** (JustDanceTools) - uses `markers[abs(startBeat)] / 48` for FFmpeg `-ss`
- **Unity2UbiArt** - uses `markers[abs(startBeat)] / 48` for audio cutting
- **ferris_dancing** - binary CKD parser confirms markers/startBeat/endBeat/videoStartTime structure
- **UBIART-AMB-CUTTER** - adds `+85ms` in its trimming approach (calibration reference)

---

## 5. Timing Formula (Reference for Intended AMB Mode)

> **Status:** Reference/design section. This logic is currently not active in default V2 runtime because intro AMB attempts are globally disabled.

If intro AMB generation is re-enabled, timing is computed in two steps:

**Step 1: Determine total intro window length and any audio delay.**
```
intro_dur   = abs(v_override)      # total silence window = video pre-roll length
audio_delay = max(0, intro_dur - abs(a_offset))
              # if v_override has more pre-roll than a_offset, prepend silence
              # so audio content starts later and aligns with the OGG start
```

**Step 2: Determine audio content duration and fade point.**

*Primary path - marker data available:*
```
audio_content_dur = marker_preroll_ms / 1000.0
fade_start        = audio_delay + audio_content_dur - 0.200
amb_duration      = audio_delay + audio_content_dur
```

*Fallback path - no marker data (or `marker_preroll_ms` is `None`):*
```
audio_content_dur = abs(a_offset) + 1.355
fade_start        = audio_delay + abs(a_offset) + 1.155
amb_duration      = audio_delay + audio_content_dur
```

The `1.355s` fallback tail is intended to absorb WAV scheduling jitter (buffer load + system audio latency).

Example (`v_override = -2.145`, `marker_preroll_ms = 2060`):
```
intro_dur          = 2.145s
a_offset           = -(2060/1000) = -2.060s
audio_delay        = max(0, 2.145 - 2.060) = 0.085s
audio_content_dur  = 2.060s
amb_duration       = 0.085 + 2.060 = 2.145s
fade_start         = 0.085 + 2.060 - 0.200 = 1.945s
```

A `200ms` linear fade-out is applied at `fade_start` to avoid hard-cut handoff artifacts.

---

## 6. AMB File Requirements (Reference)

> **Status:** File shapes below remain relevant for asset compatibility, but intro audio payloads are currently emitted as silent placeholders under the temporary mitigation.

Each intro AMB uses three files under `Audio/AMB/`:

| File | Contents |
|---|---|
| `amb_{mapname}_intro.wav` | PCM 48kHz stereo; currently written as a silent placeholder in default V2 runtime |
| `amb_{mapname}_intro.ilu` | Sound descriptor (`category="amb"`, `playMode=1`, `loop=0`) |
| `amb_{mapname}_intro.tpl` | Actor template that references SoundComponent + `.ilu` |

The actor is referenced from `{MapName}_audio.isc` as a `SoundComponent` actor.

The `.ilu` `volume = 0` field is a dB offset (`0 = unity`), not a mute flag.

---

## 7. Pipeline Integration (Current vs Intended)

The AMB-related pipeline functions remain part of the architecture, but behavior is currently split between design intent and temporary runtime policy.

### Current runtime behavior (April 2026)

1. Intro AMB attempts are gated off globally.
2. Generated/reconciled intro WAVs are forced to silent placeholders.
3. This applies across Fetch/HTML/IPK and interactive re-sync loops.

### Intended behavior after mitigation removal (reference)

When re-enabled, the pipeline is expected to:

1. Reuse existing IPK intro AMB wrappers (`*_intro.tpl.ckd`) and replace placeholder WAV content.
2. Generate missing intro AMB wrappers (`.tpl`/`.ilu`) and inject actor references when absent.
3. Populate eligible pre-roll `SoundSetClip` AMBs from source preroll audio where valid.
4. Continue orphan WAV CKD recovery (synthetic wrappers) before audio population.

Implementation detail: AMB path resolution and folder-case differences (`Audio/AMB` vs `audio/amb`) are handled defensively to avoid broken actor references on mixed-source layouts.

---

## 8. Limitations and Operator Expectations

1. **Intro AMB currently disabled (temporary but active):** Expect silent intro placeholder behavior, not active AMB preroll fill.
2. **IPK video offset remains approximate by design:** marker-derived `v_override` cannot encode per-map video lead-in; manual VIDEO_OFFSET tuning is expected.
3. **Dependency-sensitive behavior:** Missing FFmpeg/FFprobe or vgmstream reduces decode/preview/install reliability, especially for IPK/XMA2 audio paths.
4. **Source-layout variability:** Mixed casing/path layouts and cache-only assets require fallback resolution logic; map-specific edge cases remain possible.

---

## 9. Runtime Dependencies Relevant to Timing

Audio timing and preview/install quality depend on the local toolchain:

1. **FFmpeg / FFprobe** - required for probing/transcoding and timing-sensitive media operations.
2. **vgmstream** - required for robust Xbox 360 XMA2 decode paths used by many IPK maps.
3. **Playwright Chromium** (Fetch mode only) - required for web-fetch workflows, not for pure local/IPK timing math.

If any dependency is missing or partially installed, expected behavior includes decode fallback paths, reduced preview confidence, and higher chance of manual offset correction.
