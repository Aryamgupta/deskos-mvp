"""DeskOS Google Workspace OAuth2 Manager.

Manages offline user credentials and token lifecycle for Google Calendar, Gmail, and Google Docs APIs.
Ensures tokens are refreshed automatically and kept securely in data/token.json.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Full productivity scopes requested for DeskOS v2
SCOPES = [
    # Google Calendar
    "https://www.googleapis.com/auth/calendar.events",
    # Gmail
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    # Google Docs & Drive file access
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CREDENTIALS_FILE = BASE_DIR / "credentials.json"
DEFAULT_TOKEN_FILE = BASE_DIR / "data" / "token.json"


def get_credentials(
    credentials_file: Optional[Path] = None,
    token_file: Optional[Path] = None,
    interactive: bool = False,
) -> Optional[Credentials]:
    """Retrieve valid user credentials from token.json or prompt for authentication.

    Args:
        credentials_file: Path to OAuth2 client credentials.json.
        token_file: Path to token cache file.
        interactive: If True, opens local browser to perform OAuth authorization if token missing/expired.

    Returns:
        google.oauth2.credentials.Credentials or None if not authenticated.
    """
    cred_path = credentials_file or DEFAULT_CREDENTIALS_FILE
    tok_path = token_file or DEFAULT_TOKEN_FILE

    creds: Optional[Credentials] = None

    if tok_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(tok_path), SCOPES)
        except Exception as e:
            print(f"[WorkspaceAuth] Error reading token file {tok_path}: {e}")
            creds = None

    # Check validity or refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            tok_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tok_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        except Exception as e:
            print(f"[WorkspaceAuth] Failed to refresh token: {e}")
            creds = None

    if not creds or not creds.valid:
        if interactive:
            if not cred_path.exists():
                raise FileNotFoundError(
                    f"OAuth client configuration '{cred_path}' not found! "
                    "Please download credentials.json from Google Cloud Console."
                )

            flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
            # Run local server on an available port
            creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

            tok_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tok_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            print(f"[WorkspaceAuth] Credentials saved to {tok_path}")
        else:
            return None

    return creds


def is_authenticated(token_file: Optional[Path] = None) -> bool:
    """Check if DeskOS currently has valid Google Workspace credentials."""
    creds = get_credentials(token_file=token_file, interactive=False)
    return bool(creds and creds.valid)

