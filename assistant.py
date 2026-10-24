"""Hybrid Assistant for DeskOS: Gemini-powered LLM intent with safe local execution and fallback."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable

from gemini_adapter import GeminiAdapter, GeminiError


class AssistantRouter:
    """Intelligent command routing powered by Gemini with fallback to deterministic local tools."""

    def __init__(
        self,
        reminder_store,
        status_provider: Callable[[], dict[str, Any]],
        clock: Callable[[], datetime] | None = None,
        gemini_adapter: GeminiAdapter | None = None,
    ):
        self.reminder_store = reminder_store
        self.status_provider = status_provider
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.gemini_adapter = gemini_adapter

    def handle(self, command: str, confirm: bool = False, timezone_name: str | None = None) -> dict[str, Any]:
        if not isinstance(confirm, bool):
            return self._result(False, "Confirmation must be an explicit yes or no.")
        if not isinstance(command, str) or not command.strip():
            return self._result(False, "Type a command first.")
        if len(command) > 1000:
            return self._result(False, "Commands must be 1000 characters or fewer.")

        # If Gemini adapter is available, attempt intelligent interpretation
        if self.gemini_adapter:
            try:
                return self._handle_with_gemini(command.strip(), confirm, timezone_name)
            except GeminiError as exc:
                # If Gemini fails or quota is exhausted, fall through to deterministic router
                local_res = self._handle_deterministic(command, confirm)
                if local_res.get("ok"):
                    return local_res
                return self._result(False, f"{str(exc)}")
            except Exception as exc:
                local_res = self._handle_deterministic(command, confirm)
                if local_res.get("ok"):
                    return local_res
                return self._result(False, f"Assistant error: {str(exc)[:140]}")

        # Deterministic fallback when no Gemini API key is configured
        return self._handle_deterministic(command, confirm)

    def _handle_with_gemini(self, command: str, confirm: bool, timezone_name: str | None) -> dict[str, Any]:
        now = self.clock()
        tz_str = timezone_name or str(now.tzinfo) or "UTC"
        
        # Build context for the LLM
        active_reminders = []
        try:
            active_reminders = self.reminder_store.list_reminders(include_inactive=False)[:10]
        except Exception:
            pass

        sys_status = {}
        try:
            raw_status = self.status_provider()
            sys_status = {
                "cpu_percent": raw_status.get("cpu_percent"),
                "memory_percent": raw_status.get("memory", {}).get("percent"),
                "disk_free_gb": round(raw_status.get("disk", {}).get("free", 0) / (1024**3), 1),
                "uptime_seconds": raw_status.get("uptime_seconds"),
                "active_runtimes": [r.get("runtime") for r in raw_status.get("runtimes", [])],
            }
        except Exception:
            pass

        context = {
            "local_time": now.isoformat(),
            "timezone": tz_str,
            "system_status": sys_status,
            "active_reminders": active_reminders,
        }

        # Query Gemini
        result = self.gemini_adapter.interpret(command, context)
        action = result.get("action", "reply")
        params = result.get("parameters", {})
        reply = result.get("reply", "")

        # Execute safe action
        if action == "create_reminder":
            title = str(params.get("title", "")).strip()
            due_at = str(params.get("due_at", "")).strip()
            recurrence = params.get("recurrence", "none")
            reminder_tz = params.get("timezone", tz_str)

            if not title or not due_at:
                return self._result(False, "Could not determine reminder title or due time.")

            try:
                created = self.reminder_store.create(title, due_at, recurrence, reminder_tz)
                return self._result(True, reply or f"Reminder set: {title}", tool="create_reminder", data={"reminder": created})
            except Exception as exc:
                return self._result(False, f"Could not create reminder: {str(exc)}")

        elif action == "cancel_reminder":
            target_title = str(params.get("title", "")).strip().lower()
            reminder_id = str(params.get("reminder_id", "")).strip()

            matching = []
            for r in self.reminder_store.list_reminders():
                if reminder_id and r["id"] == reminder_id:
                    matching = [r]
                    break
                if target_title and target_title in r["title"].lower():
                    matching.append(r)

            if not matching:
                return self._result(False, f"No active reminder matched '{target_title or reminder_id}'.")
            if len(matching) > 1:
                return self._result(False, f"Multiple reminders match '{target_title}'. Please be more specific.")

            target = matching[0]
            if not confirm:
                return self._result(
                    True,
                    f"Are you sure you want to cancel the reminder: '{target['title']}'?",
                    confirmation_required=True,
                    data={"target_id": target["id"]},
                )

            self.reminder_store.cancel(target["id"])
            return self._result(True, reply or f"Cancelled reminder: '{target['title']}'.", tool="cancel_reminder")

        elif action == "list_reminders":
            reminders = self.reminder_store.list_reminders()
            if not reminders:
                return self._result(True, "You have no active reminders right now.", tool="list_reminders", data={"reminders": []})
            items = ", ".join(f"'{r['title']}'" for r in reminders[:5])
            msg = reply or f"You have {len(reminders)} active reminder(s): {items}."
            return self._result(True, msg, tool="list_reminders", data={"reminders": reminders})

        elif action == "system_status":
            return self._result(True, reply or self._system_status()["message"], tool="get_system_status")

        # Conversational reply or answer
        return self._result(True, reply)

    def _handle_deterministic(self, command: str, confirm: bool = False) -> dict[str, Any]:
        """Original deterministic logic for offline use."""
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
            return self._result(True, "There is no microphone session active. The text assistant is ready.")

        create_match = re.fullmatch(r"^(?:please\s+)?(?:remind me to|create reminder to)\s+(.+?)\s+in\s+(\d{1,5})\s+(minutes?|hours?|days?)\s*$", command.strip(), re.I)
        if create_match:
            title, amount_str, unit = create_match.groups()
            amount = int(amount_str)
            seconds = amount * (60 if "min" in unit else 3600 if "hour" in unit else 86400)
            from datetime import timedelta
            due = self.clock() + timedelta(seconds=seconds)
            due_iso = due.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            created = self.reminder_store.create(title, due_iso, "none", "UTC")
            return self._result(True, f"Reminder set for {title} in {amount} {unit}.", tool="create_reminder", data={"reminder": created})

        return self._result(
            False,
            "I could not understand that locally. Configure GEMINI_API_KEY in .env for advanced AI capabilities, or try: 'What time is it?', 'Show system status', 'Remind me to [action] in [X] minutes'.",
        )

    @staticmethod
    def _result(ok: bool, message: str, **extra: Any) -> dict[str, Any]:
        return {"ok": ok, "message": message, **extra}

    def _time(self) -> dict[str, Any]:
        now = self.clock()
        return self._result(True, f"It is {now.strftime('%-I:%M %p')}.", tool="get_time", data={"local_time": now.isoformat()})

    def _system_status(self) -> dict[str, Any]:
        data = self.status_provider()
        cpu = data.get("cpu_percent", 0)
        mem = data.get("memory", {}).get("percent", 0)
        temp = data.get("cpu_temperature")
        temp_str = f" at {temp['celsius']}°C" if temp else ""
        return self._result(True, f"Laptop is running with CPU {cpu}%, RAM {mem}%{temp_str}.", tool="get_system_status", data=data)

    def _device_status(self) -> dict[str, Any]:
        return self._result(True, "Laptop is online and responding.", tool="get_device_status")

    def _list_reminders(self) -> dict[str, Any]:
        reminders = self.reminder_store.list_reminders()
        if not reminders:
            return self._result(True, "You have no active reminders.", tool="list_reminders", data={"reminders": []})
        lines = [f"• {r['title']}" for r in reminders[:5]]
        return self._result(True, "Active reminders:\n" + "\n".join(lines), tool="list_reminders", data={"reminders": reminders})
