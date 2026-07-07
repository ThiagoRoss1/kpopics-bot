import sys
import json
import sqlite3
import pathlib
from contextlib import closing
from dotenv import load_dotenv

# Load src/.env and add src/ to the path regardless of the working directory,
# so this one-shot migration runs the same way from anywhere.
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
sys.path.insert(0, str(BASE_DIR))

from scripts.init_db import init_db, DB_FILE

DATA_PATH = BASE_DIR / 'data' / 'database.json'

def migrate():
    # Ensure the tables exist first (also creates the pipeline tables, all idempotent).
    init_db()

    with open(DATA_PATH, 'r', encoding='utf-8') as file:
        data = json.load(file)

    groups = data.get('groups', {})
    idols = data.get('idols', {})

    with closing(sqlite3.connect(DB_FILE)) as connect:
        with connect:
            cursor = connect.cursor()

            # Groups first, so idols can link to their group_id.
            for key, info in groups.items():
                cursor.execute(
                    """
                        INSERT OR IGNORE INTO groups (key, group_names, group_tags)
                        VALUES (?, ?, ?)
                    """, (
                        key,
                        json.dumps(info.get('group_names', []), ensure_ascii=False),
                        info.get('group_tags', "")
                    )
                )
            print(f"Migrated {len(groups)} group(s).")

            for key, info in idols.items():
                group_key = info.get('group')
                group_id = None
                if group_key:
                    cursor.execute("SELECT id FROM groups WHERE key = ?", (group_key,))
                    found = cursor.fetchone()
                    group_id = found[0] if found else None
                    if group_id is None:
                        print(f"Warning: idol '{key}' references unknown group '{group_key}'.")

                cursor.execute(
                    """
                        INSERT OR IGNORE INTO idols (key, idol_names, name_tags, group_id)
                        VALUES (?, ?, ?, ?)
                    """, (
                        key,
                        json.dumps(info.get('idol_names', []), ensure_ascii=False),
                        info.get('name_tags', f"#{key}"),
                        group_id
                    )
                )
            print(f"Migrated {len(idols)} idol(s).")

    print("Migration complete.")


if __name__ == "__main__":
    migrate()
