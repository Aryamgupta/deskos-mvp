"""DeskOS Google Calendar Integration Service.

Provides event listing, creation, and meeting queries for DeskOS voice commands and car console.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional
import zoneinfo

from googleapiclient.discovery import build

from workspace_auth import get_credentials


class GoogleCalendarService:
    def __init__(self, timezone_str: str = "Asia/Kolkata"):
        self.timezone_str = timezone_str
        self._tz = zoneinfo.ZoneInfo(timezone_str)
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds = get_credentials(interactive=False)
            if not creds:
                raise RuntimeError("Google account is not authenticated. Please run scripts/auth_google.py.")
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def get_today_events(self) -> List[Dict[str, Any]]:
        """Retrieve all events scheduled for today in the user's timezone."""
        now = datetime.now(self._tz)
        start_of_day = datetime.combine(now.date(), time.min, tzinfo=self._tz)
        end_of_day = datetime.combine(now.date(), time.max, tzinfo=self._tz)
        return self.get_events_between(start_of_day, end_of_day)

    def get_upcoming_events(self, days: int = 3, max_results: int = 15) -> List[Dict[str, Any]]:
        """Retrieve upcoming events starting from now up to `days` days ahead."""
        now = datetime.now(self._tz)
        end_time = now + timedelta(days=days)
        return self.get_events_between(now, end_time, max_results=max_results)

    def get_events_between(
        self, start_dt: datetime, end_dt: datetime, max_results: int = 50
    ) -> List[Dict[str, Any]]:
        """List events in calendar within specified time window."""
        service = self._get_service()
        time_min = start_dt.isoformat()
        time_max = end_dt.isoformat()

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        raw_items = events_result.get("items", [])
        parsed = []
        for item in raw_items:
            start_info = item.get("start", {})
            end_info = item.get("end", {})
            # All-day events have 'date', timed events have 'dateTime'
            start_val = start_info.get("dateTime") or start_info.get("date")
            end_val = end_info.get("dateTime") or end_info.get("date")

            parsed.append(
                {
                    "id": item.get("id"),
                    "summary": item.get("summary", "Untitled Event"),
                    "start": start_val,
                    "end": end_val,
                    "location": item.get("location"),
                    "description": item.get("description"),
                    "htmlLink": item.get("htmlLink"),
                    "status": item.get("status"),
                }
            )
        return parsed

    def create_event(
        self,
        summary: str,
        start_iso: str,
        end_iso: Optional[str] = None,
        duration_minutes: int = 30,
        description: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new event in user's primary calendar."""
        service = self._get_service()

        # Parse start datetime
        if "T" in start_iso:
            start_dt = datetime.fromisoformat(start_iso)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=self._tz)
        else:
            # Date only (YYYY-MM-DD)
            start_dt = datetime.fromisoformat(f"{start_iso}T09:00:00").replace(tzinfo=self._tz)

        if end_iso:
            end_dt = datetime.fromisoformat(end_iso)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=self._tz)
        else:
            end_dt = start_dt + timedelta(minutes=duration_minutes)

        event_body = {
            "summary": summary,
            "description": description or "Created by DeskOS Voice Assistant",
            "location": location,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": self.timezone_str,
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": self.timezone_str,
            },
        }

        created = service.events().insert(calendarId="primary", body=event_body).execute()
        return {
            "id": created.get("id"),
            "summary": created.get("summary"),
            "start": created.get("start", {}).get("dateTime"),
            "end": created.get("end", {}).get("dateTime"),
            "htmlLink": created.get("htmlLink"),
        }

    def delete_event(self, event_id: str) -> bool:
        """Delete an event by ID."""
        service = self._get_service()
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return True

