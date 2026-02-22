import json
import sys

def convert_value(val, indent_level):
    indent = "    " * indent_level
    if isinstance(val, dict):
        if "__class" in val:
            class_name = val["__class"]
            out = f"{{\n{indent}    NAME = \"{class_name}\",\n"
            out += f"{indent}    {class_name} = \n"
            out += f"{indent}    {{\n"
            for k, v in val.items():
                if k == "__class": continue
                out += f"{indent}        {k} = {convert_value(v, indent_level + 2)},\n"
            out += f"{indent}    }},\n{indent}}}"
            return out
        else:
            # It's a map/dictionary without __class
            # Translate to array of KEY/VAL pairs
            out = "{\n"
            for k, v in val.items():
                out += f"{indent}    {{\n"
                out += f"{indent}        KEY = \"{k}\",\n"
                out += f"{indent}        VAL = {convert_value(v, indent_level + 2)},\n"
                out += f"{indent}    }},\n"
            out += f"{indent}}}"
            return out
    elif isinstance(val, list):
        out = "{\n"
        for item in val:
            out += f"{indent}    {convert_value(item, indent_level + 1)},\n"
        out += f"{indent}}}"
        return out
    elif isinstance(val, str):
        escaped = val.replace('"', '\\"')
        return f"\"{escaped}\""
    elif isinstance(val, bool):
        return "1" if val else "0"
    elif val is None:
        return "nil"
    elif isinstance(val, float) or isinstance(val, int):
        return str(val)
    else:
        return str(val)

def convert_file(in_path, out_path):
    with open(in_path, 'rb') as f:
        raw = f.read().replace(b'\x00', b'').decode('utf-8')
        try:
            data = json.loads(raw)
        except Exception as e:
            print(f"Error parsing JSON in {in_path}: {e}")
            return
    
    lua_str = "params =\n" + convert_value(data, 0)
    
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(lua_str)
    print(f"Successfully converted {in_path} -> {out_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python json_to_lua.py <input.json> <output.lua>")
    else:
        convert_file(sys.argv[1], sys.argv[2])
