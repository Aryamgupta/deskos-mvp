# DeskOS local LLM evaluation

## Goal and safety boundary

Evaluate a small, quantized local language model as a natural-language **intent parser**. The model may propose one structured tool name and arguments; DeskOS remains responsible for validation, confirmation, and executing its existing local functions. Model output is benchmarked as text only and is never executed by the benchmark.

This stage does not add a cloud API, runtime model download, autonomous shell access, or voice input. Keep the deterministic command router available as a fallback. The tool catalog should remain allowlisted, with strict per-tool schemas. Reminder cancellation and other consequential operations must continue to require confirmation.

## Hardware baseline

The development laptop was observed as an AMD Ryzen 3 3250U (2 cores / 4 threads), 13 GiB RAM, and approximately 109 GiB available disk. At the time of inspection, about 6.8 GiB RAM was available. No Ollama, llama.cpp CLI, llamafile, or existing Hugging Face/Ollama model cache was found.

This suggests evaluating CPU inference with small instruction-tuned GGUF models, starting in roughly the 1B–3B parameter class and a low-bit quantization. A concrete first candidate is **Qwen2.5-1.5B-Instruct-GGUF Q4_K_M**: its model card declares Apache-2.0 and lists the Q4_K_M artifact at about 1.12 GB. This is only a benchmark candidate, not a selected production model or a performance claim. The future Pi 4 has not been purchased and must be measured separately.

## Benchmark harness

`tools/benchmark_local_llm.py` runs a fixed set of representative DeskOS requests against an already-installed `llama-cli`-compatible executable and an already-present local model file. It reports:

- JSON output validity and exact expected tool/argument accuracy.
- Per-request elapsed time, including process startup and model load (cold CLI latency).
- Peak resident memory observed for the inference process.
- Timeouts and runtime exit errors.

No model files are fetched. The llama.cpp invocation sets `--offline`, uses a local model path, separates the system instruction from the user request, constrains output to a JSON schema, uses a bounded thread count, caps generated tokens, imposes a timeout, and only scores returned text. Subprocesses are started with shell execution disabled. Custom command-line interfaces can be mapped with repeated `--cli-arg` options and `{model}`, `{prompt}`, and `{max_tokens}` placeholders; the custom runtime must independently be configured for offline operation.

From the repository root, run the tests:

```bash
python -m unittest discover -s tests -v
```

After a local llama.cpp-compatible runtime and a model have been installed separately, check the runtime's supported flags (`llama-cli --help`) and run the full benchmark. For CLI variants with different options, map arguments explicitly. For llama.cpp, use the official Qwen GGUF repository and select the Q4_K_M file; download it during setup, not from DeskOS or this benchmark. The report can be saved to a chosen local path:

```bash
python tools/benchmark_local_llm.py --model /absolute/path/to/model.gguf --cli llama-cli --output /tmp/deskos-llm-benchmark.json
```

The model path must already exist. Do not use a model URI or a command that downloads from a registry. Review the model's license and source before selecting it. Keep benchmark reports local if prompts or paths contain personal information.

## Evaluation criteria

Record these for each candidate, using the same prompts and laptop state:

1. **Tool accuracy:** correct intent and arguments, especially reminder title, duration, unit, unsupported requests, and ambiguity.
2. **Valid structure:** strict JSON with only the specified keys; malformed or additional fields count as failure.
3. **Latency:** cold command latency now. If a candidate is viable, measure warm repeated requests in the eventual persistent runtime before deciding.
4. **Memory and system impact:** peak RSS, available RAM before/after, swap activity, laptop responsiveness, and temperature under repeated runs.
5. **Offline behavior:** stop internet connectivity for the final test and verify no runtime fetches or external requests are required.
6. **License and maintenance:** confirm the model license, quantization provenance, runtime support, and how setup can be performed without making runtime use depend on the network.

Do not select a model based on parameter count alone. Keep the LLM only if it materially improves paraphrase handling over the deterministic router while staying within agreed memory/latency limits. If it fails a case, reject its output and ask the user to rephrase; never guess and execute. The current llama.cpp `--json-schema` constrained-decoding path failed to initialize samplers on this local build, so the benchmark currently uses prompt-only JSON instructions and strictly scores the result; this must not be mistaken for schema enforcement. Server-side validation is still mandatory.

## Expected limitations

A small CPU model may be slow, may misread natural-language time expressions, and may emit invalid or invented values. JSON prompting is not a security boundary; server-side schema validation and tool permissions remain mandatory. The benchmark currently measures one CLI process per request, so latency includes startup and is not representative of a persistent inference server's warm latency. The harness checks a fixed English test suite rather than general conversational ability. No result establishes suitability for the Realme C2 or the future Raspberry Pi.
