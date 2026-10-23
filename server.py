#!/usr/bin/env python3
"""DeskOS local workstation dashboard and reminder service for Ubuntu."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.parse import unquote, urlsplit
import json, os, socket, time
import psutil
import sqlite3

from assistant import AssistantRouter
from gemini_adapter import GeminiAdapter, GeminiError
from reminder_store import ReminderStore

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
STARTED = time.time()
CACHE_LOCK = Lock()
_PROCESS_CACHE = {"at": 0.0, "items": []}
_TEMP_CACHE = {"at": 0.0, "items": []}

# Prime psutil's CPU and network counters for meaningful subsequent readings.
psutil.cpu_percent(interval=None)
_NET_PREV = psutil.net_io_counters()
_NET_TIME = time.monotonic()
_DISK_PREV = psutil.disk_io_counters()
_DISK_TIME = time.monotonic()

# Default alert thresholds. Persisted overrides live in the settings table;
# environment variables (DESKOS_THRESHOLD_<METRIC>) take precedence over defaults
# but are overridden by persisted settings. Values are floats.
DEFAULT_THRESHOLDS = {
    "cpu_percent": 85.0,
    "memory_percent": 85.0,
    "temperature_celsius": 80.0,
    "disk_percent": 90.0,
}
# A metric is "critical" when it exceeds the threshold by this multiplier.
CRITICAL_MULTIPLIER = 1.2

_ENV_THRESHOLD_MAP = {
    "cpu_percent": "DESKOS_THRESHOLD_CPU_PERCENT",
    "memory_percent": "DESKOS_THRESHOLD_MEMORY_PERCENT",
    "temperature_celsius": "DESKOS_THRESHOLD_TEMPERATURE_CELSIUS",
    "disk_percent": "DESKOS_THRESHOLD_DISK_PERCENT",
}


def _parse_threshold_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def load_thresholds(store: ReminderStore) -> dict[str, float]:
    """Load alert thresholds: defaults, then env overrides, then persisted settings."""
    thresholds = dict(DEFAULT_THRESHOLDS)
    for metric, env_name in _ENV_THRESHOLD_MAP.items():
        thresholds[metric] = _parse_threshold_env(env_name, thresholds[metric])
    for metric in thresholds:
        try:
            stored = store.get_setting(f"threshold.{metric}")
            if stored is not None and stored.strip():
                thresholds[metric] = float(stored)
        except (ValueError, TypeError, sqlite3.Error):
            pass
    return thresholds


def evaluate_alerts(status: dict, thresholds: dict[str, float]) -> list[dict]:
    """Evaluate current system status against thresholds and return active alerts."""
    now = time.time()
    alerts: list[dict] = []

    def add(metric: str, value: float, threshold: float) -> None:
        severity = "critical" if value > threshold * CRITICAL_MULTIPLIER else "warning"
        unit = "%" if metric != "temperature_celsius" else "\u00b0C"
        alerts.append(
            {
                "metric": metric,
                "severity": severity,
                "value": round(value, 1),
                "threshold": threshold,
                "unit": unit,
                "message": f"{metric.replace('_', ' ').title()} high: {value}{unit} (threshold {threshold}{unit}).",
                "timestamp": now,
            }
        )

    cpu = status.get("cpu_percent")
    if isinstance(cpu, (int, float)) and cpu > thresholds["cpu_percent"]:
        add("cpu_percent", float(cpu), thresholds["cpu_percent"])

    memory = status.get("memory") or {}
    mem_percent = memory.get("percent") if isinstance(memory, dict) else None
    if isinstance(mem_percent, (int, float)) and mem_percent > thresholds["memory_percent"]:
        add("memory_percent", float(mem_percent), thresholds["memory_percent"])

    cpu_temp = status.get("cpu_temperature") or {}
    temp = cpu_temp.get("celsius") if isinstance(cpu_temp, dict) else None
    if isinstance(temp, (int, float)) and temp > thresholds["temperature_celsius"]:
        add("temperature_celsius", float(temp), thresholds["temperature_celsius"])

    disk = status.get("disk") or {}
    disk_percent = disk.get("percent") if isinstance(disk, dict) else None
    if isinstance(disk_percent, (int, float)) and disk_percent > thresholds["disk_percent"]:
        add("disk_percent", float(disk_percent), thresholds["disk_percent"])

    return alerts


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


def collect_status():
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


class Handler(SimpleHTTPRequestHandler):
    reminder_store = None
    gemini_adapter = None
    thresholds = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            self.send_json(200, {"ok": True, "service": "DeskOS"})
        elif path == "/api/status":
            try:
                # Serialize collection to avoid overlapping sensor/process scans if two displays connect.
                with CACHE_LOCK:
                    self.send_json(200, collect_status())
            except Exception as exc:
                self.send_json(500, {"error": "Could not collect system status", "detail": str(exc)[:160]})
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
        elif path == "/api/alerts":
            if not self.require_reminder_store():
                return
            try:
                with CACHE_LOCK:
                    status = collect_status()
                alerts = evaluate_alerts(status, Handler.thresholds)
                self.send_json(200, {"alerts": alerts, "thresholds": dict(Handler.thresholds)})
            except sqlite3.Error:
                self.log_error("Could not evaluate alerts")
                self.send_json(500, {"error": "Could not evaluate alerts"})
        elif path == "/api/settings":
            if not self.require_reminder_store():
                return
            self.send_json(200, {"thresholds": dict(Handler.thresholds)})
        elif path == "/api/assistant/provider":
            self.send_json(200, {
                "gemini_available": self.gemini_adapter is not None,
                "gemini_model": self.gemini_adapter.model if self.gemini_adapter is not None else None,
            })
        elif path.startswith("/api/"):
            self.route_reminder_item("GET", path)
        else:
            super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/assistant/gemini":
            self.handle_gemini_command()
        elif path == "/api/assistant/command":
            if not self.require_reminder_store():
                return
            try:
                payload = self.read_json()
                if set(payload) - {"command", "confirm"}:
                    raise ValueError("Only command and confirm fields are accepted")
                confirm = payload.get("confirm", False)
                if not isinstance(confirm, bool):
                    raise ValueError("confirm must be a boolean")
                router = AssistantRouter(self.reminder_store, collect_status)
                self.send_json(200, router.handle(payload.get("command"), confirm))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})
            except sqlite3.Error:
                self.log_error("Assistant command database error")
                self.send_json(500, {"error": "Could not complete the local command"})
            except Exception:
                self.log_error("Assistant command failed")
                self.send_json(500, {"error": "Could not complete the local command"})
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

    def handle_gemini_command(self):
        if not self.require_reminder_store():
            return
        if self.gemini_adapter is None:
            self.send_json(503, {"error": "Gemini is not configured on this DeskOS server. The local assistant remains available."})
            return
        try:
            payload = self.read_json()
            if set(payload) != {"command", "allow_cloud"} and set(payload) != {"command", "allow_cloud", "confirm"}:
                raise ValueError("Expected command, allow_cloud, and optional confirm fields only")
            if payload.get("allow_cloud") is not True:
                self.send_json(403, {"error": "Explicit cloud-send consent is required for every Gemini request."})
                return
            confirm = payload.get("confirm", False)
            if not isinstance(confirm, bool):
                raise ValueError("confirm must be a boolean")
            proposal = self.gemini_adapter.interpret(payload.get("command"))
            router = AssistantRouter(self.reminder_store, collect_status)
            result = router.execute_proposal(proposal, confirm=confirm)
            result["source"] = "gemini"
            result["model"] = self.gemini_adapter.model
            self.send_json(200, result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except GeminiError as exc:
            self.log_error("Gemini request failed")
            self.send_json(502, {"error": str(exc), "source": "gemini"})
        except sqlite3.Error:
            self.log_error("Gemini command database error")
            self.send_json(500, {"error": "Could not complete the local action"})
        except Exception:
            self.log_error("Gemini command failed")
            self.send_json(500, {"error": "Could not complete the cloud-assisted command"})

    def do_PATCH(self):
        self.route_reminder_item("PATCH", urlsplit(self.path).path)

    def do_DELETE(self):
        self.route_reminder_item("DELETE", urlsplit(self.path).path)

    def do_PUT(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/settings":
            if not self.require_reminder_store():
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self.send_json(400, {"error": "Invalid JSON body"})
                return
            thresholds = payload.get("thresholds")
            if not isinstance(thresholds, dict):
                self.send_json(400, {"error": "Body must contain a 'thresholds' object"})
                return
            valid_metrics = {"cpu_percent", "memory_percent", "temperature_celsius", "disk_percent"}
            updated = {}
            for metric, value in thresholds.items():
                if metric not in valid_metrics:
                    self.send_json(400, {"error": f"Unknown threshold metric '{metric}'"})
                    return
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    self.send_json(400, {"error": f"Threshold for '{metric}' must be a number"})
                    return
                if value <= 0:
                    self.send_json(400, {"error": f"Threshold for '{metric}' must be greater than zero"})
                    return
                Handler.thresholds[metric] = value
                try:
                    self.reminder_store.set_setting(f"threshold.{metric}", str(value))
                except (sqlite3.Error, ValueError) as exc:
                    self.log_error(f"Could not persist threshold '{metric}': {exc}")
                    self.send_json(500, {"error": f"Could not persist threshold '{metric}'"})
                    return
                updated[metric] = value
            self.send_json(200, {"ok": True, "thresholds": dict(Handler.thresholds), "updated": updated})
        else:
            self.send_json(404, {"error": "Endpoint not found"})

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

    def log_error(self, message):
        print(f"[DeskOS] {message}", flush=True)

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
    data_dir = Path(os.environ.get("DESKOS_DATA_DIR", str(Path.home() / ".local/share/deskos"))).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    Handler.reminder_store = ReminderStore(data_dir / "deskos.sqlite3")
    Handler.thresholds = load_thresholds(Handler.reminder_store)
    try:
        Handler.gemini_adapter = GeminiAdapter.from_environment()
    except ValueError:
        Handler.gemini_adapter = None
        print("[DeskOS] Gemini configuration is invalid; cloud assistant disabled.", flush=True)
    print(f"DeskOS is starting on http://{host}:{port}")
    print("Low-overhead mode: process scan every 20s; temperature sensors cached for 15s.")
    print(f"Reminder data directory: {data_dir}")
    print(f"Gemini assistant: {'enabled (' + Handler.gemini_adapter.model + ')' if Handler.gemini_adapter else 'disabled'}")
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
    try:
        server.serve_forever()
    finally:
        scheduler.stopping.set()
        scheduler.join(timeout=6)
        server.server_close()
