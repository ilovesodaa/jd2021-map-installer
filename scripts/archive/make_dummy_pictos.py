import os
import re
from PIL import Image

tape_path = r"d:\jd2021pc\jd21\data\World\MAPS\Starships\Timeline\Starships_TML_Dance.dtape"
pictos_dir = r"d:\jd2021pc\jd21\data\World\MAPS\Starships\Timeline\pictos"

def main():
    os.makedirs(pictos_dir, exist_ok=True)
    
    with open(tape_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find all picto paths like "world/maps/starships/timeline/pictos/abc.png"
    matches = re.findall(r'pictos/([^"\']+\.png)', content, re.IGNORECASE)
    unique_pictos = set(matches)
    
    print(f"Found {len(unique_pictos)} unique picto references in TML_Dance.dtape")
    
    generated = 0
    for picto_name in unique_pictos:
        picto_path = os.path.join(pictos_dir, picto_name)
        if not os.path.exists(picto_path):
            # Create a 1x1 transparent PNG
            img = Image.new('RGBA', (1, 1), color=(0, 0, 0, 0))
            img.save(picto_path)
            print(f"Created missing picto: {picto_name}")
            generated += 1
            
    # Also just in case, explicitly create the ones from the error log 
    # if they didn't match the regex for some reason
    error_pictos = [
        "rotatearmr_f.png",
        "wait_p.png",
        "view_f.png",
        "rotatearml_f.png",
        "pushpushr_f_shake.png"
    ]
    for p in error_pictos:
        picto_path = os.path.join(pictos_dir, p)
        if not os.path.exists(picto_path):
            img = Image.new('RGBA', (1, 1), color=(0, 0, 0, 0))
            img.save(picto_path)
            print(f"Created missing fallback picto: {p}")
            generated += 1
            
    print(f"Total dummy pictos generated: {generated}")

if __name__ == '__main__':
    main()
