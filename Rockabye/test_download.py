import urllib.request
import ssl
import sys

ssl._create_default_https_context = ssl._create_unverified_context

url = "https://jdcn-switch.cdn.ubisoft.cn/private/map/Rockabye/Rockabye.ogg/61219e92135ee06339d0b4bc6e6e28e6.ogg?auth=exp=1771743394~acl=/private/map/Rockabye/*~hmac=c8ffeacf755f77aa4718bff279aa55864c1ba8d9c54772b7c08f69726aaab520"

try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as r:
        print("Success! Download would be", len(r.read()), "bytes.")
except Exception as e:
    print("Error:", e)
