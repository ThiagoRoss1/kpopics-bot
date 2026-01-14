import sqlite3
import os
import pathlib
from contextlib import closing
from dotenv import load_dotenv

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
    
    with closing(sqlite3.connect(DB_FILE)) as connect:
        with connect:          
            cursor = connect.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_key TEXT NOT NULL,
                    bot_name TEXT NOT NULL,
                    posted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_idol TEXT,
                    UNIQUE(file_key, bot_name)
                )
            """
            )

if __name__ == "__main__":
    init_db()