#!/usr/bin/env python3
"""Benchmark a local llama.cpp-compatible CLI against DeskOS intent examples.

This script requires an already-downloaded local model file. It never fetches a
model and never executes model-produced tools; it only scores structured text.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

import psutil


@dataclass(frozen=True)
class Case:
    name: str
    utterance: str
    expected_tool: str
    expected_arguments: dict[str, Any]


CASES = (
    Case("time", "Could you tell me what time it is?", "get_time", {}),
    Case("system_status", "How is the laptop doing right now?", "get_system_status", {}),
    Case("device_status", "Can you check if my laptop is online?", "get_device_status", {}),
    Case("list_reminders", "What reminders do I have coming up?", "list_reminders", {}),
    Case("create_reminder", "Please remind me to stretch in 10 minutes.", "create_reminder", {"title": "stretch", "amount": 10, "unit": "minutes"}),
    Case("create_reminder_paraphrase", "In an hour, remind me to check the laundry.", "create_reminder", {"title": "check the laundry", "amount": 1, "unit": "hours"}),
    Case("create_reminder_days", "Set a reminder to call mum in 2 days.", "create_reminder", {"title": "call mum", "amount": 2, "unit": "days"}),
    Case("cancel_reminder", "Cancel my reminder to water plants.", "cancel_reminder", {"title": "water plants"}),
    Case("unsupported", "Search the web for today's weather.", "unsupported", {}),
)

SYSTEM_INSTRUCTION = """You classify a user's request for DeskOS, an offline personal assistant.
Return exactly one JSON object and no markdown. Shape: {\"tool\": string, \"arguments\": object}.
Allowed tools: get_time, get_system_status, get_device_status, list_reminders,
create_reminder(title:string, amount:integer, unit:minutes|hours|days|weeks),
cancel_reminder(title:string), unsupported.
For get_time, get_system_status, get_device_status, and list_reminders use arguments {} exactly.
For create_reminder, amount must be a JSON integer, not a string. Keep the complete reminder title.
For cancel_reminder, include only the exact title; confirmation is handled separately by DeskOS.
Never invent tool names. Requests for web search, weather, shell access, or unrelated tasks use unsupported with arguments {}.
Examples:
User: How is the laptop doing? JSON: {\"tool\":\"get_system_status\",\"arguments\":{}}
User: Is my laptop online? JSON: {\"tool\":\"get_device_status\",\"arguments\":{}}
User: Remind me to stretch in 10 minutes. JSON: {\"tool\":\"create_reminder\",\"arguments\":{\"title\":\"stretch\",\"amount\":10,\"unit\":\"minutes\"}}
User: Search the web for weather. JSON: {\"tool\":\"unsupported\",\"arguments\":{}}
Do not add fields, explanations, shell commands, or executable code."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {
            "type": "string",
                "enum": sorted({case.expected_tool for case in CASES}),
        },
        "arguments": {"type": "object"},
    },
    "required": ["tool", "arguments"],
    "additionalProperties": False,
}


def build_prompt(utterance: str) -> str:
    return f"User request: {utterance}\nReturn the JSON object now."


def extract_json(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def normalize_arguments(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key).lower(): normalize_arguments(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_arguments(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip().lower())
    return value


def score_output(text: str, case: Case) -> dict[str, Any]:
    payload = extract_json(text)
    if payload is None:
        return {"json_valid": False, "tool_correct": False, "arguments_correct": False, "parsed": None}

    tool = payload.get("tool")
    arguments = payload.get("arguments")
    valid_shape = isinstance(tool, str) and isinstance(arguments, dict) and set(payload) == {"tool", "arguments"}
    tool_correct = valid_shape and tool == case.expected_tool
    arguments_correct = (
        tool_correct
        and normalize_arguments(arguments) == normalize_arguments(case.expected_arguments)
    )
    return {
        "json_valid": valid_shape,
        "tool_correct": tool_correct,
        "arguments_correct": arguments_correct,
        "parsed": payload,
    }


def run_case(
    cli: str,
    model: Path,
    case: Case,
    max_tokens: int,
    timeout: float,
    cli_args: list[str] | None = None,
) -> dict[str, Any]:
    prompt = build_prompt(case.utterance)
    if cli_args is None:
        command = [
            cli,
            "-m", str(model),
            "-sys", SYSTEM_INSTRUCTION,
            "-p", prompt,
            "-n", str(max_tokens),
            # A small nonzero temperature avoids sampler initialization failures
            # in some llama.cpp JSON-schema-constrained builds.
            "--temp", "0.1",
            "-t", str(psutil.cpu_count(logical=False) or 2),
            # DeskOS command parsing needs little context; avoid reserving the
            # model's full 32K context on a low-RAM workstation.
            "-c", "2048",
            "--no-display-prompt",
            "--simple-io",
            "--single-turn",
            "--jinja",
            "--offline",
        ]
    else:
        replacements = {"{model}": str(model), "{prompt}": prompt, "{max_tokens}": str(max_tokens)}
        command = [cli]
        for argument in cli_args:
            for key, replacement in replacements.items():
                argument = argument.replace(key, replacement)
            command.append(argument)

    started = time.perf_counter()
    peak_rss = 0
    try:
        with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
            process = subprocess.Popen(
                command,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                close_fds=True,
            )
            try:
                tracked_process = psutil.Process(process.pid)
                while process.poll() is None:
                    try:
                        peak_rss = max(peak_rss, tracked_process.memory_info().rss)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    if time.perf_counter() - started > timeout:
                        process.kill()
                        process.wait()
                        raise subprocess.TimeoutExpired(command, timeout)
                    time.sleep(0.05)
                try:
                    peak_rss = max(peak_rss, tracked_process.memory_info().rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            except Exception:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                raise
            elapsed = time.perf_counter() - started
            stdout_file.seek(0)
            output = stdout_file.read().decode("utf-8", errors="replace")
            stderr_file.seek(0)
            stderr = stderr_file.read().decode("utf-8", errors="replace")
            return_code = process.returncode
    except subprocess.TimeoutExpired:
        return {
            "name": case.name,
            "utterance": case.utterance,
            "expected_tool": case.expected_tool,
            "latency_seconds": round(time.perf_counter() - started, 3),
            "peak_rss_mib": round(peak_rss / (1024 * 1024), 1),
            "exit_code": None,
            "timed_out": True,
            "stderr_tail": "Model invocation exceeded the timeout.",
            "output": "",
            "score": score_output("", case),
        }

    score = score_output(output, case)
    return {
        "name": case.name,
        "utterance": case.utterance,
        "expected_tool": case.expected_tool,
        "latency_seconds": round(elapsed, 3),
        "peak_rss_mib": round(peak_rss / (1024 * 1024), 1),
        "exit_code": return_code,
        "timed_out": False,
        "stderr_tail": stderr[-1000:],
        "output": output[-2000:],
        "score": score,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    latencies = [row["latency_seconds"] for row in results if not row["timed_out"]]
    valid = sum(bool(row["score"]["json_valid"]) for row in results)
    tools = sum(bool(row["score"]["tool_correct"]) for row in results)
    arguments = sum(bool(row["score"]["arguments_correct"]) for row in results)
    return {
        "cases": count,
        "valid_json_rate": round(valid / count, 3) if count else 0,
        "tool_accuracy": round(tools / count, 3) if count else 0,
        "exact_argument_accuracy": round(arguments / count, 3) if count else 0,
        "mean_cold_latency_seconds": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "max_peak_rss_mib": max((row["peak_rss_mib"] for row in results), default=0),
        "timeouts": sum(bool(row["timed_out"]) for row in results),
        "cli_errors": sum(row["exit_code"] not in (0, None) for row in results),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path, help="Path to an already-present local GGUF model file; no download is performed")
    parser.add_argument("--cli", default="llama-cli", help="Path/name of a llama.cpp-compatible CLI (default: llama-cli)")
    parser.add_argument("--timeout", type=float, default=180, help="Per-case process timeout in seconds")
    parser.add_argument("--max-tokens", type=int, default=128, help="Maximum generated tokens per test case")
    parser.add_argument("--cases", nargs="*", help="Optional case names to run; defaults to the whole suite")
    parser.add_argument("--cli-arg", action="append", help="Replace default CLI args; repeat per argument and use {model}, {prompt}, {max_tokens} placeholders")
    parser.add_argument("--output", type=Path, help="Optional path for the complete JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    model = args.model.expanduser().resolve()
    if not model.is_file():
        print(f"Model file not found: {model}. Place a model locally first; this tool never downloads one.", file=sys.stderr)
        return 2
    if args.timeout <= 0 or args.max_tokens < 1:
        print("--timeout and --max-tokens must be positive.", file=sys.stderr)
        return 2

    cli = shutil.which(args.cli)
    if cli is None:
        candidate = Path(args.cli).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            cli = str(candidate.resolve())
        else:
            print(f"Local inference CLI not found: {args.cli}", file=sys.stderr)
            return 2

    selected_cases = CASES
    if args.cases:
        unknown = sorted(set(args.cases) - {case.name for case in CASES})
        if unknown:
            print("Unknown case name(s): " + ", ".join(unknown), file=sys.stderr)
            return 2
        selected_cases = tuple(case for case in CASES if case.name in set(args.cases))

    print(f"Benchmarking local model: {model}", flush=True)
    print(f"Runtime: {cli}", flush=True)
    print(f"Cases: {len(selected_cases)}; max generated tokens: {args.max_tokens}; timeout: {args.timeout:g}s per case", flush=True)
    print("Outputs are scored only; no predicted tool is executed.", flush=True)

    results = []
    for case in selected_cases:
        result = run_case(cli, model, case, args.max_tokens, args.timeout, args.cli_arg)
        results.append(result)
        score = result["score"]
        print(
            f"{case.name}: tool={score['tool_correct']} args={score['arguments_correct']} "
            f"json={score['json_valid']} latency={result['latency_seconds']:.2f}s "
            f"peak-rss={result['peak_rss_mib']:.1f} MiB",
            flush=True,
        )

    report = {"model": str(model), "runtime": cli, "summary": summarize(results), "results": results}
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.expanduser().write_text(rendered + "\n", encoding="utf-8")
        print(f"Report saved to {args.output.expanduser()}", flush=True)
    print("\nSummary:\n" + json.dumps(report["summary"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
