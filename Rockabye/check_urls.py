import re
import urllib.request
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

with open(r"d:\jd2021pc\Rockabye\rockabye_mapping.html", "r", encoding="utf-8") as f:
    html = f.read()

urls = re.findall(r'href="(https?://[^"]+)"', html)
print(f"Found {len(urls)} links. Checking sizes...")

for url in urls:
    # We only care about media ones
    if "discordapp.net" in url: continue
    
    parts = url.split('/')
    if len(parts) >= 2:
        filename = parts[-2]
    else:
        filename = url.split('/')[-1]
    
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req) as response:
            size = int(response.headers.get("Content-Length", 0))
            print(f"{filename:50} : {size / 1024 / 1024:.2f} MB")
    except Exception as e:
        print(f"{filename:50} : Error {e}")
