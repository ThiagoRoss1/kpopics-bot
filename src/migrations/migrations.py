import re
import sqlite3
from pathlib import Path
from contextlib import closing


def apply_migrations(db_file):
    try:
        with closing(sqlite3.connect(db_file)) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_filename TEXT NOT NULL UNIQUE,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

            cursor.execute("SELECT migration_filename FROM schema_migrations")
            applied_migrations = {row[0] for row in cursor.fetchall()}

            migration_dir = Path(__file__).parent
            migration_files = sorted(migration_dir.glob("*.sql"))

            for migration_file in migration_files:
                migration_name = migration_file.name

                if migration_name in applied_migrations:
                    print(f"Filename already applied: {migration_name}")
                    continue

                print(f"Applying migration: {migration_name}")

                with open(migration_file, "r", encoding="utf-8") as file:
                    migration_sql = file.read()
                    # Split UP/DOWN on a line that is exactly the marker, so the string
                    # "-- DOWN" appearing inside a comment doesn't truncate the migration.
                    up_sql = re.split(r'(?m)^-- DOWN\s*$', migration_sql)[0]

                try:
                    conn.executescript(up_sql)

                    cursor.execute("""
                        INSERT INTO schema_migrations (migration_filename)
                        VALUES (?)
                    """, (migration_name,)
                    )
                    conn.commit()
                    print(f"Migration applied successfully: {migration_name}")

                except Exception as e:
                    conn.rollback()
                    print(f"Error applying migration {migration_name}: {e}")
                    break

    except Exception as e:
        print(f"Error connecting to database: {e}")


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    BASE_DIR = Path(__file__).resolve().parent.parent
    load_dotenv(BASE_DIR / ".env")
    sys.path.insert(0, str(BASE_DIR))

    from scripts.init_db import DB_FILE
    apply_migrations(DB_FILE)
