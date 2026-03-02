# Audio Timing & Pre-Roll Silence

This document explains the UbiArt engine's audio/video synchronization model, the pre-roll silence problem that affects most ported maps, and the AMB-based solution implemented in `generate_intro_amb`.

---

## 1. How the Engine Synchronizes Audio and Video

Every map has a `.trk` (MusicTrack) file that defines the beat grid. The two most critical fields are:

| Field | Type | Meaning |
|---|---|---|
| `videoStartTime` | float (seconds) | Where in the video file beat 0 appears. Negative = video has a pre-roll intro before beat 0. |
| `startBeat` | int | The beat index of the first marker (e.g. `-5` = the first marker is beat -5). |
| `markers` | array (samples @ 48kHz) | Sample position for each beat. Marker 0 always corresponds to sample 0 of the WAV. |

The engine couples two behaviors to `videoStartTime`:

1. **Video alignment**: The video player seeks to `videoStartTime` seconds when the map starts. For a negative value like `-2.145`, the video starts 2.145 seconds before beat 0 — showing the pre-roll intro frames.

2. **WAV delay**: The engine delays WAV playback by exactly `abs(videoStartTime)` seconds. With `videoStartTime = -2.145`, the WAV does not start playing until `t = 2.145s` from game start.

These two behaviors are **inseparably coupled** through a single parameter. There is no mechanism to set them independently.

---

## 2. The Pre-Roll Silence Problem

For any map where `videoStartTime < 0`, the following happens:

- `t = 0.000s` — Game starts. Video begins playing from the intro frames. **No audio.**
- `t = 2.145s` — WAV begins playing (sample 0 = beat -5 in the song).
- `t ≈ 4.489s` — Beat 0 of the song. Choreography and scoring begin.

The interval from `t=0` to `t=abs(vst)` is inherently silent. The video shows the coach's intro animation but the audio hasn't started yet. This produces a noticeable silence of typically 1–4 seconds at the start of every map.

### Why vst=0 Does Not Fix This

Setting `videoStartTime = 0.000000` eliminates the WAV delay and plays audio immediately — but it also eliminates the video pre-roll: the video starts at beat-0 frame rather than at the intro frame. This means:

- The coach's pre-roll animation is skipped (visual desync)
- Pictos and karaoke, which are driven by the video timeline, appear 2+ seconds early relative to the audio
- The only JD2021 map that legitimately uses `vst=0` is JustDance, which also has `startBeat=0` — no pre-roll at all

For any map with `startBeat < 0`, `vst=0` breaks the visual timeline. The negative `videoStartTime` value from the original JDU metadata is correct and must be preserved.

---

## 3. The AMB Solution

The engine loads `SoundComponent` actors from the audio `.isc` at `t=0`, before the WAV delay kicks in. An ambient sound actor pointing to a WAV file will start playing **immediately at game start**, regardless of `videoStartTime`.

The solution is to generate an intro AMB that:
- Plays from `t=0`, covering the silence window
- Sources its audio from the same OGG as the main WAV
- Fades out gracefully near the end

### Why Same-Source Overlap Is Inaudible

At `t=abs(vst)` the main WAV begins playing. For a brief window, both the AMB and the WAV are playing simultaneously. Both are sourced from the same OGG file. At any time `t` in the overlap window:

- AMB is playing `OGG[t]` (started at `t=0`, now at position `t` in the OGG)
- WAV is playing `OGG[abs(vst) + (t - abs(vst))] = OGG[t]` (started at `t=abs(vst)` from sample `OGG[abs(vst)]`, now also at position `t`)

Both signal sources are **phase-coherent identical content**. The overlap sounds like a single audio source at slightly elevated volume — not an echo, not a doubling artifact.

When the AMB ends, the WAV is already carrying the audio seamlessly.

---

## 4. Two Sync Variables

The pipeline tracks two independent timing values:

| Variable | Source | Meaning |
|---|---|---|
| `v_override` | `videoStartTime` from `musictrack.tpl.ckd` | How far before beat 0 the video file starts. Always negative (e.g., `-2.145`). |
| `a_offset` | Marker-based calculation (preferred) or equals `v_override` (fallback) | How far before beat 0 the OGG file starts. Always negative. |

These were previously assumed to be equal — they usually are, but marker-based timing can produce a different (more accurate) `a_offset` value.

The marker-based formula for `a_offset`:
```
idx              = abs(startBeat)
marker_preroll_ms = markers[idx] / 48.0 + 85.0   # 85ms = OGG codec decode latency calibration
a_offset          = -(marker_preroll_ms / 1000.0)
```

`markers[idx]` is the sample position (at 48kHz) of the first beat. Dividing by 48 converts to milliseconds. The 85ms constant compensates for OGG decode latency that would otherwise cause a perceived early start.

When `a_offset` equals `v_override`, the two streams are perfectly symmetric and no extra adjustment is needed. When they differ, the intro AMB must bridge the gap (see Section 4 below).

---

## 5. Timing Formula

The intro AMB is generated in two steps:

