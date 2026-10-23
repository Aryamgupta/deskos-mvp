import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
from reminder_store import ReminderStore, parse_datetime


class FakeGeminiAdapter:
    model = "fake-gemini-model"

    def __init__(self, proposal):
        self.proposal = proposal
        self.commands = []

    def interpret(self, command):
        self.commands.append(command)
        return self.proposal


class CpuTemperatureSelectionTests(unittest.TestCase):
    def test_prefers_cpu_label_over_earlier_non_cpu_sensor(self):
        readings = [
            {"sensor": "Composite", "celsius": 42.0},
            {"sensor": "CPU", "celsius": 79.0},
            {"sensor": "Tctl", "celsius": 81.0},
        ]

        self.assertEqual(server.select_cpu_temperature(readings), readings[1])

    def test_accepts_common_cpu_sensor_labels(self):
        for label in ("Tctl", "Tdie", "Package id 0"):
            with self.subTest(label=label):
                reading = {"sensor": label, "celsius": 70.0}
                self.assertEqual(server.select_cpu_temperature([reading]), reading)

    def test_returns_none_when_no_sensor_is_identifiably_cpu(self):
        self.assertIsNone(
            server.select_cpu_temperature(
                [{"sensor": "Composite", "celsius": 40.0}, {"sensor": "Ambient", "celsius": 30.0}]
            )
        )


class HttpEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        server.Handler.reminder_store = None

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_path = f"{self.temp_dir.name}/deskos.sqlite3"
        server.Handler.reminder_store = ReminderStore(self.store_path)
        server.Handler.gemini_adapter = None

    def tearDown(self):
        server.Handler.gemini_adapter = None
        self.temp_dir.cleanup()

    def request_json(self, path, method="GET", payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_health_get_returns_service_status(self):
        with urlopen(f"{self.base_url}/health") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), {"ok": True, "service": "DeskOS"})

    def test_health_head_returns_success_without_body(self):
        request = Request(f"{self.base_url}/health", method="HEAD")
        with urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertGreater(int(response.headers["Content-Length"]), 0)
            self.assertEqual(response.read(), b"")

    def test_status_includes_monitoring_and_temperature_capabilities(self):
        with urlopen(f"{self.base_url}/api/status") as response:
            self.assertEqual(response.status, 200)
            payload = json.load(response)

        for key in ("hostname", "timestamp", "cpu_percent", "memory", "disk", "network", "temperatures", "cpu_temperature", "capabilities"):
            with self.subTest(key=key):
                self.assertIn(key, payload)
        self.assertEqual(
            payload["capabilities"]["cpu_temperature"],
            payload["cpu_temperature"] is not None,
        )

    def test_reminder_crud_and_invalid_input(self):
        due_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        status, _result = self.request_json(
            "/api/reminders", "POST", {"title": "Take a break", "due_at": due_at}
        )
        self.assertEqual(status, 201)
        reminder = _result["reminder"]
        reminder_id = reminder["id"]

        status, _result = self.request_json(
            f"/api/reminders/{reminder_id}", "PATCH", {"title": "Take a short break"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(_result["reminder"]["title"], "Take a short break")

        status, result = self.request_json("/api/reminders")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in result["reminders"]], [reminder_id])

        status, result = self.request_json(f"/api/reminders/{reminder_id}", "DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(result["cancelled"])

        status, result = self.request_json("/api/reminders")
        self.assertEqual(result["reminders"], [])
        status, result = self.request_json("/api/reminders?all=1")
        self.assertEqual(result["reminders"][0]["status"], "cancelled")

        _status, result = self.request_json(
            "/api/reminders", "POST", {"title": "Missing timezone", "due_at": "2030-01-01T12:00:00"}
        )
        self.assertEqual(_status, 400)

    def test_due_notification_is_persistent_idempotent_and_acknowledgeable(self):
        due = datetime.now(timezone.utc) + timedelta(minutes=5)
        reminder = server.Handler.reminder_store.create("Read a book", due.isoformat())
        simulated_now = due + timedelta(seconds=2)

        self.assertEqual(server.Handler.reminder_store.dispatch_due(simulated_now), 1)
        self.assertEqual(server.Handler.reminder_store.dispatch_due(simulated_now), 0)

        reopened = ReminderStore(self.store_path)
        status, result = self.request_json("/api/notifications")
        self.assertEqual(status, 200)
        pending = result["notifications"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["reminder_id"], reminder["id"])
        self.assertEqual(reopened.list_reminders(), [])

        status, result = self.request_json(f"/api/notifications/{pending[0]['id']}/ack", "POST")
        self.assertEqual(status, 200)
        self.assertTrue(result["acknowledged"])
        self.assertTrue(reopened.acknowledge(pending[0]["id"]))
        self.assertEqual(reopened.list_pending_notifications(), [])

    def test_daily_recurring_reminder_catches_up_once_and_advances(self):
        due = datetime.now(timezone.utc) + timedelta(minutes=1)
        reminder = server.Handler.reminder_store.create(
            "Stretch", due.isoformat(), "daily", "UTC"
        )
        simulated_now = due + timedelta(days=3)

        self.assertEqual(server.Handler.reminder_store.dispatch_due(simulated_now), 1)
        active = server.Handler.reminder_store.list_reminders()
        self.assertEqual(len(active), 1)
        self.assertGreater(parse_datetime(active[0]["due_at"]), simulated_now)
        self.assertEqual(active[0]["id"], reminder["id"])
        self.assertEqual(len(server.Handler.reminder_store.list_pending_notifications()), 1)

    def test_assistant_endpoint_only_accepts_declared_fields_and_confirms_cancel(self):
        _status, result = self.request_json(
            "/api/assistant/command", "POST", {"command": "What time is it?"}
        )
        self.assertEqual(_status, 200)
        self.assertEqual(result["tool"], "get_time")

        status, result = self.request_json(
            "/api/assistant/command", "POST", {"command": "run shell command to erase data"}
        )
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertNotIn("tool", result)

        due = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.request_json("/api/reminders", "POST", {"title": "Pay bill", "due_at": due})
        status, result = self.request_json(
            "/api/assistant/command", "POST", {"command": "Cancel reminder to Pay bill"}
        )
        self.assertTrue(result["confirmation_required"])
        status, result = self.request_json(
            "/api/assistant/command", "POST", {"command": "Cancel reminder to Pay bill", "confirm": True}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(server.Handler.reminder_store.list_reminders(), [])

        status, result = self.request_json(
            "/api/assistant/command", "POST", {"command": "show my reminders", "shell": "anything"}
        )
        self.assertEqual(status, 400)
        self.assertIn("Only command and confirm", result["error"])

    def test_gemini_endpoint_requires_config_and_explicit_per_request_consent(self):
        status, _result = self.request_json(
            "/api/assistant/gemini", "POST", {"command": "show reminders", "allow_cloud": True}
        )
        self.assertEqual(status, 503)

        adapter = FakeGeminiAdapter({"tool": "get_time", "arguments": {}})
        server.Handler.gemini_adapter = adapter
        status, _result = self.request_json(
            "/api/assistant/gemini", "POST", {"command": "what time is it", "allow_cloud": False}
        )
        self.assertEqual(status, 403)
        self.assertEqual(adapter.commands, [])

    def test_gemini_intent_executes_only_validated_local_tool(self):
        adapter = FakeGeminiAdapter({"tool": "create_reminder", "arguments": {"title": "Stretch", "amount": 10, "unit": "minutes"}})
        server.Handler.gemini_adapter = adapter
        status, result = self.request_json(
            "/api/assistant/gemini", "POST", {"command": "in ten minutes please remind me to stretch", "allow_cloud": True}
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["source"], "gemini")
        self.assertEqual(result["tool"], "create_reminder")
        self.assertEqual(len(server.Handler.reminder_store.list_reminders()), 1)
        self.assertEqual(adapter.commands, ["in ten minutes please remind me to stretch"])

        adapter.proposal = {"tool": "run_shell", "arguments": {"command": "bad"}}
        status, result = self.request_json(
            "/api/assistant/gemini", "POST", {"command": "do something", "allow_cloud": True}
        )
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertEqual(len(server.Handler.reminder_store.list_reminders()), 1)

    def test_gemini_cancel_requires_confirmation(self):
        due = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.request_json("/api/reminders", "POST", {"title": "Pay rent", "due_at": due})
        adapter = FakeGeminiAdapter({"tool": "cancel_reminder", "arguments": {"title": "Pay rent"}})
        server.Handler.gemini_adapter = adapter

        _status, result = self.request_json(
            "/api/assistant/gemini", "POST", {"command": "cancel rent reminder", "allow_cloud": True}
        )
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(len(server.Handler.reminder_store.list_reminders()), 1)

        _status, result = self.request_json(
            "/api/assistant/gemini", "POST", {"command": "cancel rent reminder", "allow_cloud": True, "confirm": True}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(server.Handler.reminder_store.list_reminders(), [])

    def test_alerts_endpoint_returns_structure(self):
        server.Handler.thresholds = dict(server.DEFAULT_THRESHOLDS)
        status, result = self.request_json("/api/alerts")
        self.assertEqual(status, 200)
        self.assertIn("alerts", result)
        self.assertIsInstance(result["alerts"], list)
        self.assertIn("thresholds", result)
        self.assertIsInstance(result["thresholds"], dict)
        for metric in ("cpu_percent", "memory_percent", "temperature_celsius", "disk_percent"):
            self.assertIn(metric, result["thresholds"])

    def test_alerts_no_alerts_when_thresholds_very_high(self):
        server.Handler.thresholds = {
            "cpu_percent": 999.0,
            "memory_percent": 999.0,
            "temperature_celsius": 999.0,
            "disk_percent": 999.0,
        }
        status, result = self.request_json("/api/alerts")
        self.assertEqual(status, 200)
        self.assertEqual(result["alerts"], [])

    def test_settings_get_returns_thresholds(self):
        server.Handler.thresholds = dict(server.DEFAULT_THRESHOLDS)
        status, result = self.request_json("/api/settings")
        self.assertEqual(status, 200)
        self.assertEqual(result["thresholds"], server.Handler.thresholds)

    def test_settings_put_updates_and_persists_thresholds(self):
        server.Handler.thresholds = dict(server.DEFAULT_THRESHOLDS)
        status, result = self.request_json(
            "/api/settings", "PUT", {"thresholds": {"cpu_percent": 50.0, "disk_percent": 40.0}}
        )
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"]["cpu_percent"], 50.0)
        self.assertEqual(result["updated"]["disk_percent"], 40.0)
        self.assertEqual(server.Handler.reminder_store.get_setting("threshold.cpu_percent"), "50.0")
        self.assertEqual(server.Handler.thresholds["cpu_percent"], 50.0)
        self.assertEqual(server.Handler.thresholds["disk_percent"], 40.0)
        self.assertEqual(server.Handler.thresholds["memory_percent"], server.DEFAULT_THRESHOLDS["memory_percent"])

    def test_settings_put_rejects_unknown_metric(self):
        server.Handler.thresholds = dict(server.DEFAULT_THRESHOLDS)
        status, result = self.request_json(
            "/api/settings", "PUT", {"thresholds": {"bogus_metric": 50.0}}
        )
        self.assertEqual(status, 400)
        self.assertIn("Unknown threshold metric", result["error"])

    def test_settings_put_rejects_non_number_and_zero(self):
        server.Handler.thresholds = dict(server.DEFAULT_THRESHOLDS)
        status, result = self.request_json(
            "/api/settings", "PUT", {"thresholds": {"cpu_percent": "not-a-number"}}
        )
        self.assertEqual(status, 400)

        status, result = self.request_json(
            "/api/settings", "PUT", {"thresholds": {"cpu_percent": 0}}
        )
        self.assertEqual(status, 400)

        status, result = self.request_json(
            "/api/settings", "PUT", {"thresholds": {"cpu_percent": -5}}
        )
        self.assertEqual(status, 400)

    def test_settings_put_requires_thresholds_object(self):
        server.Handler.thresholds = dict(server.DEFAULT_THRESHOLDS)
        status, result = self.request_json("/api/settings", "PUT", {"not_thresholds": {}})
        self.assertEqual(status, 400)

    def test_assistant_provider_returns_gemini_status(self):
        server.Handler.gemini_adapter = None
        status, result = self.request_json("/api/assistant/provider")
        self.assertEqual(status, 200)
        self.assertFalse(result["gemini_available"])
        self.assertIsNone(result["gemini_model"])

    def test_assistant_command_includes_tts_field(self):
        status, result = self.request_json(
            "/api/assistant/command", "POST", {"command": "What time is it?"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("tts", False))
        self.assertEqual(result["tool"], "get_time")

    def test_assistant_command_includes_tts_on_error(self):
        status, result = self.request_json(
            "/api/assistant/command", "POST", {"command": "run shell command to erase data"}
        )
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("tts", False))

    def test_assistant_command_empty_rejected(self):
        status, result = self.request_json(
            "/api/assistant/command", "POST", {"command": ""}
        )
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("tts", False))

    def test_assistant_command_oversized_rejected(self):
        status, result = self.request_json(
            "/api/assistant/command", "POST", {"command": "x" * 501}
        )
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("tts", False))

    def test_assistant_command_only_declared_fields(self):
        status, result = self.request_json(
            "/api/assistant/command", "POST", {"command": "What time is it?", "shell": "bad"}
        )
        self.assertEqual(status, 400)


class AlertSettingsTests(unittest.TestCase):
    def test_evaluate_alerts_warning_and_no_alert_below_threshold(self):
        status = {
            "cpu_percent": 90.0,
            "memory": {"percent": 50.0},
            "cpu_temperature": {"celsius": 70.0},
            "disk": {"percent": 60.0},
        }
        thresholds = {
            "cpu_percent": 80.0,
            "memory_percent": 80.0,
            "temperature_celsius": 80.0,
            "disk_percent": 80.0,
        }
        alerts = server.evaluate_alerts(status, thresholds)
        by_metric = {alert["metric"]: alert for alert in alerts}
        self.assertEqual(by_metric["cpu_percent"]["severity"], "warning")
        self.assertEqual(by_metric["cpu_percent"]["value"], 90.0)
        self.assertNotIn("memory_percent", by_metric)
        self.assertNotIn("temperature_celsius", by_metric)
        self.assertNotIn("disk_percent", by_metric)

    def test_evaluate_alerts_critical_severity(self):
        status = {
            "cpu_percent": 97.0,
            "memory": {"percent": 50.0},
            "cpu_temperature": {"celsius": 70.0},
            "disk": {"percent": 60.0},
        }
        thresholds = {
            "cpu_percent": 80.0,
            "memory_percent": 80.0,
            "temperature_celsius": 80.0,
            "disk_percent": 80.0,
        }
        alerts = server.evaluate_alerts(status, thresholds)
        by_metric = {alert["metric"]: alert for alert in alerts}
        # 97 > 80 * 1.2 = 96, so critical
        self.assertEqual(by_metric["cpu_percent"]["severity"], "critical")


if __name__ == "__main__":
    unittest.main()
