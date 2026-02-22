import os
import shutil
import subprocess

SRC = r"d:\jd2021pc\Starships"
TARGET = r"d:\jd2021pc\jd21\data\World\MAPS\Starships"

mappings = {
    # Video
    "0ac1f08ec9cd2070cb1f70295661efa3.webm": f"{TARGET}\\VideosCoach\\Starships.webm",
    "67913811d9fdd089443181e2672b619e.webm": f"{TARGET}\\VideosCoach\\Starships_MapPreview.webm", # Using ULTRA.vp9 as preview
    
    # Audio
    "80f47be6f8293430ae764027a56847a4.ogg": f"{TARGET}\\Audio\\Starships.ogg",
    "b6ea5be7d5e70cda982f9d35fb6bfeba.ogg": f"{TARGET}\\Audio\\Starships_AudioPreview.ogg",
    
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
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{TARGET}\\Audio\\Starships.ogg", "-ar", "48000", f"{TARGET}\\Audio\\Starships.wav"])
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{TARGET}\\Audio\\Starships_AudioPreview.ogg", "-ar", "48000", f"{TARGET}\\Audio\\Starships_AudioPreview.wav"])

print("Done copying and converting.")
