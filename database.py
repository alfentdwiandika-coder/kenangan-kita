import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "storage" / "app.db"

from presets_lib import list_preset_summaries, load_preset

_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _lock:
        conn = get_connection()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    template_id TEXT,
                    video_path TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                );

                CREATE TABLE IF NOT EXISTS templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    duration_per_photo REAL NOT NULL,
                    size TEXT NOT NULL
                );
                """
            )
            conn.execute("DELETE FROM templates")
            for template in list_preset_summaries():
                conn.execute(
                    """
                    INSERT INTO templates (id, name, description, duration_per_photo, size)
                    VALUES (:id, :name, :description, :duration_per_photo, :size)
                    """,
                    template,
                )
            conn.commit()
        finally:
            conn.close()


def list_templates() -> list[dict]:
    return list_preset_summaries()


def get_template(template_id: str) -> dict | None:
    try:
        preset = load_preset(template_id)
    except (OSError, ValueError, FileNotFoundError):
        return None
    return {
        "id": preset["id"],
        "name": preset.get("name", preset["id"]),
        "description": preset.get("description", ""),
        "duration_per_photo": preset["duration_per_photo"],
        "size": preset["size"],
    }


def create_job(job_id: str) -> dict:
    now = utc_now()
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO jobs (id, status, created_at, updated_at)
                VALUES (?, 'photos_uploaded', ?, ?)
                """,
                (job_id, now, now),
            )
            conn.commit()
        finally:
            conn.close()
    return get_job(job_id)


def add_photo(job_id: str, sort_order: int, filename: str, file_path: str) -> None:
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO photos (job_id, sort_order, filename, file_path)
                VALUES (?, ?, ?, ?)
                """,
                (job_id, sort_order, filename, file_path),
            )
            conn.commit()
        finally:
            conn.close()


def get_job(job_id: str) -> dict | None:
    conn = get_connection()
    try:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return None
        photos = conn.execute(
            """
            SELECT id, sort_order, filename, file_path
            FROM photos
            WHERE job_id = ?
            ORDER BY sort_order
            """,
            (job_id,),
        ).fetchall()
        data = dict(job)
        data["photos"] = [dict(photo) for photo in photos]
        return data
    finally:
        conn.close()


def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [job_id]
    with _lock:
        conn = get_connection()
        try:
            conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()
