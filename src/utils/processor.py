import re 
import json
from datetime import datetime
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / 'data' / 'database.json'

with open(DATA_PATH, 'r', encoding='utf-8') as file:
    DATA = json.load(file)


def process_data(file_name):

    base_name = file_name.rsplit('.', 1)[0] # Removes file extension

    copy_match = re.search(r'\s*\((\d+)\)$', base_name) # Search for copies
    copies = copy_match.group(1) if copy_match else 0

    base_name = re.sub(r'\s*\(\d+\)$', '', base_name)

    date_match = re.search(r'-(\d{6})', base_name) # Search for date
    date = date_match.group(1) if date_match else ""

    base_name = re.sub(r'-\d{6}', '', base_name)

    urgent_match = "urgent" if "urgent" in base_name.lower() else None # Search for urgent tag

    base_name = re.sub(r'urgent', '', base_name, flags=re.IGNORECASE)

    # Search for D1, D2, T1, T2, Q1, Q2 + tags (if on file name)
    combo_match = re.search(r'-(D|T|Q)(\d+)', base_name) 
    combo = combo_match.group(0)[1:].upper() if combo_match else None

    base_name = re.sub(r'-(D|T|Q)(\d+)', '', base_name, flags=re.IGNORECASE).strip()

    raw_keys = re.findall(r'[a-zA-Z]+', base_name)
    idol_keys = [key.lower() for key in raw_keys if key.lower() in DATA['idols']]

    if not idol_keys:
        return None

    # match = re.match(r'^([a-zA-Z]+)(?:-(\d{6}))?(?:-([a-zA-Z]+))?(?:\s*\((\d+)\))?', file_name)
    # print(match)

    # if not match:
    #     return None
    
    # idol_key = match.group(1).lower()
    # date = match.group(2) or ""
    # urgent_flag = match.group(3).lower() if match.group(3) else None
    # copies = match.group(4) or 0
    
    # Data convertor 
    date_str = ""
    if date:
        date_obj = datetime.strptime(date, '%y%m%d')
        date_str = date_obj.strftime('%Y-%m-%d')
        if date_str:
            print(date_str)

    count = len(idol_keys)

    all_idol_names = []
    all_name_tags = []

    all_group_names = []
    all_group_tags = set()
    processed_groups = set()

    for key in idol_keys:
        idol_info = DATA['idols'].get(key, {"name_tags": f"#{key}", "group": None})

        names = idol_info.get('idol_names', [])
        if count == 1:
            all_idol_names.extend(names)
        elif count >= 2:
            if names:
                all_idol_names.append(names[0])
        
        if idol_info:
            all_name_tags.append(idol_info.get('name_tags', f"#{key}"))
            
            group_name = idol_info.get('group')
            if group_name and group_name not in processed_groups:

                group_info = DATA['groups'].get(group_name, {})
                group_names_org = group_info.get('group_names', [])
                group_tags = group_info.get('group_tags', "")

                if group_names_org:
                    all_group_names.append(group_names_org)

                if group_tags:
                    all_group_tags.add(group_tags)

                processed_groups.add(group_name)

    # Header part
    header = f" • ".join(all_idol_names) + (f" 「{date}」 📸" if date else " 📸")

    raw_group_names = [name for names in all_group_names for name in names]
    group_names_post = " • ".join(raw_group_names) + " ✨" if raw_group_names else ""

    name_tags = " ".join(all_name_tags) if all_name_tags else ""
    group_tags = " ".join(all_group_tags) if all_group_tags else ""

    # Test after - \n must be at the end of each variable, not at final_text
    names = f"{header}\n{group_names_post}".strip()
    
    tags = f"{name_tags} {group_tags}".strip()
     
    parts = [names, tags]
    final_text = f"\n\n".join(part for part in parts if part).strip()
    
    return {
        "key": file_name,
        "idols": idol_keys,
        "date": date,
        "urgent": urgent_match,
        "copies": copies,
        "combo": combo,
        "text": final_text
    }  

# if __name__ == "__main__":
#     result = process_data("karina-261001")
#     print(result['text'])
