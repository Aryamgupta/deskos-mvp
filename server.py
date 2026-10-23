#!/usr/bin/env python3
"""DeskOS MVP: read-only local workstation dashboard for Ubuntu."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json, os, socket, time
from threading import Lock
import psutil

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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/health":
            self.send_json(200, {"ok": True, "service": "DeskOS"})
        elif self.path.split("?", 1)[0] == "/api/status":
            try:
                # Serialize collection to avoid overlapping sensor/process scans if two displays connect.
                with CACHE_LOCK:
                    self.send_json(200, collect_status())
            except Exception as exc:
                self.send_json(500, {"error": "Could not collect system status", "detail": str(exc)[:160]})
        else:
            super().do_GET()

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
    print(f"DeskOS is starting on http://{host}:{port}")
    print("Low-overhead mode: process scan every 20s; temperature sensors cached for 15s.")
    print("Read-only dashboard. Keep it on a trusted home network; do not port-forward this port.")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
