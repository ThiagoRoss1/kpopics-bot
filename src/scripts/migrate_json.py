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
                        INSERT INTO groups (key, group_names, group_tags)
                        VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            group_names = excluded.group_names,
                            group_tags = excluded.group_tags
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
                        INSERT INTO idols (key, idol_names, name_tags, group_id)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            idol_names = excluded.idol_names,
                            name_tags = excluded.name_tags,
                            group_id = excluded.group_id
                    """, (
                        key,
                        json.dumps(info.get('idol_names', []), ensure_ascii=False),
                        info.get('name_tags', f"#{key}"),
                        group_id
                    )
                )
            print(f"Migrated {len(idols)} idol(s).")

    # After seeding, resolve Kpopping identities so any idol with a `kpopping_url` in the seed is
    # ready for the auto-scraper (idempotent — safe to re-run after adding URLs).
    linked = link_kpopping(idols)
    print(f"Linked {linked} idol(s) to Kpopping for auto-scraping.")

    print("Migration complete.")


def link_kpopping(idols):
    # For each seed idol carrying a `kpopping_url`, resolve its Kpopping UUID and store both, so the
    # per-idol poller can find it. Resolution failure is non-fatal (stored without an id, skipped).
    from scrapers.kpopping import resolve_idol_id
    from utils.database_operations import set_idol_kpopping

    linked = 0
    for key, info in idols.items():
        url = (info.get('kpopping_url') or "").strip()
        if not url:
            continue

        kpopping_id = resolve_idol_id(url)
        set_idol_kpopping(key, url, kpopping_id)
        if kpopping_id:
            linked += 1
        else:
            print(f"Warning: could not resolve Kpopping URL for idol '{key}'.")

    return linked


if __name__ == "__main__":
    migrate()
