import urllib.request
import ssl
import zipfile
import io
import re

ssl._create_default_https_context = ssl._create_unverified_context

html = open(r"d:\jd2021pc\Rockabye\rockabye_asset_mapping.html", "r", encoding="utf-8").read()
# Find the NX zip URL by looking for .zip
urls = re.findall(r'href="(https?://[^"]+\.zip[^"]*)"', html)
nx_zip_url = [u for u in urls if 'MAIN_SCENE_NX.zip' in u]

print("Downloading", nx_zip_url[0])

# Since there's often auth in URL, let's fix replacing &amp;
real_url = nx_zip_url[0].replace("&amp;", "&")

req = urllib.request.Request(real_url)
with urllib.request.urlopen(req) as response:
    data = response.read()

with zipfile.ZipFile(io.BytesIO(data)) as z:
    for name in z.namelist():
        print(name)
