#!/usr/bin/env python3
"""CLI utility to authenticate DeskOS with Google Workspace.

Runs local OAuth2 flow in default browser and writes offline token to data/token.json.
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workspace_auth import get_credentials, is_authenticated


def main():
    print("=" * 60)
    print("DeskOS v2 - Google Workspace Authentication Setup")
    print("=" * 60)
    print("This will open your default web browser to log in to your Google Account")
    print("and grant permission for DeskOS to access Calendar, Gmail, and Docs.\n")

    try:
        creds = get_credentials(interactive=True)
        if creds and creds.valid:
            print("\n[SUCCESS] Authentication completed successfully!")
            print("[SUCCESS] Refresh token stored in data/token.json")
            print("[SUCCESS] DeskOS is now connected to your Google Workspace.")
        else:
            print("\n[ERROR] Failed to obtain valid credentials.")
            sys.exit(1)
    except Exception as e:
        print(f"\n[EXCEPTION] Authentication failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