**Step 1: Determine the total intro window length and any audio delay.**
```
intro_dur   = abs(v_override)      # Total silence window = video pre-roll length
audio_delay = max(0, intro_dur - abs(a_offset))
              # If v_override has more pre-roll than a_offset, prepend silence
              # so the audio content starts later and aligns with the OGG start
```

**Step 2: Determine the audio content duration and fade point.**

*Primary path — marker data available:*
```
audio_content_dur = marker_preroll_ms / 1000.0
fade_start        = audio_delay + audio_content_dur - 0.200
amb_duration      = audio_delay + audio_content_dur
```

*Fallback path — no marker data (or marker_preroll_ms is None):*
```
audio_content_dur = abs(a_offset) + 1.355
fade_start        = audio_delay + abs(a_offset) + 1.155
amb_duration      = audio_delay + audio_content_dur
```

The 1.355s tail in the fallback covers engine WAV scheduling jitter (the WAV does not start at exactly `t=abs(vst)` — the engine needs time to buffer the main audio file before playback begins). It was empirically derived: a 100ms tail still produced an audible gap; a 3.5s AMB with no fade played seamlessly. The tail covers both buffer-loading delay for the ~30MB main WAV and OS audio pipeline latency.

For Albatraoz example assuming `v_override = -2.145`, `marker_preroll_ms = 2060ms`:
```
intro_dur          = 2.145s
a_offset           = -(2060/1000) = -2.060s
audio_delay        = max(0, 2.145 - 2.060) = 0.085s   # silence prepend
audio_content_dur  = 2.060s
amb_duration       = 0.085 + 2.060 = 2.145s
fade_start         = 0.085 + 2.060 - 0.200 = 1.945s
```

**200ms linear fade-out** is always applied at `fade_start` to prevent a hard-cut volume snap when the AMB ends.

If a map behaves differently on significantly different hardware, the 1.355s fallback tail constant can be increased. Shortening it below ~1.0s risks reintroducing a gap.

---

## 6. AMB File Requirements

Each intro AMB consists of three files in `Audio/AMB/`:

| File | Contents |
|---|---|
| `amb_{mapname}_intro.wav` | PCM 48kHz stereo, duration = `audio_delay + audio_content_dur` (see Section 5), 200ms fade-out |
| `amb_{mapname}_intro.ilu` | Sound descriptor: `category="amb"`, `playMode=1`, `loop=0` |
| `amb_{mapname}_intro.tpl` | Actor template: `includeReference` to SoundComponent and the `.ilu` |

The actor is referenced from `{MapName}_audio.isc` as a `SoundComponent` actor, placed after the MusicTrack and sequence actors.

The `.ilu` `volume = 0` field is a **dB offset** (0 = unity gain), not a mute flag.

---

## 7. Pipeline Integration

`generate_intro_amb` and `extract_amb_audio` in `map_installer.py` handle all AMB cases:

**Case 1 — Map has existing intro AMB from IPK** (`*_intro.tpl.ckd` found in extracted archive):
- IPK processing generates the `.tpl`/`.ilu` and creates a silent placeholder WAV
- `generate_intro_amb` finds the `*_intro.wav` placeholder and overwrites it with real content
- No new files created; no ISC changes needed

**Case 2 — Map has no AMB from IPK**:
- `generate_intro_amb` creates `amb_{mapname}_intro.tpl`, `.ilu`, and `.wav` from scratch
- Injects the AMB actor into `{MapName}_audio.isc` (only if not already present)

**Case 3 — `a_offset >= 0`** (no pre-roll silence):
- Function returns immediately for generation
- Any previously generated `*_intro.wav` is silenced (replaced with 0.1s silence) to prevent double-audio on re-runs

**Case 4 — SoundSetClip AMBs from mainsequence tape**:
- Some maps reference additional AMB clips in their mainsequence tape (clips with `StartTime <= 0`)
- `extract_amb_audio` scans these clips and overwrites their placeholder WAVs with real audio from the OGG pre-roll, as long as the placeholder is smaller than 50KB (which silent stubs always are)
- This applies marker-based preroll duration (with 200ms fade) when available, otherwise falls back to `abs(a_offset) + 1.355s`

The functions are called after every `convert_audio` invocation, including all interactive sync loop options, so all AMB files automatically stay consistent if timing is adjusted.

---

## 8. Limitations

- The 1.355s fallback tail is system-derived. On hardware with exceptionally high WAV scheduling latency (>1s), the gap may still be audible. The marker-based primary path does not have this problem since its timing is derived from the actual audio data, not a heuristic.
- Maps where the original JDU AMB intro references a separate audio asset (not the main OGG) will have that asset replaced by a clip from the main OGG. This is acceptable since JDU-hosted AMB WAV files are not downloadable by this pipeline.
- Background AMB sounds (SoundSetClips with `StartTime > 0`) remain as silent placeholders since they require mid-song audio not present in the pre-roll. Only SoundSetClips with `StartTime <= 0` are populated with real audio (see Case 4).
