import re 
import json
from datetime import datetime
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / 'data' / 'database.json'

with open(DATA_PATH, 'r', encoding='utf-8') as file:
    DATA = json.load(file)


def process_data(file_name):
    match = re.match(r'^([a-zA-Z]+)(?:-(\d{6}))?(?:-([a-zA-Z]+))?(?:\s*\((\d+)\))?', file_name)
    print(match)

    if not match:
        return None
    
    idol_key = match.group(1).lower()
    date = match.group(2) or ""
    urgent_flag = match.group(3).lower() if match.group(3) else None
    copies = match.group(4) or 0
    
    # Data convertor 
    date_str = ""
    if date:
        date_obj = datetime.strptime(date, '%y%m%d')
        date_str = date_obj.strftime('%Y-%m-%d')
        if date_str:
            print(date_str)

    if idol_key in DATA['idols']:
        idol_info = DATA['idols'].get(idol_key, {"name_tags": f"#{idol_key}", "group": None})
        group_name = idol_info.get('group')
        group_info = DATA['groups'].get(group_name, {"group_tags": ""} if group_name else {"group_tags": ""})

        header = f"{date} 📸" if date else "📸"
        name_tags = idol_info['name_tags'] if idol_info['name_tags'] else ""
        group_tags = group_info['group_tags'] if group_info['group_tags'] else ""

        # Test after - \n must be at the end of each variable, not at final_text
        final_text = f"{header}\n{name_tags}\n{group_tags}".strip()
    
        return {
            "key": file_name,
            "date": date,
            "urgent": urgent_flag,
            "copies": copies,
            "text": final_text
        }
    
    return None

if __name__ == "__main__":
    result = process_data("karina-261001")
    print(result['text'])
