import os
import pathlib
from dotenv import load_dotenv

from migrations.migrations import apply_migrations

load_dotenv()

db_env = os.getenv("DB_FILE")

if not db_env:
    raise RuntimeError("DB_FILE not set.")

if db_env.startswith("/"):
    DB_PATH = pathlib.Path(db_env)

else:
    DB_PATH = pathlib.Path(__file__).resolve().parent.parent / db_env

DB_FILE = str(DB_PATH)

folder_path = pathlib.Path(DB_FILE).parent
folder_path.mkdir(parents=True, exist_ok=True)

def init_db():
    # Schema is owned by the migration runner (src/migrations/*.sql); this just applies
    # any pending migrations. Kept as init_db() so existing callers don't change.
    apply_migrations(DB_FILE)

if __name__ == "__main__":
    init_db()
