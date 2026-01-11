import re 
import json
from datetime import datetime

with open('database.json', 'r') as file:
    DATA = json.load(file)


def process_data(file_name):
    match = re.match(r'^([a-zA-Z]+)-(\d{6})(?:-([a-zA-Z]+))?', file_name)
    print(match)

    if not match:
        return None
    
    idol_key = match.group(1).lower()
    date = match.group(2)
    urgent_flag = match.group(3).lower() if match.group(3) else None

    # Data convertor 
    date_obj = datetime.strptime(date, '%y%m%d')
    date_str = date_obj.strftime('%Y-%m-%d')
    print(date_str)

    if idol_key in DATA['idols']:
        idol_info = DATA['idols'].get(idol_key, {"name_tags": f"#{idol_key}", "group": None})
        group_name = idol_info.get('group')
        group_info = DATA['groups'].get(group_name, {"group_tags": ""} if group_name else {"group_tags": ""})

        final_text = f"{date_str} 📸\n{idol_info['name_tags']}\n{group_info['group_tags']}".strip()
    
        return {
            "key": file_name,
            "date": date_str,
            "urgent": urgent_flag,
            "text": final_text
        }
    
    return None

if __name__ == "__main__":
    result = process_data("karina-261001")
    print(result['text'])
