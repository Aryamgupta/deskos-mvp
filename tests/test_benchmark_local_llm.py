import tempfile
import unittest
from pathlib import Path
import sys

from tools.benchmark_local_llm import CASES, run_case, score_output, summarize


class BenchmarkScoringTests(unittest.TestCase):
    def test_parses_valid_json_with_cli_prefix(self):
        case = next(item for item in CASES if item.name == "create_reminder")
        output = 'model startup log\n{"tool":"create_reminder","arguments":{"title":"stretch","amount":10,"unit":"minutes"}}'
        score = score_output(output, case)
        self.assertTrue(score["json_valid"])
        self.assertTrue(score["tool_correct"])
        self.assertTrue(score["arguments_correct"])

    def test_rejects_invalid_json_and_extra_top_level_fields(self):
        case = CASES[0]
        self.assertFalse(score_output("not json", case)["json_valid"])
        score = score_output('{"tool":"get_time","arguments":{},"shell":"bad"}', case)
        self.assertFalse(score["json_valid"])

    def test_summary_reports_accuracy_and_resource_metrics(self):
        case = CASES[0]
        result = {
            "latency_seconds": 1.25,
            "peak_rss_mib": 64.0,
            "timed_out": False,
            "exit_code": 0,
            "score": score_output('{"tool":"get_time","arguments":{}}', case),
        }
        summary = summarize([result])
        self.assertEqual(summary["tool_accuracy"], 1.0)
        self.assertEqual(summary["exact_argument_accuracy"], 1.0)
        self.assertEqual(summary["mean_cold_latency_seconds"], 1.25)
        self.assertEqual(summary["max_peak_rss_mib"], 64.0)

    def test_invokes_cli_without_shell_and_scores_output(self):
        case = CASES[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"placeholder for test shim")
            shim = root / "fake_cli.py"
            shim.write_text(
                "import sys\n"
                "print('{\\\"tool\\\":\\\"get_time\\\",\\\"arguments\\\":{}}')\n",
                encoding="utf-8",
            )
            result = run_case(
                sys.executable,
                model,
                case,
                max_tokens=16,
                timeout=5,
                cli_args=[str(shim)],
            )
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertTrue(result["score"]["arguments_correct"])
        self.assertGreaterEqual(result["peak_rss_mib"], 0)

    def test_prompt_separates_system_policy_from_user_text(self):
        from tools.benchmark_local_llm import OUTPUT_SCHEMA, SYSTEM_INSTRUCTION, build_prompt

        prompt = build_prompt("show my reminders")
        self.assertNotIn("Allowed tools:", prompt)
        self.assertIn("User request: show my reminders", prompt)
        self.assertIn("Allowed tools:", SYSTEM_INSTRUCTION)
        self.assertEqual(OUTPUT_SCHEMA["additionalProperties"], False)
        self.assertIn("unsupported", OUTPUT_SCHEMA["properties"]["tool"]["enum"])


if __name__ == "__main__":
    unittest.main()
