#!/usr/bin/env python3
"""DeskOS local workstation dashboard and reminder service for Ubuntu."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from queue import Queue, Empty
from threading import Event, Lock, Thread
from urllib.parse import unquote, urlsplit
from uuid import uuid4
import json, os, socket, time
import psutil
import sqlite3

from assistant import AssistantRouter
from device_auth import DeviceAuthManager
from gemini_adapter import GeminiAdapter
from reminder_store import ReminderStore

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
STARTED = time.time()
CACHE_LOCK = Lock()
_PROCESS_CACHE = {"at": 0.0, "items": []}
_TEMP_CACHE = {"at": 0.0, "items": []}
_GEMINI_ADAPTER = GeminiAdapter.from_environment()
_DEVICE_AUTH = DeviceAuthManager()
_REMOTE_LAPTOP_STATUS: dict = {}
_REMOTE_LAPTOP_LAST_SEEN: float = 0.0
_REMOTE_LAPTOP_LOCK = Lock()




class EventBroadcaster:
    """Thread-safe event broadcaster for Server-Sent Events (SSE)."""

    def __init__(self):
        self._lock = Lock()
        self._subscribers: set[Queue] = set()

    def subscribe(self) -> Queue:
        q: Queue = Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: Queue):
        with self._lock:
            self._subscribers.discard(q)

    def broadcast(self, event_type: str, data: dict):
        payload = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
        with self._lock:
            dead = set()
            for q in self._subscribers:
                try:
                    q.put_nowait(payload)
                except Exception:
                    dead.add(q)
            self._subscribers.difference_update(dead)


_BROADCASTER = EventBroadcaster()
_ASSISTANT_QUEUE: Queue = Queue()
_TASK_HISTORY: dict[str, dict] = {}
_TASK_HISTORY_LOCK = Lock()


class AssistantWorker(Thread):
    """Background worker processing queued natural language assistant tasks."""

    def __init__(self, reminder_store_fn):
        super().__init__(name="DeskOSAssistantWorker", daemon=True)
        self.reminder_store_fn = reminder_store_fn
        self.stopping = Event()

    def run(self):
        while not self.stopping.is_set():
            try:
                task = _ASSISTANT_QUEUE.get(timeout=1)
            except Empty:
                continue

            task_id = task["id"]
            command = task["command"]
            confirm = task.get("confirm", False)
            timezone_name = task.get("timezone")

            with _TASK_HISTORY_LOCK:
                if task_id in _TASK_HISTORY:
                    _TASK_HISTORY[task_id]["status"] = "processing"
                    _TASK_HISTORY[task_id]["started_at"] = time.time()

            _BROADCASTER.broadcast("task_status", {
                "task_id": task_id,
                "status": "processing",
                "command": command,
            })

            global _GEMINI_ADAPTER
            if _GEMINI_ADAPTER is None:
                _GEMINI_ADAPTER = GeminiAdapter.from_environment()

            store = self.reminder_store_fn()
            router = AssistantRouter(store, collect_status, gemini_adapter=_GEMINI_ADAPTER)

            try:
                result = router.handle(command, confirm=confirm, timezone_name=timezone_name)
                status = "needs_confirmation" if result.get("confirmation_required") else ("completed" if result.get("ok") else "failed")
            except Exception as exc:
                result = {"ok": False, "message": f"Processing error: {str(exc)[:120]}"}
                status = "failed"

            with _TASK_HISTORY_LOCK:
                if task_id in _TASK_HISTORY:
                    _TASK_HISTORY[task_id]["status"] = status
                    _TASK_HISTORY[task_id]["result"] = result
                    _TASK_HISTORY[task_id]["completed_at"] = time.time()

            _BROADCASTER.broadcast("task_completed", {
                "task_id": task_id,
                "status": status,
                "command": command,
                "result": result,
            })
            _ASSISTANT_QUEUE.task_done()


# Prime psutil's CPU and network counters for meaningful subsequent readings.
psutil.cpu_percent(interval=None)
_NET_PREV = psutil.net_io_counters()
_NET_TIME = time.monotonic()
_DISK_PREV = psutil.disk_io_counters()
_DISK_TIME = time.monotonic()


def safe_temperature():
    # Hardware sensor reads are cached; no repeated sensor enumeration per request.
    now = time.monotonic()
    if now - _TEMP_CACHE["at"] < 15:
        return _TEMP_CACHE["items"]
    try:
        sensors = psutil.sensors_temperatures(fahrenheit=False) or {}
        readings = []
        for name, entries in sensors.items():
            for entry in entries:
                if entry.current is not None:
                    readings.append({"sensor": entry.label or name, "celsius": round(entry.current, 1)})
        result = readings[:6]
    except (AttributeError, OSError):
        result = []
    _TEMP_CACHE["at"] = now
    _TEMP_CACHE["items"] = result
    return result


def select_cpu_temperature(readings):
    """Return a clearly CPU-labelled sensor reading, or None when ambiguous."""
    priorities = (
        ("cpu",),
        ("tctl", "tdie"),
        ("package id",),
    )
    for terms in priorities:
        for reading in readings:
            sensor = str(reading.get("sensor", "")).lower()
            if any(term in sensor for term in terms):
                return reading
    return None


def collect_local_host_status():
    global _NET_PREV, _NET_TIME, _DISK_PREV, _DISK_TIME
    now = time.monotonic()
    net = psutil.net_io_counters()
    elapsed = max(now - _NET_TIME, 0.1)
    down = max(0, net.bytes_recv - _NET_PREV.bytes_recv) / elapsed
    up = max(0, net.bytes_sent - _NET_PREV.bytes_sent) / elapsed
    _NET_PREV, _NET_TIME = net, now

    disk_now = psutil.disk_io_counters()
    disk_elapsed = max(now - _DISK_TIME, 0.1)
    disk_activity = None
    if disk_now is not None and _DISK_PREV is not None:
        disk_activity = {
            "read_bytes_sec": round(max(0, disk_now.read_bytes - _DISK_PREV.read_bytes) / disk_elapsed),
            "write_bytes_sec": round(max(0, disk_now.write_bytes - _DISK_PREV.write_bytes) / disk_elapsed),
            "read_count_sec": round(max(0, disk_now.read_count - _DISK_PREV.read_count) / disk_elapsed),
            "write_count_sec": round(max(0, disk_now.write_count - _DISK_PREV.write_count) / disk_elapsed),
        }
    _DISK_PREV, _DISK_TIME = disk_now, now

    try:
        disk = psutil.disk_usage(str(ROOT.anchor or "/"))
    except OSError:
        disk = psutil.disk_usage("/")
    battery = None
    try:
        b = psutil.sensors_battery()
        if b is not None:
            battery = {"percent": round(b.percent), "plugged": b.power_plugged, "seconds_left": b.secsleft if b.secsleft >= 0 else None}
    except (AttributeError, OSError):
        pass

    # Process enumeration is relatively more expensive than reading counters, so run it at most every 20s.
    if now - _PROCESS_CACHE["at"] >= 20:
        processes = []
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = proc.info.get("cmdline") or []
                cmd = " ".join(cmdline).lower()
                if name in {"node", "nodejs", "bun"} or "bun run" in cmd:
                    label = "Bun" if "bun" in name or "bun run" in cmd else "Node.js"
                    item = {"runtime": label, "pid": proc.pid, "command": (cmdline or [name])[0][:80]}
                    if item not in processes:
                        processes.append(item)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        _PROCESS_CACHE["at"] = now
        _PROCESS_CACHE["items"] = processes[:12]
    processes = _PROCESS_CACHE["items"]

    vm = psutil.virtual_memory()
    temps = safe_temperature()
    cpu_temperature = select_cpu_temperature(temps)
    return {
        "hostname": socket.gethostname(),
        "timestamp": time.time(),
        "uptime_seconds": max(0, int(time.time() - psutil.boot_time())),
        "service_uptime_seconds": int(time.time() - STARTED),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory": {"used": vm.used, "total": vm.total, "percent": vm.percent},
        "disk": {"used": disk.used, "total": disk.total, "free": disk.free, "percent": disk.percent, "activity": disk_activity},
        "battery": battery,
        "temperatures": temps,
        "cpu_temperature": cpu_temperature,
        "capabilities": {
            "battery": battery is not None,
            "temperature": bool(temps),
            "cpu_temperature": cpu_temperature is not None,
            "disk_activity": disk_activity is not None,
        },
        "network": {"down_bytes_sec": round(down), "up_bytes_sec": round(up)},
        "runtimes": processes[:12],
    }


def collect_status():
    """Return workstation telemetry if laptop agent is actively reporting, otherwise local host metrics."""
    with _REMOTE_LAPTOP_LOCK:
        now = time.time()
        if _REMOTE_LAPTOP_STATUS and (now - _REMOTE_LAPTOP_LAST_SEEN < 20.0):
            data = dict(_REMOTE_LAPTOP_STATUS)
            data["laptop_online"] = True
            data["seconds_since_heartbeat"] = round(now - _REMOTE_LAPTOP_LAST_SEEN, 1)
            return data

    with CACHE_LOCK:
        data = collect_local_host_status()
        data["laptop_online"] = False
        return data


class Handler(SimpleHTTPRequestHandler):
    reminder_store = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def get_client_ip(self) -> str:
        """Extract remote client IP address."""
        forwarded = self.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "127.0.0.1"

    def get_auth_token_from_request(self) -> str | None:
        """Extract auth token from Cookie or Authorization header."""
        # Check Authorization: Bearer <token>
        auth_hdr = self.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            return auth_hdr[7:].strip()
        # Check Cookie: deskos_token=<token>
        cookie_hdr = self.headers.get("Cookie", "")
        for item in cookie_hdr.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                if k == "deskos_token":
                    return v.strip()
        return None

    def is_authenticated(self) -> bool:
        """Verify client authentication: localhost passes automatically; remote devices require token."""
        client_ip = self.get_client_ip()
        if _DEVICE_AUTH.is_client_local(client_ip):
            return True
        token = self.get_auth_token_from_request()
        return _DEVICE_AUTH.is_token_valid(token)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        client_ip = self.get_client_ip()

        # Public endpoints that bypass authentication check
        if path == "/health":
            self.send_json(200, {"ok": True, "service": "DeskOS"})
            return
        elif path == "/api/auth/status":
            is_local = _DEVICE_AUTH.is_client_local(client_ip)
            authed = self.is_authenticated()
            self.send_json(200, {
                "authenticated": authed,
                "is_local": is_local,
                "client_ip": client_ip,
            })
            return
        elif path == "/api/auth/pin":
            # Only allow host machine on localhost to query or re-display current PIN
            if not _DEVICE_AUTH.is_client_local(client_ip):
                self.send_json(403, {"error": "PIN inspection is only permitted on the local workstation host"})
                return
            self.send_json(200, {"pin": _DEVICE_AUTH.get_current_pin()})
            return

        # Enforce authentication for protected resources
        if not self.is_authenticated():
            if path.startswith("/api/"):
                self.send_json(401, {"error": "Device authentication required. Pair using PIN at /api/auth/pair"})
                return
            # Serve index.html so the browser can display the pairing PIN lock screen
            self.path = "/index.html"
            super().do_GET()
            return

        elif path == "/api/events":
            # Server-Sent Events stream
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            q = _BROADCASTER.subscribe()
            try:
                # Send initial ping event so client knows stream is established
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=20)
                        self.wfile.write(msg)
                        self.wfile.flush()
                    except Empty:
                        # Heartbeat comment to keep connection alive
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                _BROADCASTER.unsubscribe(q)
        elif path == "/api/status":
            try:
                status_data = collect_status()
                self.send_json(200, status_data)
            except Exception as exc:
                self.send_json(500, {"error": "Could not collect system status", "detail": str(exc)[:160]})

        elif path == "/api/tasks":
            if not self.require_reminder_store():
                return
            include_completed = urlsplit(self.path).query == "all=1"
            try:
                self.send_json(200, {"tasks": self.reminder_store.list_tasks(include_completed)})
            except sqlite3.Error:
                self.log_error("Could not list tasks")
                self.send_json(500, {"error": "Could not load tasks"})
        elif path == "/api/workspace/status":
            from workspace_auth import is_authenticated
            self.send_json(200, {"connected": is_authenticated()})
        elif path == "/api/calendar/events":
            from workspace_auth import is_authenticated
            if not is_authenticated():
                self.send_json(200, {"events": [], "connected": False})
                return
            try:
                from services.calendar_service import GoogleCalendarService
                cal = GoogleCalendarService()
                days = 7 if urlsplit(self.path).query == "upcoming=1" else 1
                events = cal.get_upcoming_events(days=days) if days > 1 else cal.get_today_events()
                self.send_json(200, {"events": events, "connected": True})
            except Exception as exc:
                self.send_json(500, {"error": str(exc), "connected": False})
        elif path == "/api/gmail/unread":
            from workspace_auth import is_authenticated
            if not is_authenticated():
                self.send_json(200, {"emails": [], "connected": False})
                return
            try:
                from services.gmail_service import GmailService
                gmail = GmailService()
                self.send_json(200, {"emails": gmail.get_unread_emails(max_results=8), "connected": True})
            except Exception as exc:
                self.send_json(500, {"error": str(exc), "connected": False})
        elif path == "/api/docs":
            if not self.require_reminder_store():
                return
            try:
                self.send_json(200, {"docs": self.reminder_store.list_docs()})
            except sqlite3.Error:
                self.send_json(500, {"error": "Could not load documents"})
        elif path == "/api/analytics":
            if not self.require_reminder_store():
                return
            try:
                self.send_json(200, self.reminder_store.get_desk_analytics())
            except sqlite3.Error:
                self.log_error("Could not get analytics")
                self.send_json(500, {"error": "Could not load analytics"})
        elif path == "/api/reminders":
            if not self.require_reminder_store():
                return
            include_inactive = urlsplit(self.path).query == "all=1"
            try:
                self.send_json(200, {"reminders": self.reminder_store.list_reminders(include_inactive)})
            except sqlite3.Error:
                self.log_error("Could not list reminders")
                self.send_json(500, {"error": "Could not load reminders"})
        elif path == "/api/notifications":
            if not self.require_reminder_store():
                return
            try:
                self.send_json(200, {"notifications": self.reminder_store.list_pending_notifications()})
            except sqlite3.Error:
                self.log_error("Could not list pending notifications")
                self.send_json(500, {"error": "Could not load notifications"})
        elif path.startswith("/api/"):
            self.route_reminder_item("GET", path)
        elif path in {"/", "/cockpit", "/tasks", "/reminders", "/google", "/voice", "/analytics", "/ambient"}:
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path

        # Unauthenticated pairing endpoint
        if path == "/api/auth/pair":
            try:
                payload = self.read_json()
                pin = str(payload.get("pin", "")).strip()
                device_name = str(payload.get("name", "Mobile Device")).strip()
                user_agent = self.headers.get("User-Agent", "")

                token = _DEVICE_AUTH.verify_pin_and_pair(pin, device_name=device_name, user_agent=user_agent)
                if token:
                    # Set persistent HttpOnly auth cookie for 365 days
                    cookie_val = f"deskos_token={token}; Path=/; Max-Age=31536000; SameSite=Lax"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Set-Cookie", cookie_val)
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "ok": True,
                        "token": token,
                        "message": "Device authenticated successfully"
                    }).encode("utf-8"))
                else:
                    self.send_json(401, {"ok": False, "error": "Invalid pairing PIN. Check the terminal on the host workstation."})
            except Exception as exc:
                self.send_json(400, {"ok": False, "error": str(exc)})
            return

        # Workstation Telemetry Agent Ingestion Endpoint
        if path == "/api/telemetry/report":
            secret = self.headers.get("X-DeskOS-Agent-Secret", "")
            expected = os.environ.get("DESKOS_AGENT_SECRET", "deskos-laptop-secret-key")
            if secret != expected:
                self.send_json(403, {"error": "Invalid agent secret"})
                return
            try:
                data = self.read_json()
                global _REMOTE_LAPTOP_STATUS, _REMOTE_LAPTOP_LAST_SEEN
                with _REMOTE_LAPTOP_LOCK:
                    _REMOTE_LAPTOP_STATUS = data
                    _REMOTE_LAPTOP_LAST_SEEN = time.time()

                # Immediately push real-time status update to all connected SSE clients
                telemetry_payload = dict(data)
                telemetry_payload["laptop_online"] = True
                telemetry_payload["seconds_since_heartbeat"] = 0.0
                _BROADCASTER.broadcast("status", telemetry_payload)

                self.send_json(200, {"ok": True, "message": "Telemetry received"})
            except Exception as exc:
                self.send_json(400, {"error": str(exc)})
            return

        # Enforce authentication for all other POST endpoints
        if not self.is_authenticated():
            self.send_json(401, {"error": "Device authentication required"})
            return

        if path == "/api/assistant/command":
            if not self.require_reminder_store():
                return
            try:
                payload = self.read_json()
                if set(payload) - {"command", "confirm", "timezone"}:
                    raise ValueError("Only command, confirm, and timezone fields are accepted")
                confirm = payload.get("confirm", False)
                if not isinstance(confirm, bool):
                    raise ValueError("confirm must be a boolean")
                timezone_name = payload.get("timezone")
                # Reload adapter if environment changed
                global _GEMINI_ADAPTER
                if _GEMINI_ADAPTER is None:
                    _GEMINI_ADAPTER = GeminiAdapter.from_environment()
                router = AssistantRouter(self.reminder_store, collect_status, gemini_adapter=_GEMINI_ADAPTER)
                self.send_json(200, router.handle(payload.get("command"), confirm, timezone_name=timezone_name))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})
            except sqlite3.Error:
                self.log_error("Assistant command database error")
                self.send_json(500, {"error": "Could not complete the local command"})
            except Exception:
                self.log_error("Assistant command failed")
                self.send_json(500, {"error": "Could not complete the local command"})
        elif path == "/api/assistant/enqueue":
            if not self.require_reminder_store():
                return
            try:
                payload = self.read_json()
                if set(payload) - {"command", "confirm", "timezone"}:
                    raise ValueError("Only command, confirm, and timezone fields are accepted")
                command = payload.get("command")
                if not isinstance(command, str) or not command.strip():
                    raise ValueError("command must be a non-empty string")
                confirm = payload.get("confirm", False)
                if not isinstance(confirm, bool):
                    raise ValueError("confirm must be a boolean")
                timezone_name = payload.get("timezone")

                task_id = str(uuid4())
                task_data = {
                    "id": task_id,
                    "command": command.strip(),
                    "confirm": confirm,
                    "timezone": timezone_name,
                    "status": "queued",
                    "queued_at": time.time(),
                }
                with _TASK_HISTORY_LOCK:
                    _TASK_HISTORY[task_id] = task_data
                _ASSISTANT_QUEUE.put(task_data)

                # Broadcast queue update event
                _BROADCASTER.broadcast("task_queued", {
                    "task_id": task_id,
                    "command": command.strip(),
                    "queue_size": _ASSISTANT_QUEUE.qsize(),
                })

                # Return 202 Accepted immediately
                self.send_json(202, {
                    "ok": True,
                    "task_id": task_id,
                    "status": "queued",
                    "message": f"Command enqueued for processing: '{command.strip()}'",
                })
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})
        elif path == "/api/tasks":
            if not self.require_reminder_store():
                return
            include_completed = urlsplit(self.path).query == "all=1"
            try:
                self.send_json(200, {"tasks": self.reminder_store.list_tasks(include_completed)})
            except sqlite3.Error:
                self.log_error("Could not list tasks")
                self.send_json(500, {"error": "Could not load tasks"})
        elif path == "/api/workspace/status":
            from workspace_auth import is_authenticated
            self.send_json(200, {"connected": is_authenticated()})
        elif path == "/api/calendar/events":
            from workspace_auth import is_authenticated
            if not is_authenticated():
                self.send_json(200, {"events": [], "connected": False})
                return
            try:
                from services.calendar_service import GoogleCalendarService
                cal = GoogleCalendarService()
                days = 7 if urlsplit(self.path).query == "upcoming=1" else 1
                events = cal.get_upcoming_events(days=days) if days > 1 else cal.get_today_events()
                self.send_json(200, {"events": events, "connected": True})
            except Exception as exc:
                self.send_json(500, {"error": str(exc), "connected": False})
        elif path == "/api/gmail/unread":
            from workspace_auth import is_authenticated
            if not is_authenticated():
                self.send_json(200, {"emails": [], "connected": False})
                return
            try:
                from services.gmail_service import GmailService
                gmail = GmailService()
                self.send_json(200, {"emails": gmail.get_unread_emails(max_results=8), "connected": True})
            except Exception as exc:
                self.send_json(500, {"error": str(exc), "connected": False})
        elif path == "/api/docs":
            if not self.require_reminder_store():
                return
            try:
                self.send_json(200, {"docs": self.reminder_store.list_docs()})
            except sqlite3.Error:
                self.send_json(500, {"error": "Could not load documents"})
        elif path == "/api/analytics":
            if not self.require_reminder_store():
                return
            try:
                self.send_json(200, self.reminder_store.get_desk_analytics())
            except sqlite3.Error:
                self.log_error("Could not get analytics")
                self.send_json(500, {"error": "Could not load analytics"})
        elif path == "/api/reminders":
            if not self.require_reminder_store():
                return
            try:
                payload = self.read_json()
                reminder = self.reminder_store.create(
                    payload.get("title"),
                    payload.get("due_at"),
                    payload.get("recurrence", "none"),
                    payload.get("timezone"),
                )
                self.send_json(201, {"reminder": reminder})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})
            except sqlite3.Error:
                self.log_error("Could not create reminder")
                self.send_json(500, {"error": "Could not save reminder"})
        elif path.startswith("/api/"):
            self.route_reminder_item("POST", path)
        else:
            self.send_json(404, {"error": "Endpoint not found"})

    def do_PATCH(self):
        if not self.is_authenticated():
            self.send_json(401, {"error": "Device authentication required"})
            return
        self.route_reminder_item("PATCH", urlsplit(self.path).path)

    def do_DELETE(self):
        if not self.is_authenticated():
            self.send_json(401, {"error": "Device authentication required"})
            return
        path = urlsplit(self.path).path
        if path.startswith("/api/calendar/events/"):
            event_id = path[len("/api/calendar/events/"):]
            from workspace_auth import is_authenticated
            if not is_authenticated():
                self.send_json(401, {"error": "Google Workspace is not connected"})
                return
            try:
                from services.calendar_service import GoogleCalendarService
                cal = GoogleCalendarService()
                cal.delete_event(event_id)
                self.send_json(200, {"ok": True, "message": "Event deleted successfully", "event_id": event_id})
            except Exception as exc:
                self.send_json(500, {"error": str(exc)})
            return
        self.route_reminder_item("DELETE", path)

    def require_reminder_store(self):
        if self.reminder_store is None:
            self.send_json(503, {"error": "Reminder storage is not initialized"})
            return False
        return True

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length < 1 or length > 8192:
            raise ValueError("Request body must be between 1 and 8192 bytes")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON request body must be an object")
        return payload

    def route_reminder_item(self, method, path):
        if not self.require_reminder_store():
            return
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "reminders":
            reminder_id = parts[2]
            try:
                if method == "PATCH":
                    reminder = self.reminder_store.update(reminder_id, self.read_json())
                    if reminder is None:
                        self.send_json(404, {"error": "Reminder not found"})
                    else:
                        self.send_json(200, {"reminder": reminder})
                    return
                if method == "DELETE":
                    if self.reminder_store.cancel(reminder_id):
                        self.send_json(200, {"cancelled": True})
                    else:
                        self.send_json(404, {"error": "Reminder not found"})
                    return
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})
                return
            except sqlite3.Error:
                self.log_error("Could not update reminder")
                self.send_json(500, {"error": "Could not update reminder"})
                return
        if len(parts) == 4 and parts[:2] == ["api", "reminders"] and parts[3] == "complete" and method == "POST":
            try:
                if self.reminder_store.complete(parts[2]):
                    self.send_json(200, {"completed": True})
                else:
                    self.send_json(404, {"error": "Reminder not found"})
            except sqlite3.Error:
                self.log_error("Could not complete reminder")
                self.send_json(500, {"error": "Could not complete reminder"})
            return
        if len(parts) == 4 and parts[:2] == ["api", "notifications"] and parts[3] == "ack" and method == "POST":
            try:
                if self.reminder_store.acknowledge(parts[2]):
                    self.send_json(200, {"acknowledged": True})
                else:
                    self.send_json(404, {"error": "Notification not found"})
            except sqlite3.Error:
                self.log_error("Could not acknowledge notification")
                self.send_json(500, {"error": "Could not acknowledge notification"})
            return
        self.send_json(404, {"error": "Endpoint not found"})

    def log_error(self, fmt, *args):
        if args:
            try:
                print(f"[DeskOS] {fmt % args}", flush=True)
            except Exception:
                print(f"[DeskOS] {fmt} {args}", flush=True)
        else:
            print(f"[DeskOS] {fmt}", flush=True)

    def do_HEAD(self):
        if self.path.split("?", 1)[0] == "/health":
            body = json.dumps({"ok": True, "service": "DeskOS"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
        else:
            super().do_HEAD()

    def send_json(self, code, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("[DeskOS] " + (fmt % args))


if __name__ == "__main__":
    host = os.environ.get("DESKOS_HOST", "0.0.0.0")
    port = int(os.environ.get("DESKOS_PORT", "8765"))
    default_data_dir = ROOT / "data"
    data_dir_env = os.environ.get("DESKOS_DATA_DIR")
    if data_dir_env:
        data_dir = Path(data_dir_env).expanduser()
    else:
        # Prefer workspace local data directory during laptop development
        data_dir = default_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    Handler.reminder_store = ReminderStore(data_dir / "deskos.sqlite3")
    print(f"DeskOS is starting on http://{host}:{port}")
    print("Low-overhead mode: process scan every 20s; temperature sensors cached for 15s.")
    print(f"Reminder data directory: {data_dir}")
    print("Keep DeskOS on a trusted home network; do not port-forward this port.")
    server = ThreadingHTTPServer((host, port), Handler)

    class Scheduler(Thread):
        def __init__(self, store):
            super().__init__(name="DeskOSReminderScheduler", daemon=True)
            self.store = store
            self.stopping = Event()

        def run(self):
            while not self.stopping.wait(5):
                try:
                    self.store.dispatch_due()
                except sqlite3.Error as exc:
                    print(f"[DeskOS] Reminder scheduler database error: {exc}", flush=True)

    scheduler = Scheduler(Handler.reminder_store)
    scheduler.start()

    assistant_worker = AssistantWorker(lambda: Handler.reminder_store)
    assistant_worker.start()

    class TelemetryBroadcaster(Thread):
        """Streams system telemetry over SSE periodically to eliminate client HTTP polling."""

        def __init__(self):
            super().__init__(name="DeskOSTelemetryBroadcaster", daemon=True)
            self.stopping = Event()

        def run(self):
            while not self.stopping.wait(3):
                if _BROADCASTER._subscribers:
                    try:
                        status_data = collect_status()
                        _BROADCASTER.broadcast("status", status_data)
                    except Exception as exc:
                        print(f"[DeskOS] Telemetry broadcast error: {exc}", flush=True)

    telemetry_thread = TelemetryBroadcaster()
    telemetry_thread.start()
    try:
        server.serve_forever()
    finally:
        scheduler.stopping.set()
        assistant_worker.stopping.set()
        telemetry_thread.stopping.set()
        scheduler.join(timeout=3)
        assistant_worker.join(timeout=3)
        telemetry_thread.join(timeout=3)
        server.server_close()
