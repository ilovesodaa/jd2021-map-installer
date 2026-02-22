import re

def extract_args():
    with open(r'd:\jd2021pc\jd21\engine\ua_engine.exe', 'rb') as f:
        data = f.read()

    results = []
    
    # ascii
    ascii_strings = re.findall(b'[\x20-\x7E]{5,}', data)
    for s in ascii_strings:
        if b'assert' in s.lower() or b'offline' in s.lower() or b'warning' in s.lower():
            try:
                decoded = s.decode('utf-8')
                if len(decoded) < 50:
                    results.append(decoded)
            except:
                pass
                
    # utf16le
    # pattern: (char \x00){5,}
    utf16_strings = re.findall(b'(?:[\x20-\x7E]\x00){5,}', data)
    for s in utf16_strings:
        try:
            decoded = s.decode('utf-16le')
            if 'assert' in decoded.lower() or 'offline' in decoded.lower() or 'warning' in decoded.lower():
                if len(decoded) < 50:
                    results.append(decoded)
        except:
            pass

    with open('d:/jd2021pc/found_args.txt', 'w', encoding='utf-8') as out:
        for r in sorted(set(results)):
            out.write(r + '\n')
            
if __name__ == "__main__":
    extract_args()
