"""Minimal Gemini REST adapter for DeskOS with context and structured actions."""

from __future__ import annotations

from datetime import datetime
import json
import os
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

MODEL_DEFAULT = "gemini-flash-lite-latest"
MAX_RESPONSE_BYTES = 64 * 1024
MAX_COMMAND_CHARS = 1000

SYSTEM_INSTRUCTION = """You are DeskOS, an intelligent local workstation companion and smart desk assistant.
You help the user manage reminders, check system health, track developer tools, and answer general questions.

You will receive:
1. Current Datetime and Timezone of the workstation.
2. Monitored Workstation Health (CPU, RAM, Disk, Temperature, Uptime, Active Processes).
3. The Database Schema:
   Table `reminders`:
     - id: TEXT (UUID)
     - title: TEXT (1-160 chars)
     - due_at: TEXT (ISO-8601 string in UTC, e.g. "2026-10-24T15:00:00Z")
     - timezone: TEXT (e.g. "Asia/Kolkata", "UTC")
     - recurrence: TEXT ("none", "daily", "weekly")
     - status: TEXT ("active", "completed", "cancelled")
   Table `notifications`:
     - id: TEXT (UUID)
     - reminder_id: TEXT (FK to reminders)
     - occurrence_at: TEXT (ISO-8601)
     - title: TEXT
     - acknowledged_at: TEXT (nullable)
     - created_at: TEXT
   Table `tasks`:
     - id: TEXT (UUID)
     - title: TEXT (1-200 chars)
     - category: TEXT ("work", "dev", "personal", "general")
     - priority: TEXT ("low", "normal", "high")
     - due_date: TEXT (optional YYYY-MM-DD)
     - status: TEXT ("pending", "completed", "cancelled")
     - created_at: TEXT
     - completed_at: TEXT
4. List of existing active reminders and pending tasks.

Rules for your response:
You must reply with a valid JSON object matching this schema:
{
  "action": "create_reminder" | "cancel_reminder" | "list_reminders" | "create_task" | "list_tasks" | "complete_task" | "desk_analytics" | "system_status" | "reply",
  "parameters": {
     // for "create_reminder":
     //   "title": string, "due_at": string (ISO UTC), "recurrence": "none" | "daily" | "weekly", "timezone": string
     // for "cancel_reminder":
     //   "title": string or "reminder_id": string
     // for "create_task":
     //   "title": string, "priority": "low" | "normal" | "high", "category": string, "due_date": string (optional)
     // for "complete_task":
     //   "title": string or "task_id": string
     // for other actions: {}
  },
  "reply": string (A friendly, concise conversational message confirming the action or answering the user's question directly)
}

Important Instructions:
- Multilingual Support: Understand user commands in English, Hindi, Hinglish, and mixed regional languages (e.g. "Rishabh ko call karne ka reminder lagao shaam 5 baje", "Mujhe kal subah 9 baje stretch karne ke liye yaad dilana", "laptop kaisa chal raha hai"). Always map them accurately to the appropriate action and reply naturally in the language or Hinglish the user used!
- Always compute the absolute `due_at` timestamp in UTC based on the current workstation datetime and timezone provided.
- If the user asks general questions or asks about system metrics, choose action "system_status" or "reply" with a helpful, conversational explanation in "reply".
- Always output raw valid JSON only. No markdown formatting, backticks, or extra prose outside the JSON.
"""


