"""DeskOS Device Authentication & Pairing Manager.

Enforces zero-trust local network access control:
- Localhost (127.0.0.1 / ::1) is automatically trusted.
- Remote network devices (mobile phones, tablets, other laptops) must pair once using a PIN.
- On successful pairing, devices receive a persistent cryptographic session token.
- Host machine terminal prints the current 6-digit pairing PIN on boot or when requested.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import time
from typing import Any, Dict, Optional

AUTH_FILE = Path(__file__).resolve().parent / "data" / "authorized_devices.json"


class DeviceAuthManager:
    def __init__(self, auth_file: Path = AUTH_FILE):
        self.auth_file = auth_file
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._current_pin: str = ""
        self._pin_created_at: float = 0
        self._load()
        self.generate_pin()

    def _load(self):
        if self.auth_file.exists():
            try:
                with open(self.auth_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._devices = data.get("devices", {})
            except Exception as e:
                print(f"[DeviceAuth] Warning loading {self.auth_file}: {e}")
                self._devices = {}
        else:
            self._save()

    def _save(self):
        try:
            with open(self.auth_file, "w", encoding="utf-8") as f:
                json.dump({"devices": self._devices}, f, indent=2)
        except Exception as e:
            print(f"[DeviceAuth] Failed to save {self.auth_file}: {e}")

    def generate_pin(self) -> str:
        """Generate or load custom pairing PIN."""
        # Check if user defined a fixed PIN in .env or environment
        custom_pin = os.environ.get("DESKOS_DEVICE_PIN", "").strip()
        if not custom_pin:
            for env_candidate in [Path(".env"), Path("/app/.env"), Path(self.data_dir).parent / ".env"]:
                if env_candidate.exists():
                    try:
                        with open(env_candidate, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if line.startswith("DESKOS_DEVICE_PIN="):
                                    custom_pin = line.split("=", 1)[1].strip().strip('"').strip("'")
                                    break
                        if custom_pin:
                            break
                    except Exception:
                        pass

        if custom_pin and len(custom_pin) == 6 and custom_pin.isdigit():
            self._current_pin = custom_pin
        else:
            # Cryptographically secure random 6-digit PIN
            self._current_pin = f"{secrets.randbelow(900000) + 100000}"

        self._pin_created_at = time.time()
        print("\n" + "=" * 60)
        print(f"🔒 DeskOS DEVICE PAIRING PIN:  {self._current_pin}")
        print("   Enter this PIN on your phone/tablet to authenticate the device.")
        print("=" * 60 + "\n")
        return self._current_pin

    def get_current_pin(self) -> str:
        return self._current_pin

    def is_client_local(self, client_ip: str) -> bool:
        """Check if request originates from workstation host itself."""
        return client_ip in {"127.0.0.1", "::1", "localhost"}

    def is_token_valid(self, token: Optional[str]) -> bool:
        if not token:
            return False
        device = self._devices.get(token)
        if device:
            # Update last_seen timestamp
            device["last_seen"] = time.time()
            return True
        return False

    def verify_pin_and_pair(self, pin: str, device_name: str = "Mobile Device", user_agent: str = "") -> Optional[str]:
        """Validate pairing PIN and issue persistent device auth token."""
        if not pin or pin.strip() != self._current_pin:
            return None

        # Generate persistent token for this paired device
        token = secrets.token_hex(32)
        self._devices[token] = {
            "name": device_name.strip() or "Trusted Device",
            "user_agent": user_agent[:120],
            "created_at": time.time(),
            "last_seen": time.time(),
        }
        self._save()
        # Rotate PIN after successful pairing for defense-in-depth
        self.generate_pin()
        return token

    def list_authorized_devices(self) -> list[dict[str, Any]]:
        return [
            {
                "token_prefix": token[:8] + "...",
                "name": info.get("name", "Unknown"),
                "user_agent": info.get("user_agent", ""),
                "created_at": info.get("created_at"),
                "last_seen": info.get("last_seen"),
            }
            for token, info in self._devices.items()
        ]

    def revoke_device(self, token_prefix: str) -> bool:
        for token in list(self._devices.keys()):
            if token.startswith(token_prefix):
                del self._devices[token]
                self._save()
                return True
        return False

