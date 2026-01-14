import sqlite3
import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / os.getenv("DB_FILE")

DB_FILE = str(DB_PATH)

folder_path = pathlib.Path(DB_FILE).parent

folder_path.mkdir(parents=True, exist_ok=True)

connect = sqlite3.connect(DB_FILE)
cursor = connect.cursor()

history_table = """
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_key TEXT NOT NULL,
        bot_name TEXT NOT NULL,
        posted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_idol TEXT,
        UNIQUE(file_key, bot_name)
    )
"""

cursor.execute(history_table)
connect.commit()
connect.close()