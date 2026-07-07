import sqlite3
import os
import re
import json
import pathlib
from datetime import datetime
from zoneinfo import ZoneInfo
from contextlib import closing
from dotenv import load_dotenv

load_dotenv()

TIMEZONE_BRT = ZoneInfo("America/Sao_Paulo")

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

def get_idols_with_groups(idol_keys):
    # Returns metadata for the given idol keys (order preserved, unknown keys dropped),
    # so it doubles as idol-key validation. idol_names/group_names are decoded from JSON.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            results = []
            for key in idol_keys:
                cursor.execute(
                    """
                        SELECT i.key, i.idol_names, i.name_tags,
                               g.key, g.group_names, g.group_tags
                        FROM idols i
                        LEFT JOIN groups g ON i.group_id = g.id
                        WHERE i.key = ?
                    """, (key,)
                )

                row = cursor.fetchone()
                if not row:
                    continue

                results.append({
                    "key": row[0],
                    "idol_names": json.loads(row[1]) if row[1] else [],
                    "name_tags": row[2],
                    "group_key": row[3],
                    "group_names": json.loads(row[4]) if row[4] else [],
                    "group_tags": row[5] or ""
                })

            return results

    except Exception as e:
        print(f"Error retrieving idols {idol_keys}: {e}.")
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

# --- Photo pipeline writes (ingestion) ---

def get_idol_ids_by_keys(idol_keys):
    # Resolve idol keys to their row ids (only keys that exist come back).
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            result = {}
            for key in idol_keys:
                cursor.execute("SELECT id FROM idols WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    result[key] = row[0]

            return result

    except Exception as e:
        print(f"Error resolving idol ids {idol_keys}: {e}.")
        return {}

def insert_photo(source, source_url=None, date=None, urgent=None, copies=0, combo=None, album_id=None):
    # Insert as 'uploading' first (before the R2 upload) so a crash mid-upload leaves a
    # traceable row to clean up rather than an orphaned bucket object with no record.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                cursor.execute(
                    """
                        INSERT INTO photos
                            (source, source_url, status, date, urgent, copies, combo, album_id)
                        VALUES (?, ?, 'uploading', ?, ?, ?, ?, ?)
                    """, (source, source_url, date, urgent, copies, combo, album_id)
                )

                return cursor.lastrowid

    except Exception as e:
        print(f"Error inserting photo: {e}.")
        return None

def set_photo_ready(photo_id, r2_key):
    # Called after a successful upload: record the key and move the row into the pipeline.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                cursor.execute(
                    """
                        UPDATE photos
                        SET r2_key = ?, bucket_stage = 'analysis', status = 'pending'
                        WHERE id = ?
                    """, (r2_key, photo_id)
                )

                return True

    except Exception as e:
        print(f"Error marking photo {photo_id} ready: {e}.")
        return False

def link_photo_idols(photo_id, idol_ids, confidence=1.0):
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                for idol_id in idol_ids:
                    cursor.execute(
                        """
                            INSERT OR IGNORE INTO photo_idols (photo_id, idol_id, confidence)
                            VALUES (?, ?, ?)
                        """, (photo_id, idol_id, confidence)
                    )

                return True

    except Exception as e:
        print(f"Error linking idols to photo {photo_id}: {e}.")
        return False

def delete_photo(photo_id):
    # Cleanup path for a failed ingest (removes the row + any idol links).
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                cursor.execute("DELETE FROM photo_idols WHERE photo_id = ?", (photo_id,))
                cursor.execute("DELETE FROM photos WHERE id = ?", (photo_id,))

                return True

    except Exception as e:
        print(f"Error deleting photo {photo_id}: {e}.")
        return False

def get_idol_keys_by_names(names):
    # Text-match names from source metadata (e.g. a Kpopping profile-link name) against each
    # idol's registered idol_names (multi-language), case-insensitive. Returns the resolved keys
    # (order preserved, unknown names dropped), so it doubles as idol validation for scraping.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute("SELECT key, idol_names FROM idols")

            lookup = {}
            for key, names_json in cursor.fetchall():
                for name in (json.loads(names_json) if names_json else []):
                    lookup[name.lower()] = key

            resolved = []
            for name in names:
                key = lookup.get(name.strip().lower())
                if key and key not in resolved:
                    resolved.append(key)

            return resolved

    except Exception as e:
        print(f"Error resolving idol names {names}: {e}.")
        return []

