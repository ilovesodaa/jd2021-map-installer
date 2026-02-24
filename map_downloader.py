import os
import re
import urllib.request
import ssl
import json
import zipfile
import shutil
import argparse
from urllib.parse import urlparse

ssl._create_default_https_context = ssl._create_unverified_context

def extract_urls(html_file):
    with open(html_file, "r", encoding="utf-8") as f:
        html = f.read()
    
    urls = re.findall(r'href="(https?://[^"]+)"', html)
    
    clean_urls = set()
    for url in urls:
        if "discordapp.net" in url: continue
        url = url.replace("&amp;", "&")
        clean_urls.add(url)
    return list(clean_urls)

def get_filename_from_url(url):
    parsed = urlparse(url)
    path = parsed.path
    parts = path.split('/')
    if len(parts) >= 2 and "." in parts[-2]: 
        return parts[-2]
    return parts[-1]

def download_files(urls, download_dir):
    os.makedirs(download_dir, exist_ok=True)
    downloaded = {}
    
    main_scene_zip = None
    gesture_zips = []
    video_url = None
    audio_url = None

    for u in urls:
        if "ULTRA.webm" in u: video_url = u
        elif ".ogg" in u and "AudioPreview" not in u: audio_url = u
        elif "MAIN_SCENE" in u and ".zip" in u:
            if "MAIN_SCENE_NX" in u:
                main_scene_zip = u
            else:
                gesture_zips.append(u)
            
    if not video_url:
        for u in urls:
            if "HIGH.webm" in u: video_url = u; break
            
    if not main_scene_zip and gesture_zips:
        main_scene_zip = gesture_zips.pop(0)
            
    important_urls = []
    if video_url: important_urls.append(video_url)
    if audio_url: important_urls.append(audio_url)
    if main_scene_zip: important_urls.append(main_scene_zip)
    important_urls.extend(gesture_zips)
    
    for u in urls:
        if ".ckd" in u or ".jpg" in u or ".png" in u or ".ad" in u:
            if "discordapp.net" not in u:
                important_urls.append(u)
                
    for url in set(important_urls):
        fname = get_filename_from_url(url)
        # Rename url hash files if missing the name
        if len(fname) == 32 and "." not in fname:
            pass # Keep it, we'll decode later
        
        target = os.path.join(download_dir, fname)
        if not os.path.exists(target):
            print(f"Downloading {fname}...")
            req = urllib.request.Request(url)
            try:
                with urllib.request.urlopen(req) as response:
                    with open(target, "wb") as f:
                        f.write(response.read())
            except Exception as e:
                print(f"Failed to download {fname}: {e}")
        else:
            print(f"{fname} already exists, skipping download.")
        downloaded[fname] = target
        
    return downloaded

def run(map_name, asset_html, nohud_html, jd_dir):
    if not jd_dir:
        jd_dir = os.path.dirname(os.path.abspath(__file__))
    map_dir = os.path.join(jd_dir, map_name)
    download_dir = os.path.join(map_dir, "downloads")
    
    urls1 = extract_urls(asset_html) if os.path.exists(asset_html) else []
    urls2 = extract_urls(nohud_html) if os.path.exists(nohud_html) else []
    all_urls = urls1 + urls2
    
    print(f"Found {len(all_urls)} URLs.")
    downloaded = download_files(all_urls, download_dir)
    print("Download complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-name", required=True)
    parser.add_argument("--asset-html", required=True)
    parser.add_argument("--nohud-html", required=True)
    parser.add_argument("--jd-dir", default=None)
    args = parser.parse_args()
    run(args.map_name, args.asset_html, args.nohud_html, args.jd_dir)
