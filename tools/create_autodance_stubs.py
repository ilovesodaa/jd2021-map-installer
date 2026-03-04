"""
Create Autodance Stubs for JD2021 PC Maps.

Generates the native Autodance camera logic (.act / .isc / .tpl) files 
with full recording/video structures and FX parameters, ready to be 
populated with real converted data.

Usage:
    python tools/create_autodance_stubs.py --map-name MapName --output path/to/output
"""

import argparse
import os
import sys

def write_autodance_stubs(target_dir, map_name):
    """Write Autodance ISC, TPL, and ACT stub files."""
    ad_dir = os.path.join(target_dir, "autodance")
    os.makedirs(ad_dir, exist_ok=True)
    
    # 1. Autodance.isc
    isc_path = os.path.join(ad_dir, f"{map_name.lower()}_autodance.isc")
    
    isc_content = f"""params=
{{
\tNAME="Scene",
\tScene=
\t{{
\t\tACTORS=
\t\t{{
\t\t\t{{
\t\t\t\tVAL=
\t\t\t\t{{
\t\t\t\t\tUSERFRIENDLY="{map_name}_Autodance",
\t\t\t\t\tISENVIRONMENT=0,
\t\t\t\t\tINSTANCEDATA=
\t\t\t\t\t{{
\t\t\t\t\t\tNAME="Actor",
\t\t\t\t\t\tActor=
\t\t\t\t\t\t{{
\t\t\t\t\t\t\tLUA=
\t\t\t\t\t\t\t{{
\t\t\t\t\t\t\t\t"world/maps/{map_name.lower()}/autodance/{map_name.lower()}_autodance.act"
\t\t\t\t\t\t\t}}
\t\t\t\t\t\t}}
\t\t\t\t\t}}
\t\t\t\t}}
\t\t\t}}
\t\t}}
\t}}
}}"""
    with open(isc_path, "w", encoding="utf-8") as f:
        f.write(isc_content)

    # 2. Autodance.act
    act_path = os.path.join(ad_dir, f"{map_name.lower()}_autodance.act")
    act_content = f"""params=
{{
\tNAME="Actor",
\tActor=
\t{{
\t\tLUA=
\t\t{{
\t\t\t"world/maps/{map_name.lower()}/autodance/{map_name.lower()}_autodance.tpl"
\t\t}}
\t}}
}}"""
    with open(act_path, "w", encoding="utf-8") as f:
        f.write(act_content)

    # 3. Autodance.tpl (Stub)
    tpl_path = os.path.join(ad_dir, f"{map_name.lower()}_autodance.tpl")
    
    # Only write if it doesn't exist or is very small
    if not os.path.isfile(tpl_path) or os.path.getsize(tpl_path) < 1024:
        tpl_content = """params=
{
\tNAME="Actor_Template",
\tActor_Template=
\t{
\t\tCOMPONENTS=
\t\t{
\t\t\t{
\t\t\t\tNAME="AutodanceComponent_Template",
\t\t\t\tAutodanceComponent_Template=
\t\t\t\t{
\t\t\t\t\tautodanceFXToPlay="FX_Autodance_Save",
\t\t\t\t\trecordParams=
\t\t\t\t\t{
\t\t\t\t\t\titems=
\t\t\t\t\t\t{
\t\t\t\t\t\t}
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t}
\t}
}"""
        with open(tpl_path, "w", encoding="utf-8") as f:
            f.write(tpl_content)
        print(f"[OK] {map_name.lower()}_autodance.tpl (stub generated)")
    else:
        print(f"[SKIP] {map_name.lower()}_autodance.tpl (already populated)")

    print(f"[OK] {map_name.lower()}_autodance.isc")
    print(f"[OK] {map_name.lower()}_autodance.act")
    return True

def main():
    parser = argparse.ArgumentParser(
        description="Generate native Autodance camera logic (.act / .isc / .tpl) stubs.")
    parser.add_argument("--map-name", required=True, help="Map codename (e.g. Starships)")
    parser.add_argument("--output", required=True, help="Output directory to create the autodance folder in")

    args = parser.parse_args()
    
    if write_autodance_stubs(args.output, args.map_name):
        print(f"\\nAutodance stubs for {args.map_name} successfully generated.")

if __name__ == "__main__":
    main()
