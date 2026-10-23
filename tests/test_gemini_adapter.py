import json
import unittest
from io import BytesIO
from urllib.error import HTTPError

from gemini_adapter import GeminiAdapter, GeminiError, MODEL_DEFAULT


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        _ = _args
        return False

    def read(self, size=-1):
        return self._payload if size < 0 else self._payload[:size]


def response_with_intent(intent):
    return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(intent)}]}}]}).encode()


class GeminiAdapterTests(unittest.TestCase):
    def test_environment_is_opt_in_and_never_requires_a_key_value_in_code(self):
        self.assertIsNone(GeminiAdapter.from_environment({"GEMINI_API_KEY": "secret"}))
        self.assertIsNone(GeminiAdapter.from_environment({"DESKOS_GEMINI_ENABLED": "true"}))
        config = {"DESKOS_GEMINI_ENABLED": "true", "DESKOS_GEMINI_DATA_POLICY_ACCEPTED": "true", "GEMINI_API_KEY": "test-key"}
        adapter = GeminiAdapter.from_environment(config)
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.model, MODEL_DEFAULT)
        config["DESKOS_GEMINI_DATA_POLICY_ACCEPTED"] = "false"
        self.assertIsNone(GeminiAdapter.from_environment(config))

    def test_sends_only_command_text_with_small_json_schema_request(self):
        captured = {}
        intent = {"tool": "list_reminders", "arguments": {}}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(response_with_intent(intent))

        adapter = GeminiAdapter("unit-test-key", opener=opener)
        result = adapter.interpret("Show my reminders")
        self.assertEqual(result, intent)
        self.assertEqual(captured["timeout"], 12)
        self.assertEqual(captured["request"].get_header("X-goog-api-key"), "unit-test-key")
        body = json.loads(captured["request"].data)
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "Show my reminders")
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertLessEqual(body["generationConfig"]["maxOutputTokens"], 160)

    def test_rejects_empty_and_oversized_commands_before_network_call(self):
        calls = []
        adapter = GeminiAdapter("unit-test-key", opener=lambda *_a, **_k: self._record_call(calls))
        for command in ("", "x" * 501):
            with self.subTest(length=len(command)), self.assertRaises(GeminiError):
                adapter.interpret(command)
        self.assertEqual(calls, [])

    @staticmethod
    def _record_call(calls):
        calls.append(True)
        return FakeResponse(b"{}")

    def test_maps_quota_and_network_failures_to_safe_messages(self):
        def limited(*_args, **_kwargs):
            raise HTTPError("https://example.invalid", 429, "limited", {}, BytesIO(b"private provider detail"))

        with self.assertRaises(GeminiError) as caught:
            GeminiAdapter("unit-test-key", opener=limited).interpret("what time is it")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertNotIn("private provider detail", str(caught.exception))

    def test_rejects_unreadable_or_oversized_provider_responses(self):
        malformed = GeminiAdapter("unit-test-key", opener=lambda *_a, **_k: self._fake_response(b"not-json"))
        with self.assertRaisesRegex(GeminiError, "unreadable"):
            malformed.interpret("what time is it")

        oversized_payload = b" " * (32 * 1024 + 1)
        oversized = GeminiAdapter("unit-test-key", opener=lambda *_a, **_k: self._fake_response(oversized_payload))
        with self.assertRaisesRegex(GeminiError, "oversized"):
            oversized.interpret("what time is it")

    @staticmethod
    def _fake_response(payload):
        return FakeResponse(payload)


if __name__ == "__main__":
    unittest.main()
