import os
import shutil
import re

sku_isc = r"d:\jd2021pc\jd21\data\World\SkuScenes\SkuScene_Maps_PC_All.isc"
if os.path.exists(sku_isc):
    with open(sku_isc, "r", encoding="utf-8") as f:
        data = f.read()

    # Remove Actor for "ImAnAlbatraoz"
    data = re.sub(r'\s*<ACTORS NAME="Actor">\s*<Actor[^>]*USERFRIENDLY="ImAnAlbatraoz"[^>]*>.*?<\/ACTORS>\n?', '', data, flags=re.DOTALL)
    # Remove Coverflow for "ImAnAlbatraoz"
    data = re.sub(r'\s*<CoverflowSkuSongs>\s*<CoverflowSong name="ImAnAlbatraoz"[^>]*>.*?<\/CoverflowSkuSongs>\n?', '', data, flags=re.DOTALL)

    with open(sku_isc, "w", encoding="utf-8") as f:
        f.write(data)

bad_dir = r"d:\jd2021pc\jd21\data\World\MAPS\ImAnAlbatraoz"
if os.path.exists(bad_dir):
    shutil.rmtree(bad_dir)

bad_cache = r"d:\jd2021pc\jd21\data\cache\itf_cooked\pc\world\maps\imanalbatraoz"
if os.path.exists(bad_cache):
    shutil.rmtree(bad_cache)

print("Cleanup complete.")
