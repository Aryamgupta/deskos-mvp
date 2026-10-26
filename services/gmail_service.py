"""DeskOS Gmail Integration Service.

Provides email queries, summaries, draft creation, and two-step voice email sending.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build

from workspace_auth import get_credentials


class GmailService:
    def __init__(self):
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds = get_credentials(interactive=False)
            if not creds:
                raise RuntimeError("Google account is not authenticated. Please run scripts/auth_google.py.")
            self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    def get_unread_emails(self, max_results: int = 5) -> List[Dict[str, Any]]:
        """Retrieve recent unread messages from Inbox."""
        return self.search_emails(query="is:unread in:inbox", max_results=max_results)

    def search_emails(self, query: str = "in:inbox", max_results: int = 5) -> List[Dict[str, Any]]:
        """Search messages matching standard Gmail query."""
        service = self._get_service()
        response = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        messages = response.get("messages", [])

        results = []
        for msg_meta in messages:
            msg_id = msg_meta.get("id")
            msg_data = (
                service.users()
                .messages()
                .get(userId="me", id=msg_id, format="metadata", metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )

            headers = {
                h.get("name"): h.get("value")
                for h in msg_data.get("payload", {}).get("headers", [])
            }

            snippet = msg_data.get("snippet", "")
            results.append(
                {
                    "id": msg_id,
                    "threadId": msg_data.get("threadId"),
                    "from": headers.get("From", "Unknown Sender"),
                    "subject": headers.get("Subject", "(No Subject)"),
                    "date": headers.get("Date", ""),
                    "snippet": snippet,
                }
            )
        return results

    def create_draft(self, to_email: str, subject: str, body_text: str) -> Dict[str, Any]:
        """Create a new email draft in Gmail."""
        service = self._get_service()
        message = EmailMessage()
        message.set_content(body_text)
        message["To"] = to_email
        message["Subject"] = subject

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft_body = {"message": {"raw": encoded_message}}

        draft = service.users().drafts().create(userId="me", body=draft_body).execute()
        return {
            "draft_id": draft.get("id"),
            "to": to_email,
            "subject": subject,
            "status": "draft_created",
        }

    def send_email(self, to_email: str, subject: str, body_text: str) -> Dict[str, Any]:
        """Directly send an email (requires explicit user voice confirmation)."""
        service = self._get_service()
        message = EmailMessage()
        message.set_content(body_text)
        message["To"] = to_email
        message["Subject"] = subject

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": encoded_message}).execute()
        return {
            "message_id": sent.get("id"),
            "to": to_email,
            "subject": subject,
            "status": "sent",
        }

