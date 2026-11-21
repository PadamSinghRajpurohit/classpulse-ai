"""Local, privacy-conscious SQLite storage for ClassPulse.

Raw camera and microphone media should be processed in memory and never passed
to this module. Only session-level summaries and pseudonymous rollups belong in
the database.
"""

from __future__ import annotations

import json
import importlib.util
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def database_path() -> Path:
    """Return the configured database location (defaults to ``data/classpulse.db``)."""
    configured = os.getenv("DATABASE_PATH", "data/classpulse.db").strip()
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


@contextmanager
def _connect():
    """Open a SQLite connection and always close it after the transaction."""
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Create local schema if needed. No users or demo credentials are seeded."""
    with _connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                class_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                enrollment_count INTEGER NOT NULL DEFAULT 0,
                attendance_count INTEGER NOT NULL DEFAULT 0,
                engagement_score REAL,
                participation_count INTEGER NOT NULL DEFAULT 0,
                summary_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_owner_started
                ON sessions(owner_id, started_at DESC);
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                student_code TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(owner_id, student_code)
            );
            CREATE INDEX IF NOT EXISTS idx_students_owner_name
                ON students(owner_id, name COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(owner_id, name)
            );
            CREATE INDEX IF NOT EXISTS idx_classes_owner_name
                ON classes(owner_id, name COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS class_students (
                owner_id TEXT NOT NULL,
                class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                PRIMARY KEY(class_id, student_id)
            );
            CREATE INDEX IF NOT EXISTS idx_class_students_owner_class
                ON class_students(owner_id, class_id);
            CREATE TABLE IF NOT EXISTS app_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                student_pk INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                session_date TEXT NOT NULL,
                class_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('present', 'absent', 'late', 'excused')),
                marked_at TEXT NOT NULL,
                UNIQUE(owner_id, student_pk, session_date, class_name)
            );
            CREATE INDEX IF NOT EXISTS idx_attendance_owner_date
                ON attendance_records(owner_id, session_date DESC);
            """
        )
        attendance_columns = {row["name"] for row in db.execute("PRAGMA table_info(attendance_records)")}
        if "class_name" not in attendance_columns:
            # Rebuild the early local schema so attendance can be tracked by
            # class as well as date. Existing records migrate as an empty class.
            db.execute("DROP INDEX IF EXISTS idx_attendance_owner_date")
            db.execute("ALTER TABLE attendance_records RENAME TO attendance_records_legacy")
            db.execute(
                """CREATE TABLE attendance_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL,
                    student_pk INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    session_date TEXT NOT NULL,
                    class_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN ('present', 'absent', 'late', 'excused')),
                    marked_at TEXT NOT NULL,
                    UNIQUE(owner_id, student_pk, session_date, class_name)
                )"""
            )
            db.execute(
                """INSERT INTO attendance_records(id, owner_id, student_pk, session_date, class_name, status, marked_at)
                   SELECT id, owner_id, student_pk, session_date, '', status, marked_at
                   FROM attendance_records_legacy"""
            )
            db.execute("DROP TABLE attendance_records_legacy")
            db.execute("CREATE INDEX idx_attendance_owner_date ON attendance_records(owner_id, session_date DESC)")

        # One-time migration from the old account-wide roster. Previous app
        # versions did not track class membership, so attach those existing
        # students to every previously used class label. New memberships stay
        # explicit after this migration has been recorded.
        migration = "class_scoped_rosters_v1"
        applied = db.execute("SELECT 1 FROM app_migrations WHERE name = ?", (migration,)).fetchone()
        if not applied:
            owners = db.execute("SELECT DISTINCT owner_id FROM students").fetchall()
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for owner in owners:
                owner_id = str(owner["owner_id"])
                class_rows = db.execute(
                    "SELECT id FROM classes WHERE owner_id = ? ORDER BY id", (owner_id,)
                ).fetchall()
                if not class_rows:
                    old_labels = db.execute(
                        "SELECT DISTINCT class_name FROM attendance_records "
                        "WHERE owner_id = ? AND TRIM(class_name) <> '' ORDER BY class_name COLLATE NOCASE",
                        (owner_id,),
                    ).fetchall()
                    labels = [str(row["class_name"]).strip() for row in old_labels] or ["Class 1"]
                    for label in labels:
                        db.execute(
                            "INSERT OR IGNORE INTO classes(owner_id, name, created_at) VALUES (?, ?, ?)",
                            (owner_id, label[:100], timestamp),
                        )
                    class_rows = db.execute(
                        "SELECT id FROM classes WHERE owner_id = ? ORDER BY id", (owner_id,)
                    ).fetchall()
                student_rows = db.execute("SELECT id FROM students WHERE owner_id = ?", (owner_id,)).fetchall()
                for class_row in class_rows:
                    for student in student_rows:
                        db.execute(
                            "INSERT OR IGNORE INTO class_students(owner_id, class_id, student_id, created_at) "
                            "VALUES (?, ?, ?, ?)",
                            (owner_id, int(class_row["id"]), int(student["id"]), timestamp),
                        )
            db.execute(
                "INSERT INTO app_migrations(name, applied_at) VALUES (?, ?)", (migration, timestamp)
            )