def photo_exists_by_source_url(source_url):
    # Dedup check for ingestion: has this exact source image already been ingested?
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute("SELECT 1 FROM photos WHERE source_url = ? LIMIT 1", (source_url,))
            return cursor.fetchone() is not None

    except Exception as e:
        print(f"Error checking source_url {source_url}: {e}.")
        return False

# --- Photo pipeline reads (posting) ---

def _build_photo_text(idol_keys, date):
    # Reuses processor.build_tweet_text with DB-sourced idol metadata. Imported lazily because
    # processor imports this module at load time, so a top-level import would be circular.
    from utils.processor import build_tweet_text

    idols_data = get_idols_with_groups(idol_keys)
    return build_tweet_text(idols_data, date)

def get_approved_photos():
    # The bot's approved queue: every photo in the 'approved' bucket stage, shaped exactly like
    # process_data's output (key/idols/date/urgent/copies/combo/text) so _get_image consumes it
    # unchanged — `key` is now the r2_key (the object actually downloaded/logged), the metadata
    # coming from the DB instead of the file name. Also carries the pipeline fields.
    # priority sort needs (ai_score, reviewed_at) and album_id (the source grouping key).
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute(
                """
                    SELECT id, r2_key, date, urgent, copies, combo,
                           album_id, ai_score, reviewed_at
                    FROM photos
                    WHERE bucket_stage = 'approved'
                """
            )
            rows = cursor.fetchall()

            photos = []
            for row in rows:
                (photo_id, r2_key, date, urgent, copies,
                 combo, album_id, ai_score, reviewed_at) = row

                cursor.execute(
                    """
                        SELECT i.key
                        FROM photo_idols pi
                        JOIN idols i ON pi.idol_id = i.id
                        WHERE pi.photo_id = ?
                        ORDER BY i.id
                    """, (photo_id,)
                )
                idol_keys = [r[0] for r in cursor.fetchall()]

                photos.append({
                    "id": photo_id,
                    "key": r2_key,
                    "idols": idol_keys,
                    "date": date or "",
                    "urgent": urgent if urgent else None,
                    "copies": copies or 0,
                    "combo": combo,
                    "album_id": album_id,
                    "ai_score": ai_score,
                    "reviewed_at": reviewed_at,
                    "text": _build_photo_text(idol_keys, date or "")
                })

            return photos

    except Exception as e:
        print(f"Error retrieving approved photos: {e}.")
        return []

# --- Approval pipeline (webapp) ---

def get_pending_photos():
    # The approval queue: photos awaiting review (status='pending', still in the analysis stage),
    # newest first, each with its resolved idol keys and the fields the webapp shows.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute(
                """
                    SELECT id, source, source_url, date, ai_score, album_id, created_at,
                           urgent, combo, copies
                    FROM photos
                    WHERE status = 'pending'
                    ORDER BY created_at DESC, id DESC
                """
            )
            rows = cursor.fetchall()

            photos = []
            for row in rows:
                (photo_id, source, source_url, date, ai_score, album_id, created_at,
                 urgent, combo, copies) = row

                cursor.execute(
                    """
                        SELECT i.key
                        FROM photo_idols pi
                        JOIN idols i ON pi.idol_id = i.id
                        WHERE pi.photo_id = ?
                        ORDER BY i.id
                    """, (photo_id,)
                )
                idol_keys = [r[0] for r in cursor.fetchall()]

                photos.append({
                    "id": photo_id,
                    "idols": idol_keys,
                    "source": source,
                    "source_url": source_url,
                    "date": date,
                    "ai_score": ai_score,
                    "album_id": album_id,
                    "created_at": created_at,
                    "urgent": urgent if urgent else None,
                    "combo": combo,
                    "copies": copies or 0
                })

            return photos

    except Exception as e:
        print(f"Error retrieving pending photos: {e}.")
        return []

