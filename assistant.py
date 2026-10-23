"""Deterministic, local-only DeskOS command routing. No model or shell access."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable


TOOL_SCHEMAS = {
    "get_time": {"description": "Return the local workstation time", "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    "get_system_status": {"description": "Return a limited local system-health summary", "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    "get_device_status": {"description": "Check whether the monitored laptop status is available", "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    "list_reminders": {"description": "List active local reminders", "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    "create_reminder": {
        "description": "Create a local reminder with an explicit relative time",
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 160}, "amount": {"type": "integer", "minimum": 1}, "unit": {"type": "string", "enum": ["minutes", "hours", "days", "weeks"]}},
            "required": ["title", "amount", "unit"],
            "additionalProperties": False,
        },
    },
    "cancel_reminder": {
        "description": "Cancel one uniquely matched active reminder after confirmation",
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 160}, "confirmed": {"type": "boolean"}},
            "required": ["title", "confirmed"],
            "additionalProperties": False,
        },
    },
}

_CREATE_PATTERNS = (
    re.compile(r"^(?:please\s+)?remind me to\s+(.+?)\s+in\s+(\d{1,5})\s+(minutes?|mins?|hours?|hrs?|days?|weeks?)\s*[.!?]*$", re.I),
    re.compile(r"^(?:please\s+)?(?:create|add) (?:a )?reminder to\s+(.+?)\s+in\s+(\d{1,5})\s+(minutes?|mins?|hours?|hrs?|days?|weeks?)\s*[.!?]*$", re.I),
)
_CANCEL_PATTERN = re.compile(r"^(?:please\s+)?cancel (?:my )?reminder(?: to)?\s+(.+?)[.!?]*$", re.I)
_DURATION_FACTORS = {
    "minute": 60,
    "min": 60,
    "hour": 3600,
    "hr": 3600,
    "day": 86400,
    "week": 604800,
}


class AssistantRouter:
    """Allowlisted deterministic intents backed by narrowly scoped local tools."""

    def __init__(self, reminder_store, status_provider: Callable[[], dict[str, Any]], clock: Callable[[], datetime] | None = None):
        self.reminder_store = reminder_store
        self.status_provider = status_provider
        self.clock = clock or (lambda: datetime.now().astimezone())

    def handle(self, command: str, confirm: bool = False) -> dict[str, Any]:
        if not isinstance(confirm, bool):
            return self._result(False, "Confirmation must be an explicit yes or no.")
        if not isinstance(command, str) or not command.strip():
            return self._result(False, "Type a command first.")
        if len(command) > 500:
            return self._result(False, "Commands must be 500 characters or fewer.")

        normalized = re.sub(r"\s+", " ", command.strip().lower()).rstrip(".!?")
        if normalized in {"what time is it", "tell me the time", "time"}:
            return self._time()
        if normalized in {"how is my laptop doing", "show system status", "system status", "how is my system"}:
            return self._system_status()
        if normalized in {"is my laptop online", "is the laptop online", "check laptop status"}:
            return self._device_status()
        if normalized in {"show my reminders", "list reminders", "what are my reminders", "show reminders"}:
            return self._list_reminders()
        if normalized in {"stop listening", "stop voice assistant"}:
            return self._result(True, "There is no microphone session active. The text assistant is ready when you are.")

        for pattern in _CREATE_PATTERNS:
            match = pattern.fullmatch(command.strip())
            if match:
                return self._create_reminder(match.group(1), int(match.group(2)), match.group(3))

        cancel_match = _CANCEL_PATTERN.fullmatch(command.strip())
        if cancel_match:
            return self._cancel_reminder(cancel_match.group(1), confirm)

        return self._result(
            False,
            "I did not recognize that. Try: ‘What time is it?’, ‘How is my laptop doing?’, ‘Show my reminders’, ‘Remind me to stretch in 10 minutes’, or ‘Cancel reminder to stretch’.",
        )

    @staticmethod
    def _result(ok: bool, message: str, **extra: Any) -> dict[str, Any]:
        return {"ok": ok, "message": message, **extra}

    def _time(self) -> dict[str, Any]:
        now = self.clock()
        return self._result(True, f"It is {now.strftime('%-I:%M %p')}.", tool="get_time", data={"local_time": now.isoformat()})

    def _system_status(self) -> dict[str, Any]:
        status = self.status_provider()
        temperature = status.get("cpu_temperature")
        parts = [
            f"CPU {round(float(status.get('cpu_percent') or 0))}%",
            f"memory {round(float(status.get('memory', {}).get('percent') or 0))}%",
            f"storage {round(float(status.get('disk', {}).get('percent') or 0))}% used",
        ]
        if temperature:
            parts.append(f"CPU temperature {temperature['celsius']} °C")
        return self._result(True, "Laptop status: " + ", ".join(parts) + ".", tool="get_system_status", data={"hostname": status.get("hostname"), "cpu_percent": status.get("cpu_percent"), "memory_percent": status.get("memory", {}).get("percent"), "disk_percent": status.get("disk", {}).get("percent"), "cpu_temperature": temperature})

    def _device_status(self) -> dict[str, Any]:
        status = self.status_provider()
        return self._result(True, f"Your laptop is online as {status.get('hostname', 'the monitored device')}.", tool="get_device_status", data={"online": True, "hostname": status.get("hostname")})

    def _list_reminders(self) -> dict[str, Any]:
        reminders = self.reminder_store.list_reminders()
        if not reminders:
            return self._result(True, "You have no active reminders.", tool="list_reminders", data={"reminders": []})
        now = self.clock()
        entries = []
        for reminder in reminders[:10]:
            entries.append({"id": reminder["id"], "title": reminder["title"], "due_at": reminder["due_at"], "recurrence": reminder["recurrence"], "timezone": reminder["timezone"]})
        summary = "; ".join(f"{item['title']} at {datetime.fromisoformat(item['due_at'].replace('Z', '+00:00')).astimezone(now.tzinfo).strftime('%a %-I:%M %p')}" for item in entries)
        more = f" and {len(reminders) - len(entries)} more" if len(reminders) > len(entries) else ""
        return self._result(True, f"Your reminders: {summary}{more}.", tool="list_reminders", data={"reminders": entries})

    def _create_reminder(self, title: str, amount: int, unit_text: str) -> dict[str, Any]:
        clean_title = title.strip(" \t.,!?;")
        if not clean_title or len(clean_title) > 160:
            return self._result(False, "Reminder titles must contain 1 to 160 characters.")
        if amount < 1 or amount > 525600:
            return self._result(False, "Choose a time between 1 minute and 1 year from now.")
        unit = unit_text.lower().rstrip("s")
        unit = "min" if unit in {"min", "mins"} else "hr" if unit in {"hr", "hrs"} else unit
        seconds = amount * _DURATION_FACTORS.get(unit, 0)
        if seconds <= 0 or seconds > 366 * 86400:
            return self._result(False, "Choose a time between 1 minute and 1 year from now.")
        due = (self.clock() + timedelta(seconds=seconds)).astimezone(timezone.utc)
        reminder = self.reminder_store.create(clean_title, due.isoformat(), "none", "UTC")
        due_local = due.astimezone(self.clock().tzinfo)
        return self._result(True, f"I’ll remind you to {clean_title} at {due_local.strftime('%-I:%M %p')}.", tool="create_reminder", data={"reminder": reminder})

    def _cancel_reminder(self, title: str, confirm: bool) -> dict[str, Any]:
        clean_title = title.strip(" \t.,!?;")
        if not clean_title:
            return self._result(False, "Include the exact reminder title to cancel.")
        matches = [item for item in self.reminder_store.list_reminders() if item["title"].casefold() == clean_title.casefold()]
        if not matches:
            return self._result(False, f"I could not find an active reminder titled ‘{clean_title}’.", tool="cancel_reminder")
        if len(matches) > 1:
            return self._result(False, "More than one active reminder has that title. Use the reminder list to manage it.", tool="cancel_reminder")
        reminder = matches[0]
        if not confirm:
            return self._result(False, f"Cancel ‘{reminder['title']}’? This cannot be undone from the assistant.", tool="cancel_reminder", confirmation_required=True)
        self.reminder_store.cancel(reminder["id"])
        return self._result(True, f"Cancelled the reminder ‘{reminder['title']}’.", tool="cancel_reminder", data={"id": reminder["id"]})
