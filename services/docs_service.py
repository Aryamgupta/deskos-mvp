"""DeskOS Google Docs & Drive Integration Service.

Provides automatic creation of Daily Standups / Summaries and voice note appending to Google Docs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
import zoneinfo

from googleapiclient.discovery import build

from workspace_auth import get_credentials


class GoogleDocsService:
    def __init__(self, timezone_str: str = "Asia/Kolkata"):
        self.timezone_str = timezone_str
        self._tz = zoneinfo.ZoneInfo(timezone_str)
        self._docs_service = None
        self._drive_service = None

    def _get_services(self):
        if self._docs_service is None or self._drive_service is None:
            creds = get_credentials(interactive=False)
            if not creds:
                raise RuntimeError("Google account is not authenticated. Please run scripts/auth_google.py.")
            self._docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
            self._drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._docs_service, self._drive_service

    def create_daily_summary_doc(self, title: Optional[str] = None, initial_content: Optional[str] = None) -> Dict[str, Any]:
        """Create a new Google Document for daily summary or meeting notes."""
        docs_service, _ = self._get_services()
        now_str = datetime.now(self._tz).strftime("%Y-%m-%d")
        doc_title = title or f"DeskOS Daily Summary - {now_str}"

        # 1. Create document
        doc = docs_service.documents().create(body={"title": doc_title}).execute()
        document_id = doc.get("documentId")

        # 2. Add header content
        content_to_insert = initial_content or (
            f"DeskOS Daily Summary\nDate: {now_str}\n"
            + "=" * 40
            + "\n\nGenerated automatically via DeskOS Voice Assistant.\n\n"
        )

        requests = [
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": content_to_insert,
                }
            }
        ]
        docs_service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()

        return {
            "documentId": document_id,
            "title": doc_title,
            "url": f"https://docs.google.com/document/d/{document_id}/edit",
        }

    def append_to_doc(self, document_id: str, text: str) -> bool:
        """Append text to the end of an existing Google Document."""
        docs_service, _ = self._get_services()
        doc = docs_service.documents().get(documentId=document_id).execute()
        
        # Determine the end index of the document
        content = doc.get("body", {}).get("content", [])
        end_index = 1
        if content:
            end_index = max(1, content[-1].get("endIndex", 1) - 1)

        timestamp = datetime.now(self._tz).strftime("%H:%M:%S")
        entry_text = f"\n[{timestamp}] {text}\n"

        requests = [
            {
                "insertText": {
                    "location": {"index": end_index},
                    "text": entry_text,
                }
            }
        ]
        docs_service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()
        return True

