"""SQLite persistence and due-reminder dispatch for DeskOS."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
RECURRENCES = {"none", "daily", "weekly"}


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime that includes an explicit UTC offset."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("due_at must be an ISO-8601 datetime with timezone information")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("due_at must be a valid ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("due_at must include a timezone offset")
    return parsed


def utc_string(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_timezone(value: str | None) -> str:
    if value is None:
        return "UTC"
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("timezone must be a valid IANA timezone name")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone name") from exc
    return value


def next_occurrence(due_at: datetime, recurrence: str, timezone_name: str, now: datetime) -> datetime:
    """Advance a recurring wall-clock schedule to its next future occurrence."""
    zone = ZoneInfo(timezone_name)
    local_due = due_at.astimezone(zone)
    period_days = 1 if recurrence == "daily" else 7
    days_late = max(0, (now.astimezone(zone).date() - local_due.date()).days)
    steps = max(1, days_late // period_days)

    while True:
        next_day = local_due.date() + timedelta(days=steps * period_days)
        candidate = datetime.combine(next_day, local_due.timetz().replace(tzinfo=None), tzinfo=zone)
        # If a daylight-saving transition skips this wall time, move to the
        # first valid local minute rather than silently scheduling in the past.
        for _ in range(181):
            round_trip = candidate.astimezone(UTC).astimezone(zone)
            if round_trip.replace(tzinfo=None) == candidate.replace(tzinfo=None):
                break
            candidate += timedelta(minutes=1)
        if candidate.astimezone(UTC) > now.astimezone(UTC):
            return candidate.astimezone(UTC)
        steps += 1


class ReminderStore:
    """Small connection-per-operation SQLite store with idempotent dispatch."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        self.initialize()
        self.path.chmod(0o600)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def connection(self):
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
                    due_at TEXT NOT NULL,
                    timezone TEXT NOT NULL DEFAULT 'UTC',
                    recurrence TEXT NOT NULL CHECK(recurrence IN ('none', 'daily', 'weekly')),
                    status TEXT NOT NULL CHECK(status IN ('active', 'completed', 'cancelled')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS reminders_due_idx
                    ON reminders(status, due_at);
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    reminder_id TEXT NOT NULL REFERENCES reminders(id),
                    occurrence_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    acknowledged_at TEXT,
                    UNIQUE(reminder_id, occurrence_at)
                );
                CREATE INDEX IF NOT EXISTS notifications_pending_idx
                    ON notifications(acknowledged_at, created_at);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
                    category TEXT NOT NULL DEFAULT 'general',
                    priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('low', 'normal', 'high')),
                    due_date TEXT,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'completed', 'cancelled')),
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS tasks_status_idx ON tasks(status, created_at);
                CREATE TABLE IF NOT EXISTS desk_docs (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    doc_url TEXT NOT NULL,
                    summary_snippet TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS desk_docs_created_idx ON desk_docs(created_at DESC);
                CREATE TABLE IF NOT EXISTS analytics_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    value_num REAL DEFAULT 0,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS analytics_type_idx ON analytics_events(event_type, created_at);
                """
            )

    @staticmethod
    def _reminder(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def create(self, title: str, due_at: str, recurrence: str = "none", timezone_name: str | None = None) -> dict[str, Any]:
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
            raise ValueError("title must contain 1 to 160 characters")
        if recurrence not in RECURRENCES:
            raise ValueError("recurrence must be none, daily, or weekly")
        parsed_due = parse_datetime(due_at)
        tz_name = validate_timezone(timezone_name)
        if recurrence != "none":
            # Validate that the supplied zone is meaningful for the chosen instant.
            parsed_due = parsed_due.astimezone(ZoneInfo(tz_name))
        now = datetime.now(UTC)
        if parsed_due.astimezone(UTC) <= now:
            raise ValueError("due_at must be in the future")
        reminder_id = str(uuid4())
        now_text = utc_string(now)
        values = (reminder_id, title.strip(), utc_string(parsed_due), tz_name, recurrence, "active", now_text, now_text)
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO reminders
                   (id, title, due_at, timezone, recurrence, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            row = connection.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return self._reminder(row)

    def list_reminders(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM reminders"
        params: tuple[Any, ...] = ()
        if not include_inactive:
            query += " WHERE status = 'active'"
        query += " ORDER BY due_at ASC, created_at ASC"
        with self.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._reminder(row) for row in rows]

    def update(self, reminder_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"title", "due_at", "recurrence", "timezone"}
        if not changes or set(changes) - allowed:
            raise ValueError("update must contain title, due_at, recurrence, or timezone only")
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            if row is None:
                return None
            if row["status"] != "active":
                raise ValueError("only active reminders can be edited")
            title = changes.get("title", row["title"])
            if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
                raise ValueError("title must contain 1 to 160 characters")
            recurrence = changes.get("recurrence", row["recurrence"])
            if recurrence not in RECURRENCES:
                raise ValueError("recurrence must be none, daily, or weekly")
            timezone_name = validate_timezone(changes.get("timezone", row["timezone"]))
            due_value = changes.get("due_at", row["due_at"])
            parsed_due = parse_datetime(due_value)
            if recurrence != "none":
                parsed_due = parsed_due.astimezone(ZoneInfo(timezone_name))
            if parsed_due.astimezone(UTC) <= datetime.now(UTC):
                raise ValueError("due_at must be in the future")
            updated_at = utc_string(datetime.now(UTC))
            connection.execute(
                """UPDATE reminders SET title = ?, due_at = ?, timezone = ?, recurrence = ?, updated_at = ?
                   WHERE id = ?""",
                (title.strip(), utc_string(parsed_due), timezone_name, recurrence, updated_at, reminder_id),
            )
            updated = connection.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return self._reminder(updated)

    def complete(self, reminder_id: str) -> bool:
        return self._set_status(reminder_id, "completed")

    def cancel(self, reminder_id: str) -> bool:
        return self._set_status(reminder_id, "cancelled")

    def _set_status(self, reminder_id: str, status: str) -> bool:
        with self.connection() as connection:
            connection.execute(
                "UPDATE reminders SET status = ?, updated_at = ? WHERE id = ? AND status = 'active'",
                (status, utc_string(datetime.now(UTC)), reminder_id),
            )
            exists = connection.execute("SELECT 1 FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return exists is not None

    def dispatch_due(self, now: datetime | None = None) -> int:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        current_text = utc_string(current)
        dispatched = 0
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            due_rows = connection.execute(
                "SELECT * FROM reminders WHERE status = 'active' AND due_at <= ? ORDER BY due_at ASC",
                (current_text,),
            ).fetchall()
            for row in due_rows:
                occurrence_at = row["due_at"]
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO notifications
                       (id, reminder_id, occurrence_at, title, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (str(uuid4()), row["id"], occurrence_at, row["title"], current_text),
                )
                dispatched += cursor.rowcount
                if row["recurrence"] == "none":
                    connection.execute(
                        "UPDATE reminders SET status = 'completed', updated_at = ? WHERE id = ?",
                        (current_text, row["id"]),
                    )
                else:
                    next_due = next_occurrence(
                        parse_datetime(occurrence_at), row["recurrence"], row["timezone"], current
                    )
                    connection.execute(
                        "UPDATE reminders SET due_at = ?, updated_at = ? WHERE id = ?",
                        (utc_string(next_due), current_text, row["id"]),
                    )
        return dispatched

    def list_pending_notifications(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT id, reminder_id, occurrence_at, title, created_at
                   FROM notifications WHERE acknowledged_at IS NULL
                   ORDER BY created_at ASC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def acknowledge(self, notification_id: str) -> bool:
        with self.connection() as connection:
            connection.execute(
                "UPDATE notifications SET acknowledged_at = ? WHERE id = ? AND acknowledged_at IS NULL",
                (utc_string(datetime.now(UTC)), notification_id),
            )
            exists = connection.execute("SELECT 1 FROM notifications WHERE id = ?", (notification_id,)).fetchone()
        return exists is not None

    # --- Task Management Methods ---

    def create_task(self, title: str, category: str = "general", priority: str = "normal", due_date: str | None = None) -> dict[str, Any]:
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            raise ValueError("title must contain 1 to 200 characters")
        if priority not in {"low", "normal", "high"}:
            priority = "normal"
        task_id = str(uuid4())
        now_text = utc_string(datetime.now(UTC))
        values = (task_id, title.strip(), category.strip(), priority, due_date, "pending", now_text)
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO tasks (id, title, category, priority, due_date, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row)

    def list_tasks(self, include_completed: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM tasks"
        if not include_completed:
            query += " WHERE status = 'pending'"
        query += " ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, created_at DESC"
        with self.connection() as connection:
            rows = connection.execute(query).fetchall()
        return [dict(row) for row in rows]

    def complete_task(self, task_id: str) -> bool:
        now_text = utc_string(datetime.now(UTC))
        with self.connection() as connection:
            connection.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ? WHERE id = ? AND status = 'pending'",
                (now_text, task_id),
            )
            exists = connection.execute("SELECT 1 FROM tasks WHERE id = ? AND status = 'completed'", (task_id,)).fetchone()
            if exists:
                # Log analytics event for completed task
                connection.execute(
                    "INSERT INTO analytics_events (id, event_type, value_num, created_at) VALUES (?, 'task_completed', 1, ?)",
                    (str(uuid4()), now_text),
                )
        return exists is not None

    def delete_task(self, task_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0

    # --- Desk Analytics Methods ---

    def log_analytics_event(self, event_type: str, value_num: float = 0.0, metadata_json: str | None = None) -> None:
        now_text = utc_string(datetime.now(UTC))
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO analytics_events (id, event_type, value_num, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid4()), event_type, value_num, metadata_json, now_text),
            )

    def get_desk_analytics(self) -> dict[str, Any]:
        """Aggregate today's analytics and lifetime task metrics."""
        today_prefix = datetime.now(UTC).strftime("%Y-%m-%d")
        with self.connection() as connection:
            # Tasks completed today
            tasks_today = connection.execute(
                "SELECT COUNT(*) as c FROM tasks WHERE status = 'completed' AND completed_at LIKE ?",
                (f"{today_prefix}%",),
            ).fetchone()["c"]

            # Pending tasks
            pending_tasks = connection.execute(
                "SELECT COUNT(*) as c FROM tasks WHERE status = 'pending'"
            ).fetchone()["c"]

            # Focus sessions completed today
            focus_events = connection.execute(
                "SELECT SUM(value_num) as total_min, COUNT(*) as sessions FROM analytics_events WHERE event_type = 'focus_session' AND created_at LIKE ?",
                (f"{today_prefix}%",),
            ).fetchone()
            focus_minutes = focus_events["total_min"] or 0
            focus_sessions = focus_events["sessions"] or 0

            # Total active reminders
            active_reminders = connection.execute(
                "SELECT COUNT(*) as c FROM reminders WHERE status = 'active'"
            ).fetchone()["c"]

        return {
            "tasks_completed_today": tasks_today,
            "tasks_pending": pending_tasks,
            "focus_minutes_today": round(focus_minutes),
            "focus_sessions_today": focus_sessions,
            "active_reminders": active_reminders,
        }

    # --- Desk Documents Methods ---

    def save_doc(self, doc_id: str, title: str, doc_url: str, summary_snippet: str | None = None) -> dict[str, Any]:
        now_text = utc_string(datetime.now(UTC))
        with self.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO desk_docs (id, title, doc_url, summary_snippet, created_at) VALUES (?, ?, ?, ?, ?)",
                (doc_id, title, doc_url, summary_snippet, now_text),
            )
        return {"id": doc_id, "title": title, "doc_url": doc_url, "summary_snippet": summary_snippet, "created_at": now_text}

    def list_docs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id, title, doc_url, summary_snippet, created_at FROM desk_docs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

