"""Hybrid Assistant for DeskOS: Gemini-powered LLM intent with safe local execution and fallback."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable

from gemini_adapter import GeminiAdapter, GeminiError
from workspace_auth import is_authenticated
from services.calendar_service import GoogleCalendarService
from services.gmail_service import GmailService
from services.docs_service import GoogleDocsService


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
        self.calendar_service = GoogleCalendarService()
        self.gmail_service = GmailService()
        self.docs_service = GoogleDocsService()


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
        pending_tasks = []
        calendar_events = []
        try:
            active_reminders = self.reminder_store.list_reminders(include_inactive=False)[:10]
            pending_tasks = self.reminder_store.list_tasks(include_completed=False)[:10]
        except Exception:
            pass

        if is_authenticated():
            try:
                calendar_events = self.calendar_service.get_today_events()
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
            "pending_tasks": pending_tasks,
            "upcoming_calendar_events": calendar_events,
        }

        # Query Gemini
        result = self.gemini_adapter.interpret(command, context)
        action = result.get("action", "reply")
        params = result.get("parameters", {})
        reply = result.get("reply", "")

        # Fallback check for ambient/rest phrases in case Gemini chose 'reply'
        norm_cmd = command.lower()
        if action == "reply" and re.search(r"\b(rest(\s+for\s+the\s+day)?|good\s*night|sleep(\s+mode)?|ambient(\s+mode|\s+clock)?)\b", norm_cmd):
            action = "set_ambient_mode"
            if not reply:
                reply = "Rest well for the day! Switching to ambient mode."

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
            self.reminder_store.cancel(target["id"])
            return self._result(True, reply or f"Cancelled reminder: '{target['title']}'.", tool="cancel_reminder")

        elif action == "list_reminders":
            reminders = self.reminder_store.list_reminders()
            if not reminders:
                return self._result(True, "You have no active reminders right now.", tool="list_reminders", data={"reminders": []})
            items = ", ".join(f"'{r['title']}'" for r in reminders[:5])
            msg = reply or f"You have {len(reminders)} active reminder(s): {items}."
            return self._result(True, msg, tool="list_reminders", data={"reminders": reminders})

        elif action == "create_task":
            title = str(params.get("title", "")).strip()
            category = str(params.get("category", "general")).strip()
            priority = str(params.get("priority", "normal")).strip().lower()
            due_date = params.get("due_date")
            if not title:
                return self._result(False, "Could not determine task title.")
            try:
                task = self.reminder_store.create_task(title, category=category, priority=priority, due_date=due_date)
                return self._result(True, reply or f"Added task: '{title}'.", tool="create_task", data={"task": task})
            except Exception as exc:
                return self._result(False, f"Could not save task: {str(exc)}")

        elif action == "list_tasks":
            tasks = self.reminder_store.list_tasks(include_completed=False)
            if not tasks:
                return self._result(True, "You have no pending tasks right now. You are all caught up!", tool="list_tasks", data={"tasks": []})
            
            # Format clean natural speech dictating each task
            task_list_str = "; ".join(f"{i+1}. {t['title']} ({t['priority']} priority)" for i, t in enumerate(tasks))
            # If Gemini gave a generic placeholder like "fetching", override with natural dictation
            if not reply or "fetching" in reply.lower() or "checking" in reply.lower():
                msg = f"You have {len(tasks)} pending task{'s' if len(tasks) > 1 else ''}: {task_list_str}."
            else:
                msg = reply
            return self._result(True, msg, tool="list_tasks", data={"tasks": tasks})

        elif action == "complete_task":
            target_title = str(params.get("title", "")).strip().lower()
            task_id = str(params.get("task_id", "")).strip()

            matching = []
            for t in self.reminder_store.list_tasks(include_completed=False):
                if task_id and t["id"] == task_id:
                    matching = [t]
                    break
                if target_title and target_title in t["title"].lower():
                    matching.append(t)

            if not matching:
                return self._result(False, f"No pending task matched '{target_title or task_id}'.")
            
            target = matching[0]
            self.reminder_store.complete_task(target["id"])
            return self._result(True, reply or f"Completed task: '{target['title']}'!", tool="complete_task", data={"task": target})

        elif action == "start_timer" or action == "set_focus_mode":
            minutes = params.get("minutes", 25)
            try:
                minutes = int(minutes)
            except Exception:
                minutes = 25
            action_name = "Focus session" if action == "set_focus_mode" else "Timer"
            msg = reply or f"{action_name} started for {minutes} minutes."
            return self._result(True, msg, tool="start_timer", data={"minutes": minutes, "mode": "focus"})

        elif action == "set_ambient_mode":
            msg = reply or "Rest well for the day! Switching to ambient mode."
            return self._result(True, msg, tool="set_ambient_mode", data={"mode": "ambient"})

        elif action == "desk_analytics":
            analytics = self.reminder_store.get_desk_analytics()
            raw_status = self.status_provider()
            uptime_hrs = round(raw_status.get("uptime_seconds", 0) / 3600, 1)
            cpu = raw_status.get("cpu_percent", 0)
            mem = raw_status.get("memory", {}).get("percent", 0)
            
            data_payload = {**analytics, "uptime_hours": uptime_hrs, "cpu_percent": cpu, "memory_percent": mem}
            fallback_reply = (
                f"Today you have completed {analytics['tasks_completed_today']} task(s), "
                f"logged {analytics['focus_minutes_today']} minutes of focus across {analytics['focus_sessions_today']} session(s). "
                f"Your workstation has been active for {uptime_hrs} hours with CPU at {cpu}%."
            )
            return self._result(True, reply or fallback_reply, tool="desk_analytics", data=data_payload)

        elif action == "system_status":
            return self._result(True, reply or self._system_status()["message"], tool="get_system_status")

        elif action == "list_calendar_events":
            days = params.get("days", 1)
            try:
                days = int(days)
            except Exception:
                days = 1

            if not is_authenticated():
                return self._result(
                    False,
                    "Google Workspace is not connected. Run 'scripts/auth_google.py' to connect your Google Calendar.",
                    tool="list_calendar_events",
                )

            try:
                if days <= 1:
                    events = self.calendar_service.get_today_events()
                else:
                    events = self.calendar_service.get_upcoming_events(days=days)

                if not events:
                    return self._result(
                        True,
                        "You have no meetings scheduled for today. Your calendar is clear!",
                        tool="list_calendar_events",
                        data={"events": []},
                    )

                event_titles = [f"'{e['summary']}' at {e['start'][11:16] if 'T' in str(e['start']) else 'all-day'}" for e in events]
                fallback_reply = f"You have {len(events)} event{'s' if len(events) > 1 else ''} scheduled: {', '.join(event_titles)}."
                return self._result(True, reply or fallback_reply, tool="list_calendar_events", data={"events": events})
            except Exception as exc:
                return self._result(False, f"Could not fetch calendar events: {str(exc)}")

        elif action == "create_calendar_event":
            summary = str(params.get("summary", "")).strip()
            start_iso = str(params.get("start_iso", "")).strip()
            duration = params.get("duration_minutes", 30)
            desc = params.get("description", "Created via DeskOS Voice")

            if not is_authenticated():
                return self._result(False, "Google Workspace is not connected.", tool="create_calendar_event")
            if not summary or not start_iso:
                return self._result(False, "Missing summary or event start time.")

            try:
                created = self.calendar_service.create_event(
                    summary=summary,
                    start_iso=start_iso,
                    duration_minutes=int(duration),
                    description=desc,
                )
                return self._result(
                    True,
                    reply or f"Scheduled '{summary}' on your Google Calendar.",
                    tool="create_calendar_event",
                    data={"event": created},
                )
            except Exception as exc:
                return self._result(False, f"Failed to create calendar event: {str(exc)}")

        elif action == "list_emails":
            if not is_authenticated():
                return self._result(False, "Google Workspace is not connected.", tool="list_emails")

            query = str(params.get("query", "is:unread in:inbox")).strip()
            try:
                emails = self.gmail_service.search_emails(query=query, max_results=5)
                if not emails:
                    return self._result(
                        True,
                        "You have no unread emails in your inbox.",
                        tool="list_emails",
                        data={"emails": []},
                    )

                email_summaries = [f"From {e['from'].split('<')[0].strip()}: {e['subject']}" for e in emails]
                fallback_reply = f"You have {len(emails)} unread email{'s' if len(emails) > 1 else ''}: {'; '.join(email_summaries)}."
                return self._result(True, reply or fallback_reply, tool="list_emails", data={"emails": emails})
            except Exception as exc:
                return self._result(False, f"Could not fetch emails: {str(exc)}")

        elif action == "create_email_draft":
            if not is_authenticated():
                return self._result(False, "Google Workspace is not connected.", tool="create_email_draft")

            to_addr = str(params.get("to", "")).strip()
            subject = str(params.get("subject", "")).strip()
            body = str(params.get("body", "")).strip()

            if not to_addr or not subject:
                return self._result(False, "Recipient email and subject are required for drafting an email.")

            try:
                draft = self.gmail_service.create_draft(to_email=to_addr, subject=subject, body_text=body)
                return self._result(
                    True,
                    reply or f"Created email draft to {to_addr} with subject '{subject}'.",
                    tool="create_email_draft",
                    data={"draft": draft},
                )
            except Exception as exc:
                return self._result(False, f"Could not create email draft: {str(exc)}")

        elif action == "create_doc_summary":
            if not is_authenticated():
                return self._result(False, "Google Workspace is not connected.", tool="create_doc_summary")

            title = params.get("title")
            content = params.get("content")
            try:
                doc = self.docs_service.create_daily_summary_doc(title=title, initial_content=content)
                return self._result(
                    True,
                    reply or f"Created Google Document: '{doc['title']}'.",
                    tool="create_doc_summary",
                    data={"doc": doc},
                )
            except Exception as exc:
                return self._result(False, f"Could not create Google Doc: {str(exc)}")


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
