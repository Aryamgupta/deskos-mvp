#!/usr/bin/env python3
"""DeskOS Workstation Telemetry Agent (Laptop Sidecar).

Runs on your Ubuntu laptop as a lightweight background daemon.
Gathers CPU load, RAM usage, NVMe activity, thermals, battery %, and runtimes,
then pushes live metrics to DeskOS Master (e.g. https://deskos.local or https://raspberrypi.local).
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import psutil

# Read target server from environment or argument (defaults to local mDNS)
MASTER_URL = os.environ.get("DESKOS_MASTER_URL", "https://deskos.local")
AGENT_SECRET = os.environ.get("DESKOS_AGENT_SECRET", "deskos-laptop-secret-key")
INTERVAL_SEC = float(os.environ.get("DESKOS_AGENT_INTERVAL", "3.0"))

_NET_PREV = psutil.net_io_counters()
_NET_TIME = time.monotonic()
_DISK_PREV = psutil.disk_io_counters()
_DISK_TIME = time.monotonic()


def select_cpu_temperature():
    """Extract CPU core temperatures."""
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return None
        # Look for coretemp, k10temp, acpitz
        for name in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if name in temps and temps[name]:
                entry = temps[name][0]
                return {"sensor": f"{name} ({entry.label or 'temp'})", "celsius": round(entry.current, 1)}
        for sensor_list in temps.values():
            if sensor_list:
                return {"sensor": sensor_list[0].label or "cpu", "celsius": round(sensor_list[0].current, 1)}
    except Exception:
        pass
    return None


def collect_laptop_metrics() -> dict:
    global _NET_PREV, _NET_TIME, _DISK_PREV, _DISK_TIME
    now = time.monotonic()

    # Network rate
    net = psutil.net_io_counters()
    elapsed = max(now - _NET_TIME, 0.1)
    down = max(0, net.bytes_recv - _NET_PREV.bytes_recv) / elapsed
    up = max(0, net.bytes_sent - _NET_PREV.bytes_sent) / elapsed
    _NET_PREV, _NET_TIME = net, now

    # Disk read / write
    disk_now = psutil.disk_io_counters()
    disk_elapsed = max(now - _DISK_TIME, 0.1)
    disk_activity = None
    if disk_now is not None and _DISK_PREV is not None:
        disk_activity = {
            "read_bytes_sec": round(max(0, disk_now.read_bytes - _DISK_PREV.read_bytes) / disk_elapsed),
            "write_bytes_sec": round(max(0, disk_now.write_bytes - _DISK_PREV.write_bytes) / disk_elapsed),
        }
    _DISK_PREV, _DISK_TIME = disk_now, now

    # Battery
    battery = None
    try:
        b = psutil.sensors_battery()
        if b is not None:
            battery = {
                "percent": round(b.percent),
                "plugged": b.power_plugged,
                "seconds_left": b.secsleft if b.secsleft >= 0 else None,
            }
    except Exception:
        pass

    # Active development runtimes
    processes = []
    try:
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = proc.info.get("cmdline") or []
                cmd = " ".join(cmdline).lower()
                if name in {"node", "nodejs", "bun", "docker", "code"} or "bun run" in cmd:
                    label = "Bun" if "bun" in name or "bun run" in cmd else "Node.js" if "node" in name else "Dev"
                    item = {"runtime": label, "pid": proc.pid, "command": (cmdline or [name])[0][:80]}
                    if item not in processes:
                        processes.append(item)
            except Exception:
                continue
    except Exception:
        pass

    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    cpu_temp = select_cpu_temperature()

    return {
        "hostname": socket.gethostname(),
        "timestamp": time.time(),
        "uptime_seconds": max(0, int(time.time() - psutil.boot_time())),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory": {"used": vm.used, "total": vm.total, "percent": vm.percent},
        "disk": {"used": disk.used, "total": disk.total, "free": disk.free, "percent": disk.percent, "activity": disk_activity},
        "battery": battery,
        "cpu_temperature": cpu_temp,
        "network": {"down_bytes_sec": round(down), "up_bytes_sec": round(up)},
        "runtimes": processes[:12],
        "is_workstation": True,
    }


def send_metrics(metrics: dict, target_url: str):
    endpoint = f"{target_url.rstrip('/')}/api/telemetry/report"
    payload = json.dumps(metrics).encode("utf-8")

    req = Request(endpoint, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-DeskOS-Agent-Secret", AGENT_SECRET)

    # Disable SSL verification for local self-signed mDNS certificate
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with urlopen(req, timeout=4.0, context=ctx) as resp:
        return resp.status == 200


def main():
    target = MASTER_URL
    for arg in sys.argv[1:]:
        if arg.startswith("http://") or arg.startswith("https://"):
            target = arg
    print(f"[DeskOS Agent] Starting workstation telemetry agent...")
    print(f"[DeskOS Agent] Workstation: {socket.gethostname()}")
    print(f"[DeskOS Agent] Target Master: {target}")
    print(f"[DeskOS Agent] Interval: {INTERVAL_SEC}s\n")

    consecutive_errors = 0
    while True:
        try:
            data = collect_laptop_metrics()
            send_metrics(data, target)
            if consecutive_errors > 0:
                print(f"[DeskOS Agent] Reconnected to master at {target}")
            consecutive_errors = 0
        except URLError as exc:
            consecutive_errors += 1
            if consecutive_errors == 1 or consecutive_errors % 20 == 0:
                print(f"[DeskOS Agent] Could not reach master at {target}: {exc.reason}")
        except Exception as exc:
            consecutive_errors += 1
            if consecutive_errors == 1 or consecutive_errors % 20 == 0:
                print(f"[DeskOS Agent] Unexpected error: {exc}")

        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()