def get_photo(photo_id):
    # Minimal lookup for the approve/reject/stream endpoints: current R2 key + pipeline state.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute(
                "SELECT id, r2_key, bucket_stage, status FROM photos WHERE id = ?", (photo_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            return {"id": row[0], "r2_key": row[1], "bucket_stage": row[2], "status": row[3]}

    except Exception as e:
        print(f"Error retrieving photo {photo_id}: {e}.")
        return None

def set_photo_approved(photo_id, r2_key, reviewed_by="webapp"):
    # Finalize an approval: point the row at the promoted 'approved/...' key and stamp review data.
    # reviewed_at is BRT ISO so the sorter's _days_waiting parses it consistently with the app tz.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                cursor.execute(
                    """
                        UPDATE photos
                        SET r2_key = ?, bucket_stage = 'approved', status = 'approved',
                            reviewed_by = ?, reviewed_at = ?
                        WHERE id = ?
                    """, (r2_key, reviewed_by, datetime.now(TIMEZONE_BRT).isoformat(), photo_id)
                )

                return True

    except Exception as e:
        print(f"Error approving photo {photo_id}: {e}.")
        return False

def set_photo_posted(photo_id):
    # Called after the bot posts a photo and deletes its bytes: take it out of the approved queue
    # so get_approved_photos never returns a row whose R2 object is already gone.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                cursor.execute(
                    "UPDATE photos SET status = 'posted', bucket_stage = 'posted' WHERE id = ?",
                    (photo_id,)
                )

                return True

    except Exception as e:
        print(f"Error marking photo {photo_id} posted: {e}.")
        return False

def set_photo_rejected(photo_id, reviewed_by="webapp"):
    # Reject: the bytes are deleted by the caller; the row is kept (r2_key cleared) so the same
    # source image is not re-ingested later (dedup via source_url). Both status and bucket_stage
    # read 'rejected' so the state is visible in either column.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                cursor.execute(
                    """
                        UPDATE photos
                        SET status = 'rejected', bucket_stage = 'rejected', r2_key = NULL,
                            reviewed_by = ?, reviewed_at = ?
                        WHERE id = ?
                    """, (reviewed_by, datetime.now(TIMEZONE_BRT).isoformat(), photo_id)
                )

                return True

    except Exception as e:
        print(f"Error rejecting photo {photo_id}: {e}.")
        return False

# --- Approval metadata: urgent + auto-combo (webapp) ---

def set_photo_urgent(photo_id, urgent):
    # Toggle a pending photo's urgent flag (stored 1 / NULL to match the sorter's `is not None`).
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                cursor.execute(
                    "UPDATE photos SET urgent = ? WHERE id = ? AND status = 'pending'",
                    (1 if urgent else None, photo_id)
                )

                return cursor.rowcount > 0

    except Exception as e:
        print(f"Error setting urgent on photo {photo_id}: {e}.")
        return False

def _idol_set(cursor, photo_id):
    # The photo's idol keys as an ordered tuple (the grouping identity for a combo).
    cursor.execute(
        """
            SELECT i.key FROM photo_idols pi
            JOIN idols i ON pi.idol_id = i.id
            WHERE pi.photo_id = ? ORDER BY i.id
        """, (photo_id,)
    )
    return tuple(row[0] for row in cursor.fetchall())

def _combos_for_idol_set(cursor, idol_set):
    # Every distinct combo label already used by photos of exactly this idol-set (any status), so a
    # new combo number never collides with an existing one for the same idol(s).
    rows = cursor.execute("SELECT id, combo FROM photos WHERE combo IS NOT NULL").fetchall()
    return {combo for pid, combo in rows if _idol_set(cursor, pid) == idol_set}

def create_combo(photo_ids):
    # Group 2-4 pending photos of the same idol(s) into one multi-image tweet. Assigns a combo label
    # (D/T/Q by size + the next per-idol-set number) and `copies` = list order. Returns
    # {combo, label} or None on any validation failure (caller -> 400).
    if not (2 <= len(photo_ids) <= 4):
        return None

    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                idol_sets = []
                for photo_id in photo_ids:
                    row = cursor.execute("SELECT status FROM photos WHERE id = ?", (photo_id,)).fetchone()
                    if not row or row[0] != "pending":
                        return None
                    idol_sets.append(_idol_set(cursor, photo_id))

                idol_set = idol_sets[0]
                if not idol_set or any(s != idol_set for s in idol_sets):
                    return None

                type_letter = {2: "D", 3: "T", 4: "Q"}[len(photo_ids)]
                used = _combos_for_idol_set(cursor, idol_set)
                numbers = [int(re.search(r"\d+", c).group()) for c in used if re.search(r"\d+", c)]
                number = (max(numbers) + 1) if numbers else 1
                combo = f"{type_letter}{number}"

                for order, photo_id in enumerate(photo_ids, start=1):
                    cursor.execute("UPDATE photos SET combo = ?, copies = ? WHERE id = ?",
                                   (combo, order, photo_id))

                label = f"{ {'D': 'Duo', 'T': 'Trio', 'Q': 'Quad'}[type_letter] } #{number}"
                return {"combo": combo, "label": label}

    except Exception as e:
        print(f"Error creating combo for {photo_ids}: {e}.")
        return None

