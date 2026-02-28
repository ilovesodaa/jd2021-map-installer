import sys

def analyze_dtape(filepath):
    print(f"Analyzing {filepath}")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return

    current_clip_type = ""
    clips = []
    current_clip = {}
    
    for line in lines:
        line = line.strip()
        if line.startswith('NAME = "') and 'Clip' in line:
            if current_clip:
                clips.append((current_clip_type, current_clip))
                current_clip = {}
            current_clip_type = line.split('"')[1]
        elif line.startswith('Id = '):
            current_clip['Id'] = int(line.split('=')[1].strip(', '))
        elif line.startswith('TrackId = '):
            current_clip['TrackId'] = int(line.split('=')[1].strip(', '))
        
    if current_clip:
        clips.append((current_clip_type, current_clip))
    
    # Analyze
    ids = [c['Id'] for t, c in clips if 'Id' in c]
    track_ids = [c['TrackId'] for t, c in clips if 'TrackId' in c]
    
    print(f"Total clips parsed: {len(clips)}")
    print(f"Total Ids: {len(ids)}")
    unique_ids = set(ids)
    print(f"Unique Ids: {len(unique_ids)}")
    if len(ids) > len(unique_ids):
        print(f"WARNING: Found {len(ids) - len(unique_ids)} duplicate IDs!")
        
        # Count occurrences of each ID
        id_counts = {}
        for i in ids:
            id_counts[i] = id_counts.get(i, 0) + 1
            
        print("Sample Duplicates [ID]: count")
        dupes = [(k, v) for k, v in id_counts.items() if v > 1]
        for d, count in dupes[:10]:
            types_with_this_id = [t for t, c in clips if c.get('Id') == d]
            print(f"  Id {d}: {count} occurrences in types {types_with_this_id}")
            
    # TrackIds
    unique_tracks = set(track_ids)
    print(f"Unique TrackIds used by clips: {unique_tracks}")
        
    for track in unique_tracks:
        track_types = set([t for t, c in clips if c.get('TrackId') == track])
        print(f"  Track {track} used by: {track_types}")

analyze_dtape(r'd:\jd2021pc\ritmica\TikTok\Timeline\TikTok_TML_Dance.dtape')
analyze_dtape(r'd:\jd2021pc\jd21\data\World\MAPS\Starships\Timeline\Starships_TML_Dance.dtape')