class GeminiError(Exception):
    """Custom error for Gemini API calls."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GeminiAdapter:
    """Interacts with the Gemini REST API to interpret commands and query intentions."""

    def __init__(
        self,
        api_key: str,
        model: str = MODEL_DEFAULT,
        timeout: float = 30.0,
        opener: Callable[..., Any] = urlopen,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("Gemini API key is required")
        self._api_key = api_key.strip()
        self.model = model.strip() or MODEL_DEFAULT
        self.timeout = timeout
        self._opener = opener

    @classmethod
    def load_env(cls, env_path: str = ".env") -> dict[str, str]:
        """Simple .env reader without third-party dependencies."""
        loaded = {}
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        loaded[k.strip()] = v.strip().strip("\"'")
            except OSError:
                pass
        return loaded

    @classmethod
    def from_environment(cls) -> "GeminiAdapter | None":
        env_file = cls.load_env()
        api_key = os.environ.get("GEMINI_API_KEY") or env_file.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            return None
        model = os.environ.get("DESKOS_GEMINI_MODEL") or env_file.get("DESKOS_GEMINI_MODEL", MODEL_DEFAULT)
        return cls(api_key=api_key, model=model)

    def interpret(self, command: str, context: dict[str, Any]) -> dict[str, Any]:
        """Send command and context to Gemini and parse the structured intent."""
        if not isinstance(command, str) or not command.strip():
            raise GeminiError("Please enter a command.")
        if len(command) > MAX_COMMAND_CHARS:
            raise GeminiError(f"Command exceeds {MAX_COMMAND_CHARS} characters limit.")

        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(self.model, safe='')}:generateContent"
        )

        user_content = {
            "current_context": {
                "local_time": context.get("local_time", datetime.now().isoformat()),
                "timezone": context.get("timezone", "UTC"),
                "system_status": context.get("system_status", {}),
                "active_reminders": context.get("active_reminders", []),
            },
            "user_query": command.strip(),
        }

        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(user_content, ensure_ascii=False)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
                "maxOutputTokens": 800,
            },
        }

        request = Request(
            endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            method="POST",
        )

        start_t = time.time()
        print(f"\n[DeskOS-Gemini] >>> Prompt sent to Gemini ({self.model}, timeout={self.timeout}s): {command.strip()!r}")
        try:
            response = self._opener(request, timeout=self.timeout)
            with response:
                payload_bytes = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload_bytes) > MAX_RESPONSE_BYTES:
                    raise GeminiError("Gemini response was too large.")
            print(f"[DeskOS-Gemini] <<< Network response received in {time.time() - start_t:.2f}s")
        except HTTPError as exc:
            status_code = exc.code
            try:
                error_body = exc.read().decode("utf-8")
                error_json = json.loads(error_body)
                msg = error_json.get("error", {}).get("message", str(exc))
            except Exception:
                msg = str(exc)
            print(f"[DeskOS-Gemini] !!! HTTP Error ({status_code}): {msg}")
            if status_code == 429:
                raise GeminiError(f"Gemini API quota exceeded or rate limited: {msg}", 429) from None
            if status_code in {400, 401, 403}:
                raise GeminiError(f"Gemini API request failed ({status_code}): {msg}", status_code) from None
            raise GeminiError(f"Gemini service error ({status_code}): {msg}", status_code) from None
        except (TimeoutError, URLError, OSError) as exc:
            print(f"[DeskOS-Gemini] !!! Network/Connection Error: {exc}")
            raise GeminiError(f"Could not connect to Gemini API: {exc}") from None

        try:
            raw_response_text = payload_bytes.decode("utf-8")
            envelope = json.loads(raw_response_text)
            candidates = envelope.get("candidates") or []
            if not candidates:
                raise GeminiError("No response candidates returned by Gemini.")
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
            
            print(f"[DeskOS-Gemini] <<< Raw Gemini candidate text:\n{text}")

            # Clean possible markdown wrapping if returned despite json mime type
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            result = json.loads(text)
            print(f"[DeskOS-Gemini] <<< Parsed Structured JSON:\n{json.dumps(result, indent=2)}\n")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            print(f"[DeskOS-Gemini] !!! JSON Parse Error on text: {exc}")
            raise GeminiError("Failed to parse Gemini response as JSON.") from exc

        if not isinstance(result, dict) or "action" not in result or "reply" not in result:
            raise GeminiError("Gemini response missing required action or reply fields.")

        return result

