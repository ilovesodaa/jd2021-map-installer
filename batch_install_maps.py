import subprocess
import sys
import os
import time

maps = [
    ("Albatraoz", r"d:\jd2021pc\MapDownloads\Albatraoz\assets.html", r"d:\jd2021pc\MapDownloads\Albatraoz\nohud.html"),
    ("BadRomance", r"d:\jd2021pc\MapDownloads\BadRomance\assets.html", r"d:\jd2021pc\MapDownloads\BadRomance\nohud.html"),
    ("JustDance", r"d:\jd2021pc\MapDownloads\JustDance\assets.html", r"d:\jd2021pc\MapDownloads\JustDance\nohud.html"),
    ("Rockabye", r"d:\jd2021pc\MapDownloads\Rockabye\assets.html", r"d:\jd2021pc\MapDownloads\Rockabye\nohud.html"),
    ("Starships", r"d:\jd2021pc\MapDownloads\Starships\assets.html", r"d:\jd2021pc\MapDownloads\Starships\nohud.html")
]

processes = []
for name, asset, nohud in maps:
    print(f"\n========================================")
    print(f"Launching installer for {name} in new terminal...")
    print(f"========================================\n")
    # Quote the Python executable path
    python_exe = f'"{sys.executable}"'
    cmd = f'start "Install {name}" cmd /k {python_exe} map_installer.py --map-name {name} --asset-html {asset} --nohud-html {nohud}'
    subprocess.Popen(cmd, shell=True, cwd=r"d:\jd2021pc")

print("\nAll installers launched in separate terminals. Review offsets individually.")