def clear_combo(combo):
    # Ungroup: drop the combo label + copies from every photo carrying it.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                cursor.execute("UPDATE photos SET combo = NULL, copies = 0 WHERE combo = ?", (combo,))
                return True

    except Exception as e:
        print(f"Error clearing combo {combo}: {e}.")
        return False

# --- Idol registration (webapp) ---

def get_all_idols():
    # Every registered idol with its group — for the webapp's idol picker and the idol list.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute(
                """
                    SELECT i.key, i.idol_names, i.name_tags,
                           g.key, g.group_names, g.group_tags
                    FROM idols i
                    LEFT JOIN groups g ON i.group_id = g.id
                    ORDER BY g.key, i.key
                """
            )

            return [{
                "key": row[0],
                "idol_names": json.loads(row[1]) if row[1] else [],
                "name_tags": row[2],
                "group_key": row[3],
                "group_names": json.loads(row[4]) if row[4] else [],
                "group_tags": row[5] or ""
            } for row in cursor.fetchall()]

    except Exception as e:
        print(f"Error retrieving idols: {e}.")
        return []

def get_all_groups():
    # Every registered group — for the register-idol form's group dropdown.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute("SELECT key, group_names, group_tags FROM groups ORDER BY key")

            return [{
                "key": row[0],
                "group_names": json.loads(row[1]) if row[1] else [],
                "group_tags": row[2] or ""
            } for row in cursor.fetchall()]

    except Exception as e:
        print(f"Error retrieving groups: {e}.")
        return []

def idol_exists(key):
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute("SELECT 1 FROM idols WHERE key = ? LIMIT 1", (key,))
            return cursor.fetchone() is not None

    except Exception as e:
        print(f"Error checking idol {key}: {e}.")
        return False

def create_idol(key, idol_names, name_tags, group_key, group_names=None, group_tags=None):
    # Register a new idol, creating its group on the fly if that group key doesn't exist yet
    # (group_names defaults to the group key). Returns the new idol id, or None on failure.
    # Assumes the idol key is free — callers check idol_exists first for a clean 409.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                group_id = None
                if group_key:
                    row = cursor.execute("SELECT id FROM groups WHERE key = ?", (group_key,)).fetchone()
                    if row:
                        group_id = row[0]
                    else:
                        cursor.execute(
                            "INSERT INTO groups (key, group_names, group_tags) VALUES (?, ?, ?)",
                            (group_key, json.dumps(group_names or [group_key], ensure_ascii=False),
                             group_tags or "")
                        )
                        group_id = cursor.lastrowid

                cursor.execute(
                    "INSERT INTO idols (key, idol_names, name_tags, group_id) VALUES (?, ?, ?, ?)",
                    (key, json.dumps(idol_names, ensure_ascii=False), name_tags, group_id)
                )

                return cursor.lastrowid

    except Exception as e:
        print(f"Error creating idol {key}: {e}.")
        return None

def set_idol_kpopping(idol_key, kpopping_url, kpopping_id):
    # Store an idol's Kpopping identity (profile URL + resolved UUID) so the poller can find them.
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            with connect:
                cursor = connect.cursor()

                cursor.execute(
                    "UPDATE idols SET kpopping_url = ?, kpopping_id = ? WHERE key = ?",
                    (kpopping_url, kpopping_id, idol_key)
                )

                return True

    except Exception as e:
        print(f"Error setting Kpopping id for idol {idol_key}: {e}.")
        return False

def get_idols_for_discovery():
    # Idols the auto-scraper can poll: those with a resolved Kpopping UUID. Returns [(key, id), ...].
    try:
        with closing(sqlite3.connect(DB_FILE)) as connect:
            cursor = connect.cursor()

            cursor.execute(
                """
                    SELECT key, kpopping_id FROM idols
                    WHERE kpopping_id IS NOT NULL AND kpopping_id != ''
                    ORDER BY key
                """
            )

            return [{"key": row[0], "kpopping_id": row[1]} for row in cursor.fetchall()]

    except Exception as e:
        print(f"Error retrieving idols for discovery: {e}.")
        return []