def list_classes(owner_id: int | str, access_token: str | None = None) -> list[dict[str, Any]]:
    """List this owner's local classes for attendance and session selection."""
    if _remote_roster_enabled(owner_id, access_token):
        _sync_legacy_local_roster(owner_id, access_token)
        table = _remote_table(access_token, "classpulse_classes")
        rows = table.select(
            "id,name,created_at"
        ).eq("owner_id", str(owner_id)).order("name").execute().data or []
        return [dict(row) for row in rows]
    with _connect() as db:
        rows = db.execute(
            "SELECT id, name, created_at FROM classes WHERE owner_id = ? ORDER BY name COLLATE NOCASE",
            (str(owner_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def create_class(owner_id: int | str, name: str, access_token: str | None = None) -> int:
    """Create an owner-scoped local class and return its ID."""
    normalized = (name or "").strip()
    if not normalized or len(normalized) > 100:
        raise ValueError("Class name is required and must be 100 characters or fewer")
    if _remote_roster_enabled(owner_id, access_token):
        try:
            result = _remote_table(access_token, "classpulse_classes").insert(
                {"owner_id": str(owner_id), "name": normalized}
            ).execute().data or []
        except Exception as exc:
            raise RuntimeError("Class storage is unavailable. Confirm the ClassPulse Supabase migration has been applied.") from exc
        if not result:
            raise RuntimeError("Class storage returned no saved class.")
        return int(result[0]["id"])
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as db:
        try:
            cursor = db.execute(
                "INSERT INTO classes(owner_id, name, created_at) VALUES (?, ?, ?)",
                (str(owner_id), normalized, timestamp),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("A class with that name already exists") from exc
        return int(cursor.lastrowid)


def list_students(owner_id: int | str, class_id: int | None = None, access_token: str | None = None) -> list[dict[str, Any]]:
    """List an owner's roster, optionally limited to one class membership."""
    if _remote_roster_enabled(owner_id, access_token):
        table = _remote_table(access_token, "classpulse_students")
        if class_id is None:
            rows = table.select("id,student_code,name,created_at").eq("owner_id", str(owner_id)).order("name").execute().data or []
        else:
            memberships = _remote_table(access_token, "classpulse_class_students").select(
                "student_id"
            ).eq("owner_id", str(owner_id)).eq("class_id", int(class_id)).execute().data or []
            ids = [int(row["student_id"]) for row in memberships]
            rows = table.select("id,student_code,name,created_at").eq("owner_id", str(owner_id)).in_("id", ids).order("name").execute().data if ids else []
        return [dict(row) for row in (rows or [])]
    with _connect() as db:
        if class_id is None:
            rows = db.execute(
                "SELECT id, student_code, name, created_at FROM students WHERE owner_id = ? ORDER BY name COLLATE NOCASE",
                (str(owner_id),),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT s.id, s.student_code, s.name, s.created_at FROM students AS s "
                "JOIN class_students AS cs ON cs.student_id = s.id "
                "JOIN classes AS c ON c.id = cs.class_id "
                "WHERE s.owner_id = ? AND cs.owner_id = ? AND c.owner_id = ? AND c.id = ? "
                "ORDER BY s.name COLLATE NOCASE",
                (str(owner_id), str(owner_id), str(owner_id), int(class_id)),
            ).fetchall()
    return [dict(row) for row in rows]


def list_unenrolled_students(owner_id: int | str, class_id: int, access_token: str | None = None) -> list[dict[str, Any]]:
    """List existing local students who are not yet members of this class."""
    if _remote_roster_enabled(owner_id, access_token):
        students = list_students(owner_id, access_token=access_token)
        members = list_students(owner_id, class_id, access_token=access_token)
        member_ids = {int(row["id"]) for row in members}
        return [row for row in students if int(row["id"]) not in member_ids]
    with _connect() as db:
        rows = db.execute(
            "SELECT s.id, s.student_code, s.name FROM students AS s "
            "JOIN classes AS c ON c.owner_id = s.owner_id "
            "WHERE s.owner_id = ? AND c.id = ? AND NOT EXISTS ("
            "SELECT 1 FROM class_students AS cs WHERE cs.owner_id = s.owner_id "
            "AND cs.class_id = c.id AND cs.student_id = s.id) "
            "ORDER BY s.name COLLATE NOCASE",
            (str(owner_id), int(class_id)),
        ).fetchall()
    return [dict(row) for row in rows]


def enroll_student(owner_id: int | str, class_id: int, student_id: int, access_token: str | None = None) -> bool:
    """Enroll an existing local student in another local class."""
    if _remote_roster_enabled(owner_id, access_token):
        try:
            result = _remote_table(access_token, "classpulse_class_students").upsert({
                "owner_id": str(owner_id), "class_id": int(class_id), "student_id": int(student_id),
            }, on_conflict="class_id,student_id").execute()
            return bool(getattr(result, "data", None))
        except Exception as exc:
            raise RuntimeError("Student could not be enrolled in the remote class roster.") from exc
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as db:
        class_exists = db.execute(
            "SELECT 1 FROM classes WHERE owner_id = ? AND id = ?", (str(owner_id), int(class_id))
        ).fetchone()
        student_exists = db.execute(
            "SELECT 1 FROM students WHERE owner_id = ? AND id = ?", (str(owner_id), int(student_id))
        ).fetchone()
        if not class_exists or not student_exists:
            raise ValueError("Choose a class and student from this local account")
        cursor = db.execute(
            "INSERT OR IGNORE INTO class_students(owner_id, class_id, student_id, created_at) VALUES (?, ?, ?, ?)",
            (str(owner_id), int(class_id), int(student_id), timestamp),
        )
        return cursor.rowcount > 0


def remove_student_from_class(owner_id: int | str, class_id: int, student_id: int, access_token: str | None = None) -> bool:
    """Remove a student from one class while keeping their other class data."""
    if _remote_roster_enabled(owner_id, access_token):
        result = _remote_table(access_token, "classpulse_class_students").delete().eq(
            "owner_id", str(owner_id)
        ).eq("class_id", int(class_id)).eq("student_id", int(student_id)).execute()
        return bool(getattr(result, "data", None))
    with _connect() as db:
        cursor = db.execute(
            "DELETE FROM class_students WHERE owner_id = ? AND class_id = ? AND student_id = ?",
            (str(owner_id), int(class_id), int(student_id)),
        )
        return cursor.rowcount > 0


def add_student(
    owner_id: int | str,
    name: str,
    student_code: str = "",
    *,
    student_id: str | None = None,
    class_id: int | None = None,
    access_token: str | None = None,
) -> int:
    """Add a local roster entry and return its local integer ID.

    The code is instructor-assigned, not a government or school-wide identifier.
    Student data is deliberately never synced to Supabase.
    """
    normalized_name = (name or "").strip()
    code = (student_id if student_id is not None else student_code or "").strip()
    if not code:
        code = "STU-" + secrets.token_hex(3).upper()
    if not normalized_name or len(normalized_name) > 100:
        raise ValueError("Student name is required and must be 100 characters or fewer")
    if not code or len(code) > 64:
        raise ValueError("Student code is required and must be 64 characters or fewer")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if _remote_roster_enabled(owner_id, access_token):
        try:
            result = _remote_table(access_token, "classpulse_students").insert({
                "owner_id": str(owner_id), "student_code": code,
                "name": normalized_name, "created_at": timestamp,
            }).execute().data or []
            if not result:
                raise RuntimeError("Student storage returned no saved roster row.")
            new_student_id = int(result[0]["id"])
            if class_id is not None:
                _remote_table(access_token, "classpulse_class_students").insert({
                    "owner_id": str(owner_id), "class_id": int(class_id),
                    "student_id": new_student_id,
                }).execute()
            return new_student_id
        except Exception as exc:
            raise ValueError("Student could not be saved. Check for a duplicate roster code and verify the Supabase migration.") from exc
    with _connect() as db:
        try:
            cursor = db.execute(
                "INSERT INTO students(owner_id, student_code, name, created_at) VALUES (?, ?, ?, ?)",
                (str(owner_id), code, normalized_name, timestamp),
            )
            new_student_id = int(cursor.lastrowid)
            if class_id is not None:
                class_exists = db.execute(
                    "SELECT 1 FROM classes WHERE owner_id = ? AND id = ?",
                    (str(owner_id), int(class_id)),
                ).fetchone()
                if not class_exists:
                    raise ValueError("Choose a class from this local account")
                db.execute(
                    "INSERT INTO class_students(owner_id, class_id, student_id, created_at) VALUES (?, ?, ?, ?)",
                    (str(owner_id), int(class_id), new_student_id, timestamp),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("That student code is already in this roster") from exc
        return new_student_id


def save_attendance(
    owner_id: int | str,
    session_date: str,
    class_name: str,
    rows: list[dict[str, Any]],
    access_token: str | None = None,
) -> int:
    """Upsert manual statuses for one local roster, class, and ISO date.

    Entries accept a local integer ``student_id`` or ``student_code`` and either
    a boolean ``present`` or status ``present``, ``absent``, ``late``, ``excused``.
    """
    try:
        normalized_date = datetime.strptime(session_date, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("session_date must use YYYY-MM-DD format") from exc
    class_name = (class_name or "").strip()
    if not class_name or len(class_name) > 120:
        raise ValueError("class_name is required and must be 120 characters or fewer")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("rows must be a list with at most 1000 attendance entries")
    valid_statuses = {"present", "absent", "late", "excused"}
    normalized_rows: list[tuple[str, str]] = []
    seen_codes: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("each attendance entry must be an object")
        student_ref = item.get("student_id")
        code = str(item.get("student_code") or (student_ref if isinstance(student_ref, str) else "")).strip()
        status_value = item.get("status")
        if isinstance(item.get("present"), bool):
            status_value = "present" if item["present"] else "absent"
        status = str(status_value or "").strip().casefold()
        if not code and student_ref is None:
            raise ValueError("each entry requires a valid student_id or student_code")
        if len(code) > 64:
            raise ValueError("student_code must be 64 characters or fewer")
        if status not in valid_statuses:
            raise ValueError("status must be present, absent, late, or excused")
        duplicate_key = code or f"id:{student_ref}"
        if duplicate_key in seen_codes:
            raise ValueError("a student can appear only once in one attendance save")
        seen_codes.add(duplicate_key)
        normalized_rows.append((code or f"#id:{student_ref}", status))

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if _remote_roster_enabled(owner_id, access_token):
        student_rows = _remote_table(access_token, "classpulse_students").select(
            "id,student_code"
        ).eq("owner_id", str(owner_id)).execute().data or []
        by_id = {int(row["id"]): row for row in student_rows}
        by_code = {str(row["student_code"]): row for row in student_rows}
        payload = []
        for item, (code, status) in zip(rows, normalized_rows):
            student_ref = item.get("student_id")
            match = by_id.get(int(student_ref)) if isinstance(student_ref, int) else by_code.get(code)
            if not match:
                raise ValueError("attendance contains a student outside this owner's remote roster")
            payload.append({
                "owner_id": str(owner_id), "student_pk": int(match["id"]),
                "session_date": normalized_date, "class_name": class_name,
                "status": status, "marked_at": now,
            })
        try:
            if payload:
                _remote_table(access_token, "classpulse_attendance_records").upsert(
                    payload, on_conflict="owner_id,student_pk,session_date,class_name"
                ).execute()
        except Exception as exc:
            raise RuntimeError("Attendance could not be saved to the Supabase database.") from exc
        return len(payload)
    with _connect() as db:
        for code, status in normalized_rows:
            if code.startswith("#id:"):
                try:
                    ref_id = int(code[4:])
                except ValueError as exc:
                    raise ValueError("student_id must be a local integer roster ID") from exc
                student = db.execute(
                    "SELECT id FROM students WHERE owner_id = ? AND id = ?",
                    (str(owner_id), ref_id),
                ).fetchone()
            else:
                student = db.execute(
                    "SELECT id FROM students WHERE owner_id = ? AND student_code = ?",
                    (str(owner_id), code),
                ).fetchone()
            if student is None:
                raise ValueError("attendance contains a student code outside this owner's roster")
            db.execute(
                """INSERT INTO attendance_records(owner_id, student_pk, session_date, class_name, status, marked_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(owner_id, student_pk, session_date, class_name)
                   DO UPDATE SET class_name = excluded.class_name, status = excluded.status, marked_at = excluded.marked_at""",
                (str(owner_id), int(student["id"]), normalized_date, class_name, status, now),
            )
    return len(normalized_rows)


def list_attendance(
    owner_id: int | str,
    session_date: str | None = None,
    class_name: str | None = None,
    access_token: str | None = None,
) -> list[dict[str, Any]]:
    """List this owner's local manual records, optionally filtered by date/class."""
    if session_date is not None:
        try:
            session_date = datetime.strptime(session_date, "%Y-%m-%d").date().isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError("session_date must use YYYY-MM-DD format") from exc
    if _remote_roster_enabled(owner_id, access_token):
        query = _remote_table(access_token, "classpulse_attendance_records").select(
            "id,student_pk,session_date,class_name,status,marked_at"
        ).eq("owner_id", str(owner_id))
        if session_date is not None:
            query = query.eq("session_date", session_date)
        if class_name is not None:
            query = query.eq("class_name", class_name.strip())
        rows = query.order("session_date", desc=True).execute().data or []
        ids = list({int(row["student_pk"]) for row in rows})
        students = _remote_table(access_token, "classpulse_students").select(
            "id,student_code,name"
        ).eq("owner_id", str(owner_id)).in_("id", ids).execute().data if ids else []
        by_id = {int(row["id"]): row for row in (students or [])}
        return [{
            **row,
            "student_id": int(row["student_pk"]),
            "student_code": by_id.get(int(row["student_pk"]), {}).get("student_code", ""),
            "student_name": by_id.get(int(row["student_pk"]), {}).get("name", "Student"),
            "present": row["status"] in {"present", "late"},
        } for row in rows]
    query = """SELECT a.session_date, a.class_name, a.student_pk AS student_id,
                      s.student_code, s.name AS student_name, a.status,
                      (a.status IN ('present', 'late')) AS present, a.marked_at
               FROM attendance_records AS a
               JOIN students AS s ON s.id = a.student_pk
               WHERE a.owner_id = ?"""
    parameters: list[Any] = [str(owner_id)]
    if session_date is not None:
        query += " AND a.session_date = ?"
        parameters.append(session_date)
    if class_name is not None:
        query += " AND a.class_name = ?"
        parameters.append(class_name.strip())
    query += " ORDER BY a.session_date DESC, s.name COLLATE NOCASE"
    with _connect() as db:
        rows = db.execute(query, parameters).fetchall()
    records = [dict(row) for row in rows]
    for record in records:
        record["present"] = bool(record["present"])
    return records


def delete_student(owner_id: int | str, student_id: int, access_token: str | None = None) -> bool:
    """Remove one local roster entry owned by this user and its attendance rows."""
    if _remote_roster_enabled(owner_id, access_token):
        result = _remote_table(access_token, "classpulse_students").delete().eq(
            "owner_id", str(owner_id)
        ).eq("id", int(student_id)).execute()
        return bool(getattr(result, "data", None))
    with _connect() as db:
        cursor = db.execute("DELETE FROM students WHERE owner_id = ? AND id = ?", (str(owner_id), int(student_id)))
        return cursor.rowcount > 0


def get_attendance_summary(owner_id: int | str, session_date: str, class_name: str) -> dict[str, int | float]:
    """Count manual roster confirmations for one owner, class, and date."""
    records = list_attendance(owner_id, session_date, class_name)
    enrollment = len(records)
    present = sum(1 for record in records if record["status"] == "present")
    return {
        "present_count": present,
        "enrollment_count": enrollment,
        "attendance_rate": round(100 * present / enrollment) if enrollment else 0,
    }


def create_session(
    owner_id: int | str,
    class_name: str,
    *,
    enrollment_count: int = 0,
    attendance_count: int = 0,
    engagement_score: float | None = None,
    participation_count: int = 0,
    summary: dict[str, Any] | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    access_token: str | None = None,
) -> int | str:
    """Persist a session summary and return its local ID."""
    if not class_name or not class_name.strip():
        raise ValueError("class_name is required")
    counts = (enrollment_count, attendance_count, participation_count)
    if any(not isinstance(value, int) or value < 0 for value in counts):
        raise ValueError("session counts must be non-negative integers")
    if engagement_score is not None and not 0 <= float(engagement_score) <= 100:
        raise ValueError("engagement_score must be between 0 and 100")
    timestamp = started_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Remote sync is opt-in: it uploads only the explicit session summary fields,
    # never source video/audio, student names, or biometric data.
    if _supabase_sync_enabled() and access_token and _remote_user_id(owner_id):
        try:
            result = _supabase_table(access_token).insert({
                "owner_id": str(owner_id),
                "class_name": class_name.strip(),
                "started_at": timestamp,
                "ended_at": ended_at,
                "enrollment_count": enrollment_count,
                "attendance_count": attendance_count,
                "engagement_score": None if engagement_score is None else float(engagement_score),
                "participation_count": participation_count,
                "summary": _remote_summary(summary or {}),
            }).execute()
            data = getattr(result, "data", None) or []
            if data:
                return data[0].get("id", 0)
        except Exception:
            # A remote outage or missing optional schema does not block local use.
            pass

    with _connect() as db:
        cursor = db.execute(
            """INSERT INTO sessions (
                owner_id, class_name, started_at, ended_at, enrollment_count,
                attendance_count, engagement_score, participation_count, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(owner_id), class_name.strip(), timestamp, ended_at,
                enrollment_count, attendance_count,
                None if engagement_score is None else float(engagement_score),
                participation_count, json.dumps(summary or {}, ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid)


def list_sessions(owner_id: int | str, limit: int = 20, access_token: str | None = None) -> list[dict[str, Any]]:
    """Return recent session summaries for one authenticated owner."""
    limit = max(1, min(int(limit), 100))
    if _supabase_sync_enabled() and access_token and _remote_user_id(owner_id):
        try:
            response = _supabase_table(access_token).select(
                "id,class_name,started_at,ended_at,enrollment_count,attendance_count,engagement_score,participation_count,summary"
            ).order("started_at", desc=True).limit(limit).execute()
            return list(response.data or [])
        except Exception:
            pass
    with _connect() as db:
        rows = db.execute(
            """SELECT id, class_name, started_at, ended_at, enrollment_count,
                      attendance_count, engagement_score, participation_count, summary_json
               FROM sessions WHERE owner_id = ? ORDER BY started_at DESC LIMIT ?""",
            (str(owner_id), limit),
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        try:
            item["summary"] = json.loads(item.pop("summary_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            item["summary"] = {}
        results.append(item)
    return results


def get_dashboard_data(
    user_id: int | str | None = None,
    access_token: str | None = None,
    *,
    owner_id: int | str | None = None,
) -> dict[str, Any]:
    """Aggregate dashboard cards and recent sessions without exposing other users."""
    # ``owner_id`` remains as a backwards-compatible alias.
    if user_id is None:
        user_id = owner_id
    if user_id is not None and _supabase_sync_enabled() and access_token and _remote_user_id(user_id):
        sessions = list_sessions(user_id, limit=100, access_token=access_token)
        # A successful empty remote response should remain empty; a remote failure
        # already falls through to local lookup in list_sessions, so both paths work.
        return _aggregate_dashboard(sessions)
    if user_id is None:
        return _aggregate_dashboard([])
    with _connect() as db:
        rows = db.execute(
            """SELECT id, class_name, started_at, ended_at, enrollment_count,
                      attendance_count, engagement_score, participation_count
               FROM sessions WHERE owner_id = ? ORDER BY started_at DESC""",
            (str(user_id),),
        ).fetchall()
    return _aggregate_dashboard([dict(row) for row in rows])


def _aggregate_dashboard(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(s["engagement_score"]) for s in sessions if s["engagement_score"] is not None]
    week_count = 0
    now = datetime.now(timezone.utc)
    for session in sessions:
        try:
            stamp = datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if (now - stamp.astimezone(timezone.utc)).days < 7:
                week_count += 1
        except (TypeError, ValueError):
            continue
    enrollment = sum(int(s["enrollment_count"] or 0) for s in sessions)
    present = sum(int(s["attendance_count"] or 0) for s in sessions)
    return {
        "attendance_rate": round(100 * present / enrollment) if enrollment else 0,
        "attendance_total": present,
        "enrollment_total": enrollment,
        "engagement_average": round(sum(scores) / len(scores)) if scores else None,
        "participation_total": sum(int(s["participation_count"] or 0) for s in sessions),
        "sessions_this_week": week_count,
        "recent_sessions": sessions[:8],
        "session_count": len(sessions),
    }


def delete_session(owner_id: int | str, session_id: int) -> bool:
    """Delete only a session belonging to its owner; return whether it existed."""
    with _connect() as db:
        cursor = db.execute(
            "DELETE FROM sessions WHERE id = ? AND owner_id = ?",
            (int(session_id), str(owner_id)),
        )
        return cursor.rowcount > 0


def _supabase_sync_enabled() -> bool:
    return (
        os.getenv("SUPABASE_SYNC_ENABLED", "").strip().casefold() in {"1", "true", "yes"}
        and bool(os.getenv("SUPABASE_URL", "").strip())
        and bool(os.getenv("SUPABASE_ANON_KEY", "").strip())
        and bool(importlib.util.find_spec("supabase"))
    )


def _remote_user_id(owner_id: int | str) -> bool:
    # Local SQLite IDs are numeric; Supabase Auth IDs are UUID strings.
    return isinstance(owner_id, str) and len(owner_id) >= 30


def _supabase_table(access_token: str):
    return _remote_table(access_token, "classpulse_session_summaries")


def _remote_roster_enabled(owner_id: int | str, access_token: str | None) -> bool:
    return bool(access_token and _remote_user_id(owner_id) and _supabase_sync_enabled())


def _remote_table(access_token: str | None, table_name: str):
    if not access_token:
        raise RuntimeError("A signed-in Supabase session is required for remote storage.")
    try:
        from supabase import create_client  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Supabase sync is enabled but the optional supabase package is not installed") from exc
    client = create_client(os.environ["SUPABASE_URL"].strip(), os.environ["SUPABASE_ANON_KEY"].strip())
    # Use the user JWT so database row-level security policies remain in force.
    client.postgrest.auth(access_token)
    # Namespace the remote table so enabling ClassPulse cannot collide with
    # unrelated data in a Supabase project the user already owns.
    return client.table(table_name)


def _sync_legacy_local_roster(owner_id: int | str, access_token: str) -> None:
    """Copy this user's old SQLite roster once when the remote roster is empty."""
    migrations = _remote_table(access_token, "classpulse_data_migrations")
    marker = migrations.select("migration_key").eq(
        "owner_id", str(owner_id)
    ).eq("migration_key", "sqlite_roster_v1").limit(1).execute().data or []
    if marker:
        return
    local_classes = list_classes(owner_id)
    local_students = list_students(owner_id)
    local_attendance = list_attendance(owner_id)
    classes = _remote_table(access_token, "classpulse_classes")
    students = _remote_table(access_token, "classpulse_students")
    class_students = _remote_table(access_token, "classpulse_class_students")
    attendance = _remote_table(access_token, "classpulse_attendance_records")
    if local_classes:
        classes.upsert([
            {"owner_id": str(owner_id), "name": row["name"], "created_at": row["created_at"]}
            for row in local_classes
        ], on_conflict="owner_id,name").execute()
    remote_classes = classes.select("id,name").eq("owner_id", str(owner_id)).execute().data or []
    class_ids = {str(row["name"]): int(row["id"]) for row in remote_classes}
    if local_students:
        students.upsert([
            {"owner_id": str(owner_id), "student_code": row["student_code"], "name": row["name"], "created_at": row["created_at"]}
            for row in local_students
        ], on_conflict="owner_id,student_code").execute()
    remote_students = students.select("id,student_code").eq("owner_id", str(owner_id)).execute().data or []
    student_ids = {str(row["student_code"]): int(row["id"]) for row in remote_students}
    local_class_ids = {int(row["id"]): str(row["name"]) for row in local_classes}
    local_student_ids = {int(row["id"]): str(row["student_code"]) for row in local_students}
    memberships = []
    for row in local_classes:
        for student in list_students(owner_id, int(row["id"])):
            remote_student_id = student_ids.get(str(student["student_code"]))
            if remote_student_id is not None:
                memberships.append({
                    "owner_id": str(owner_id), "class_id": class_ids[str(row["name"])],
                    "student_id": remote_student_id,
                })
    if memberships:
        class_students.upsert(memberships, on_conflict="class_id,student_id").execute()
    if local_attendance:
        attendance.upsert([
            {
                "owner_id": str(owner_id),
                "student_pk": student_ids[local_student_ids[int(row["student_id"])]],
                "session_date": row["session_date"],
                "class_name": row["class_name"],
                "status": row["status"],
                "marked_at": row["marked_at"],
            }
            for row in local_attendance
            if int(row["student_id"]) in local_student_ids and row["class_name"] in class_ids
        ], on_conflict="owner_id,student_pk,session_date,class_name").execute()
    migrations.upsert({
        "owner_id": str(owner_id), "migration_key": "sqlite_roster_v1",
    }, on_conflict="owner_id,migration_key").execute()


def _remote_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Keep sync payloads to small group aggregates and approved codes only."""
    clean: dict[str, Any] = {}
    trend = summary.get("trend_points")
    if isinstance(trend, list):
        points = []
        for value in trend[:120]:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if 0 <= number <= 100:
                points.append(round(number, 1))
        clean["trend_points"] = points
    for key in ("video_quality", "audio_quality"):
        value = summary.get(key)
        if isinstance(value, str) and value in {"good", "fair", "low", "unavailable"}:
            clean[key] = value
    codes = summary.get("recommendation_codes")
    allowed = {"quick_check_in", "add_visual_example", "repeat_key_point", "adjust_audio", "review_occlusion"}
    if isinstance(codes, list):
        clean["recommendation_codes"] = [value for value in codes if isinstance(value, str) and value in allowed][:10]
    return clean

