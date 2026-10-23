from datetime import datetime, timedelta, timezone
import tempfile
import unittest

from assistant import AssistantRouter, TOOL_SCHEMAS
from reminder_store import ReminderStore


class AssistantRouterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ReminderStore(f"{self.temp_dir.name}/assistant.sqlite3")
        self.now = datetime.now(timezone.utc) + timedelta(seconds=1)
        self.status_calls = 0

        def status_provider():
            self.status_calls += 1
            return {
                "hostname": "desk-test",
                "cpu_percent": 12.0,
                "memory": {"percent": 50.0},
                "disk": {"percent": 40.0},
                "cpu_temperature": {"sensor": "CPU", "celsius": 45.0},
            }

        self.router = AssistantRouter(self.store, status_provider, clock=lambda: self.now)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_time_and_status_are_local_deterministic_tools(self):
        time_result = self.router.handle("What time is it?")
        self.assertTrue(time_result["ok"])
        self.assertEqual(time_result["tool"], "get_time")
        self.assertIn(self.now.strftime("%-I:%M %p"), time_result["message"])

        status_result = self.router.handle("How is my laptop doing?")
        self.assertEqual(status_result["tool"], "get_system_status")
        self.assertIn("CPU 12%", status_result["message"])
        self.assertEqual(self.status_calls, 1)

    def test_create_and_list_reminder(self):
        result = self.router.handle("Remind me to stretch in 10 minutes")
        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "create_reminder")
        self.assertEqual(result["data"]["reminder"]["title"], "stretch")
        self.assertEqual(len(self.store.list_reminders()), 1)

        listing = self.router.handle("Show my reminders")
        self.assertEqual(listing["tool"], "list_reminders")
        self.assertIn("stretch", listing["message"])

    def test_cancel_requires_confirmation_and_matches_exact_title(self):
        reminder = self.store.create("Pay rent", "2026-10-24T12:00:00Z")
        challenge = self.router.handle("Cancel reminder to Pay rent")
        self.assertTrue(challenge["confirmation_required"])
        self.assertEqual(self.store.list_reminders()[0]["id"], reminder["id"])

        result = self.router.handle("Cancel reminder to Pay rent", confirm=True)
        self.assertTrue(result["ok"])
        self.assertEqual(self.store.list_reminders(), [])

    def test_ambiguous_cancellation_never_changes_reminders(self):
        self.store.create("Water plants", "2026-10-24T12:00:00Z")
        self.store.create("Water plants", "2026-10-25T12:00:00Z")
        result = self.router.handle("Cancel reminder to Water plants", confirm=True)
        self.assertFalse(result["ok"])
        self.assertEqual(len(self.store.list_reminders()), 2)

    def test_unknown_commands_cannot_access_shell_or_invoke_tools(self):
        result = self.router.handle("run shell command to delete files")
        self.assertFalse(result["ok"])
        self.assertNotIn("tool", result)
        self.assertEqual(self.status_calls, 0)

    def test_rejects_invalid_confirmation_and_oversized_command(self):
        self.assertFalse(self.router.handle("show my reminders", confirm="yes")["ok"])
        self.assertFalse(self.router.handle("x" * 501)["ok"])

    def test_tool_catalog_is_explicit_and_contains_no_shell(self):
        self.assertIn("get_system_status", TOOL_SCHEMAS)
        self.assertIn("create_reminder", TOOL_SCHEMAS)
        self.assertIn("cancel_reminder", TOOL_SCHEMAS)
        self.assertFalse(any("shell" in name for name in TOOL_SCHEMAS))


if __name__ == "__main__":
    unittest.main()
