# Data Formats Reference

Binary and text data formats used by the JD2021 Map Installer pipeline.

---

## Table of Contents

- [CKD (Cooked Data)](#ckd-cooked-data)
- [IPK (UbiArt Archive)](#ipk-ubiart-archive)
- [ISC (Scene Graph)](#isc-scene-graph)
- [TPL (Template)](#tpl-template)
- [ACT (Actor Instance)](#act-actor-instance)
- [TRK (Music Track Timing)](#trk-music-track-timing)
- [DTAPE / KTAPE (Choreography Tapes)](#dtape--ktape-choreography-tapes)
- [TAPE (Cinematic Tape)](#tape-cinematic-tape)
- [STAPE (Sequence Tape)](#stape-sequence-tape)
- [ILU (Sound Descriptor Include)](#ilu-sound-descriptor-include)
- [SFI (Sound Format Info)](#sfi-sound-format-info)
- [MPD (DASH Manifest)](#mpd-dash-manifest)
- [WAV Audio Requirements](#wav-audio-requirements)
- [Installer Settings JSON](#installer-settings-json)
- [installer_paths.json](#installer_pathsjson)

---

## Binary Formats

### CKD (Cooked Data)

CKD is UbiArt's cooked asset container format. Its internal payload varies
depending on the asset type.

**Header layout (44 bytes):**

| Offset | Size | Description |
|--------|------|-------------|
| 0-3 | 4 bytes | Magic: `\x00\x00\x00\x09` |
| 4-7 | 4 bytes | `TEX` marker (present for texture assets) |
| 8-43 | 36 bytes | Remaining header data |

**Constants:**

```
CKD_HEADER_SIZE = 44
CKD_MAGIC       = b'\x00\x00\x00\x09'
TEX_MAGIC       = b'TEX'
NVFD_MAGIC      = b'\x44\x46\x76\x4E'
```

**Texture CKD files** contain one of two payloads after the 44-byte header:

- **Switch textures (XTX):** identified by the NvFD magic `\x44\x46\x76\x4E`
  at the start of the payload.
- **PC textures (DDS):** identified by the `DDS ` magic at the start of the
  payload.

**Non-texture CKD files** (`.tpl.ckd`, `.tape.ckd`, etc.) are plaintext JSON
with null-byte padding. They are loaded via `load_ckd_json()`, which strips
`\x00` bytes and leading/trailing whitespace, then parses the result as UTF-8
JSON.

---

### IPK (UbiArt Archive)

IPK is UbiArt's package archive format. All multi-byte integers are
**big-endian**.

**Magic bytes:** `b'\x50\xEC\x12\xBA'`

**Header structure:**

| Field | Type | Description |
|-------|------|-------------|
| magic | uint32 | `0x50EC12BA` |
| version | uint32 | Archive version |
| unknown | uint32 | Reserved / unknown field |
| file_count | uint32 | Number of entries in the archive |

**Entry structure (per file):**

| Field | Type | Description |
|-------|------|-------------|
| offset | uint64 | Byte offset of file data within the archive |
| size | uint32 | Uncompressed size |
| compressed_size | uint32 | Compressed size (0 or equal to size if uncompressed) |
| timestamp | uint32 | File timestamp |
| crc | uint32 | CRC checksum |
| filename_length | uint32 | Length of the filename string |
| filename | bytes | Filename (length determined by filename_length) |

**Decompression strategy:** For each compressed entry the pipeline attempts
decompression in the following order:

1. **zlib** -- try first.
2. **lzma** -- fall back if zlib raises an error.
3. **raw copy** -- treat data as uncompressed if both fail.

**Security:** Path traversal protection is enforced. Any entry whose filename
contains `..` is rejected.

---

## Text / Structured Formats

### ISC (Scene Graph)

ISC files are XML documents that describe a UbiArt scene graph.

**Key requirements for JD2021:**

- `ENGINE_VERSION` attribute must be `"280000"`.
- Contains `ACTORS` elements that link to `.tpl` (template) and `.act` (actor
  instance) files.
- `sceneConfigs` elements hold scene-level configuration.

**Common scene roles:**

| Role | Description |
|------|-------------|
| MAIN_SCENE | Top-level map scene |
| audio | Audio scene graph |
| timeline | Timeline / sequencing |
| cinematics | Cinematic sequences |
| menuart | Menu artwork and UI |
| video | Video playback |
| autodance | Autodance mode |

---

### TPL (Template)

TPL files use **Lua table syntax**.

**Structure:**

```lua
params = {
    Actor_Template = {
        COMPONENTS = {
            -- component definitions
        }
    }
}
```

Templates define the reusable component layout for an actor. Common template
types include SongDesc, MusicTrack, Dance/Karaoke tapes, AMB sounds, and
autodance descriptors.

---

### ACT (Actor Instance)

ACT files use **Lua table syntax**.

**Structure:**

```lua
params = {
    Actor = {
        COMPONENTS = {
            -- instance-specific component data
        }
        -- references the parent TPL file
    }
}
```

An ACT file instantiates a TPL template with concrete data (paths, overrides,
runtime values).

---

### TRK (Music Track Timing)

TRK files use **Lua table syntax** and define the rhythmic structure of a song.

**Structure:**

```lua
structure = {
    MusicTrackStructure = {
        markers = {
            { VAL = <sample_position> },
            -- ...
        },
        startBeat = <int>,       -- typically negative, e.g. -5
        endBeat = <int>,
        videoStartTime = <float>, -- seconds, typically negative
        previewEntry = <float>,   -- beat index for song preview
    }
}
```

**Important:** All `markers` positions are in samples at **48 kHz**. The
`startBeat` value is usually negative to allow a pre-roll before beat zero.

---

### DTAPE / KTAPE (Choreography Tapes)

DTAPE (dance tape) and KTAPE (karaoke tape) files use **Lua table syntax**.

**Structure:**

```lua
params = {
    Clips = {
        -- array of timed clip events
    }
}
```

**Dance tape (.dtape) clip types:**

- `MotionClips` -- choreography move definitions.
- `PictogramClips` -- pictogram display triggers.
- `GoldEffectClips` -- gold move highlight effects.

**Karaoke tape (.ktape) clip types:**

- `KaraokeClips` -- lyric display events with timing.

**Timing resolution:** 24 ticks per beat.

---

### TAPE (Cinematic Tape)

TAPE files use **Lua table syntax** and are structurally similar to dtape/ktape
but target animation and visual properties rather than gameplay events.

**Common clip types:**

| Clip Type | Description |
|-----------|-------------|
| AlphaClip | Opacity animation |
| RotationClip | Rotation animation |
| TranslationClip | Position animation |
| SizeClip | Scale animation |

**Curve keys** use the `vector2dNew(x, y)` format for keyframe values.

**Actor resolution:** `ActorPaths` are resolved from `ActorIndices` in the
containing scene graph.

---

### STAPE (Sequence Tape)

STAPE files contain BPM and time-signature data for each section of a song.

These files are converted from CKD-wrapped JSON via `json_to_lua.py` into Lua
table syntax.

---

### ILU (Sound Descriptor Include)

ILU files use **Lua table syntax** and define ambient sound descriptors.

**Structure:**

```lua
appendTable({
    SoundDescriptor_Template = {
        name = "<descriptor_name>",
        volume = <float>,
        category = "<category>",
        files = {
            -- list of audio file paths
        }
    }
})
```

Used for AMB (ambient) sounds within a map.

---

## XML Metadata Formats

### SFI (Sound Format Info)

SFI files are single-element XML documents describing audio encoding metadata.

**Example:**

```xml
<SoundFormatInfo Format="PCM" IsStreamed="1" IsMusic="1" Platform="PC" />
```

---

### MPD (DASH Manifest)

MPD files follow the MPEG-DASH manifest schema, adapted for UbiArt local
playback.

**Namespace (must be capitalized exactly as shown):**

```
urn:mpeg:DASH:schema:MPD:2011
```

**Profile:**

```
urn:webm:dash:profile:webm-on-demand:2012
```

**BaseURL format:**

```
jmcs://jd-contents/[MapName]/[MapName].webm
```

The `jmcs://` scheme forces the engine to use a local content fallback instead
of fetching from a remote server.

---

## Audio Requirements

### WAV Audio

All WAV audio files used by the pipeline must meet the following requirements:

| Property | Required Value |
|----------|---------------|
| Sample rate | 48000 Hz (48 kHz) |
| Format | PCM |
| Channels | Stereo (2 channels) |

The 48 kHz sample rate is mandatory because TRK marker positions are expressed
in samples at that rate.

**Trimming:** The WAV is trimmed by `abs(a_offset)` seconds from the start of
the source OGG file during conversion.

---

## Configuration Files

### Installer Settings JSON

Located at `installer_settings.json` in the project root. See [MAP_CONFIG_FORMAT.md](MAP_CONFIG_FORMAT.md) for full documentation.

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| skip_preflight | bool | false | Skip pre-flight checks on startup |
| suppress_offset_notification | bool | false | Don't show offset refinement popup after install |
| auto_cleanup_downloads | bool | false | Auto-delete intermediates after Apply & Finish |
| default_quality | string | "ultra_hd" | Default video quality tier |

---

### installer_paths.json

Caches game-path discovery results so the installer does not need to re-scan on
every launch.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| jd21_dir | string | Root directory of the JD2021 installation |
| sku_scene | string | Full path to `SkuScene_Maps_PC_All.isc` |

**Validation on load:** The `sku_scene` file must still exist on disk. If the
file is missing the cached paths are discarded and discovery runs again.
