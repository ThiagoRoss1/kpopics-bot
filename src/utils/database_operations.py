import sqlite3
import os
import pathlib
from contextlib import closing
from dotenv import load_dotenv

load_dotenv()
DB_PATH = pathlib.Path(__file__).resolve().parent.parent / os.getenv("DB_FILE")

DB_FILE = str(DB_PATH)

def log_posted_image(file_key, bot_name, last_idol):
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                cursor.execute(
                    """
                        INSERT OR IGNORE INTO history (file_key, bot_name, last_idol)
                        VALUES (?, ?, ?)
                    """, (file_key, bot_name, last_idol)
                )
                
    except Exception as e:
        print(f"Error logging posted image {file_key} for bot {bot_name}: {e}.")
        
def get_log_history(file_key):
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute(
                """
                    SELECT bot_name FROM history
                    WHERE file_key = ?
                """, (file_key,)
            )

            results = cursor.fetchall()
            return [row[0] for row in results]
    
    except Exception as e:
        print(f"Error retrieving log history for {file_key}: {e}.")
        return []

def get_last_posted_image(bot_name):
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute(
                """
                    SELECT file_key, last_idol FROM history
                    WHERE bot_name = ?
                    ORDER BY posted_at DESC
                    LIMIT 1
                """, (bot_name,)
                )
            
            result = cursor.fetchone()
            if result:
                return {"file_key": result[0], "last_idol": result[1]}
            
            return None
    
    except Exception as e:
        print(f"Error retrieving last posted image for bot {bot_name}: {e}.")
        return None
