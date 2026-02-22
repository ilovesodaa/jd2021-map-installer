import os
import shutil
import subprocess
import argparse

parser = argparse.ArgumentParser(description="Copy and convert Starships media files.")
parser.add_argument(
    "--audio-start-offset",
    type=float,
    default=0.0,
    metavar="SECONDS",
    help=(
        "Shift the audio start relative to the beat grid. "
        "Positive = pad silence at the start (audio starts later). "
        "Negative = trim the start of the file (audio starts earlier). "
        "Use this to align audio beat 0 with video beat 0. "
        "Example: --audio-start-offset -1.901"
    )
)
args = parser.parse_args()

SRC = r"d:\jd2021pc\Starships"
TARGET = r"d:\jd2021pc\jd21\data\World\MAPS\Starships"

mappings = {
    # Video
    "0ac1f08ec9cd2070cb1f70295661efa3.webm": f"{TARGET}\\VideosCoach\\Starships.webm",
    "67913811d9fdd089443181e2672b619e.webm": f"{TARGET}\\VideosCoach\\Starships_MapPreview.webm", # Using ULTRA.vp9 as preview
    
    # Audio
    "80f47be6f8293430ae764027a56847a4.ogg": f"{TARGET}\\Audio\\Starships.ogg",
    # NOTE: Starships_AudioPreview.ogg is intentionally NOT copied here.
    # The engine uses previewEntry/previewLoopStart/previewLoopEnd in the .trk
    # to seek into the main audio for preview. A separate preview audio file
    # is never referenced by any actor, ISC, or scene file.
    
    # Phone Images (non-ckd)
    "6d162ce9e558fb6d4059e9d383112398.jpg": f"{TARGET}\\MenuArt\\textures\\Starships_Cover_Phone.jpg",
    "f62544a48195680424c3b82c4059057d.png": f"{TARGET}\\MenuArt\\textures\\Starships_Coach_1_Phone.png",
    "361e165f9e893979b0aff0de0a89ade8.png": f"{TARGET}\\MenuArt\\textures\\Starships_Cover_1024.png",
    
    # MenuArt CKDs -> Temp location for decode
    "dbe3c08891c1859cc22bd27c962e2268.ckd": f"{TARGET}\\MenuArt\\textures\\Starships_coach_1.tga.ckd",
    "8c69e5b8d670d7f19880388e995ff064.ckd": f"{TARGET}\\MenuArt\\textures\\Starships_cover_generic.tga.ckd",
    "86e08b8e5c89f8389db5723f136b81d7.ckd": f"{TARGET}\\MenuArt\\textures\\Starships_cover_online.tga.ckd",
    "7285efe8d585ac76b882c2115989a4f8.ckd": f"{TARGET}\\MenuArt\\textures\\Starships_cover_albumbkg.tga.ckd",
    "370d94f300a9f5c48d372f3fad0cec8e.ckd": f"{TARGET}\\MenuArt\\textures\\Starships_cover_albumcoach.tga.ckd",
    "440d6ce474051538b9d98b0d0dab2341.ckd": f"{TARGET}\\MenuArt\\textures\\Starships_map_bkg.tga.ckd",
    "650d843e8d21e55a4cd58a17d6588005.ckd": f"{TARGET}\\MenuArt\\textures\\Starships_banner_bkg.tga.ckd",
}

for src_file, dst_path in mappings.items():
    s = os.path.join(SRC, src_file)
    if os.path.exists(s):
        print(f"Copying {s} to {dst_path}")
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(s, dst_path)
    else:
        print(f"Missing {s}")

print("Converting audio to wav (forcing 48kHz to match .trk marker positions)...")
audio_offset = args.audio_start_offset
if audio_offset != 0.0:
    print(f"[INFO] Audio start offset applied: {audio_offset:+.3f}s")
    if audio_offset < 0:
        # Trim: skip the first |offset| seconds of the OGG before converting
        af_filter = f"atrim=start={abs(audio_offset)},asetpts=PTS-STARTPTS"
    else:
        # Pad: add silence at the start before the music begins
        af_filter = f"adelay={int(audio_offset * 1000)}|{int(audio_offset * 1000)},asetpts=PTS-STARTPTS"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-i", f"{TARGET}\\Audio\\Starships.ogg",
                    "-af", af_filter,
                    "-ar", "48000",
                    f"{TARGET}\\Audio\\Starships.wav"])
else:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-i", f"{TARGET}\\Audio\\Starships.ogg",
                    "-ar", "48000",
                    f"{TARGET}\\Audio\\Starships.wav"])
# AudioPreview conversion removed: engine uses main audio + .trk previewEntry seek values.

print("Done copying and converting.")
