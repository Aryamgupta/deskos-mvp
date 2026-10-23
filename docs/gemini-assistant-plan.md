# DeskOS Gemini API assistant plan

## Decision and product boundary

Explore Gemini API as an **optional cloud-assisted command interpreter and response writer**, not as a replacement for DeskOS's local core. This is a deliberate change from the original offline-only requirement. If adopted, DeskOS will no longer be fully offline for natural-language assistant requests. The dashboard clock, monitoring, reminders, and deterministic commands must continue to work without internet or Gemini availability.

The initial configurable model is `gemini-3.5-flash-lite` (documented by Google as available and supporting structured output as of 2026-10-23). Verify model availability and current free-tier limits in AI Studio before use. Gemini is attractive because model inference is remote and avoids the laptop's measured ~29-second cold CLI inference, but real latency, throughput, and account quotas must be measured from this network and account.

## Current implementation status

The backend contains a disabled-by-default Gemini adapter and separate `/api/assistant/gemini` route. It requires server-side `DESKOS_GEMINI_ENABLED=true`, `DESKOS_GEMINI_DATA_POLICY_ACCEPTED=true`, a server-side `GEMINI_API_KEY`, and per-request `allow_cloud: true`. The adapter only returns an intent proposal; DeskOS validates it and invokes the existing local router. Gemini is not used for final phrasing and receives no tool result. A per-process request cap defaults to 10/minute. Automated tests use a fake provider; no live provider request or key has been configured/tested.

The dashboard has per-request cloud consent plus local-only dictation/TTS controls guarded by browser capability checks. The current LAN HTTP endpoint is not a secure context for microphone APIs on most mobile browsers, and the Realme C2 has not been tested. Dictation may require a trusted HTTPS setup; typed input remains available. No voice capture, Gemini call, or device speech output has been verified on that phone.

## Intended voice-command chain

```text
Push-to-talk on phone
    -> device/on-device speech recognition
    -> show transcript for correction and explicit Send
    -> DeskOS backend sends permitted text to Gemini for an allowlisted intent
    -> DeskOS validates intent/arguments and executes its own local tool
    -> local response template by default
             OR separately consented, minimized tool result -> Gemini phrasingl
    -> phone's verified offline speechSynthesis/TTS, otherwise visible text
```

The first release should use push-to-talk, not an always-listening wake phrase. A wake phrase such as “Hello Desk” is possible in principle and can be added as a later, optional **on-device wake-word detector**; this is a small audio classifier, not a local LLM. Speech recognition must be proven to run on-device on the Realme C2; browser `SpeechRecognition` implementations can use a remote service and must not be presumed local. If device-local transcription is unavailable or cannot be verified, use typed text as the supported fallback rather than uploading audio. The Gemini request is a distinct cloud boundary: the user sees and can edit the transcript before it is sent. No camera/audio media is sent to Gemini in this stage.

**Wake-word feasibility and platform limit:** a lightweight detector could listen locally for only the wake phrase and begin command capture after detection. However, a browser/PWA tab is not a dependable always-on microphone host: Android can suspend/background it, screen-off behavior varies by browser/device, microphone access needs permission and supported security context, and continuous recognition can use battery. Reliable screen-off listening may require a dedicated Android app with a microphone foreground service, persistent user-visible notification, runtime microphone permission, and vendor battery-management configuration. That is a larger mobile-client workstream than the current web dashboard. Do not promise lock-screen or background wake behavior until tested on the actual Realme C2 and Android/browser version.

**Free-tier privacy gate:** Google's current unpaid-service terms say prompts and responses may be used to improve Google products and may be reviewed, and advise against submitting sensitive/confidential/personal information. Therefore use synthetic/non-sensitive test phrases only for free-tier evaluation. Do not send real voice transcripts, reminder titles, or system values through the free tier unless the user has reviewed the current terms and explicitly accepts that data handling; for real personal commands, use an eligible paid tier if its terms are acceptable, or stay on the local deterministic path. Merely checking a “cloud enabled” box is not enough to treat sensitive personal data as safe.

After a validated local action, prefer deterministic local response text. If the product later sends tool results to Gemini to produce a conversational response, this needs a separate opt-in because status values and reminder titles are personal data. Send only the smallest useful summary, never the whole database/status payload. If consent is absent, Gemini is unavailable, or the result is sensitive, use the local result template. The final answer can be spoken only if an offline-capable Android/browser TTS voice is verified on the target device; otherwise show text. Avoid downloading or running a separate local TTS model for the initial release.

## Important privacy, quota, and service constraints

- **Free tier is not private/offline.** Current Gemini API pricing/terms state unpaid-tier prompts, system instructions, and responses may be used to improve Google products and may be reviewed by people. Never send raw system metrics, hostnames, reminder contents, personal identifiers, secrets, or speech transcripts by default. Send only the minimum redacted user request needed to classify an intent. Prefer paid service only if its separate terms are acceptable; paid prompts are not used to improve products per current terms.
- **The free tier has limited quotas and no availability guarantee.** RPM, TPM, and requests/day vary by model, project, and account, can change, and may return 429. Read active project limits in AI Studio; don't hardcode assumptions or promise a fixed daily count. Do not enable automatic billing just to overcome quota without an explicit user decision.
- **Terms:** Current Gemini API Additional Terms describe the API/AI Studio as for professional or business developer use, not consumer use, and require use from supported regions. Confirm that a personal DeskOS development project fits the applicable terms and region before sending real data.
- **Connectivity:** Gemini calls require internet access, Google service availability, a valid API key, and an eligible project. Offline fallback is mandatory.
- **Key handling:** Store the key in an environment variable or user/systemd environment file outside Git and browser code; never return it to the dashboard. Restrict the key to Gemini API where applicable, monitor quota, and rotate promptly if leaked. Standard keys identify a project, not the calling user; do not treat the key as end-user authentication.
- **No client-side key:** The browser must call DeskOS's backend only. The backend calls Gemini. Keep the local endpoint bound to the trusted LAN policy already used by DeskOS.

## Target architecture

```text
Browser UI --local HTTP--> DeskOS backend
                              |-- deterministic local command router (always available)
                              |-- Gemini adapter (optional, outbound HTTPS)
                              |-- validated local tool dispatcher
                              `-- SQLite reminder store
```

The model returns a constrained intent/result object. DeskOS independently validates it against a fixed allowlist and existing server-side schemas. The model must never receive shell access, execute its own function calls, write SQLite directly, or decide whether confirmation can be skipped. Preserve the current local `AssistantRouter` as a fallback and as the authoritative implementation of safe local actions.

Initial tools available to model routing only:

- `get_time`
- `get_system_status`
- `get_device_status`
- `list_reminders`
- `create_reminder`
- `cancel_reminder`
- `unsupported`

Do not send the current reminder list or monitoring payload to the provider. For system/device status, the model can select the tool; the local dispatcher fetches and formats the result. For reminder actions, include only the user's supplied title/duration. A cancellation always goes through the existing confirmation flow.

## Implementation milestones

### G1 — Privacy and policy gate

1. Confirm the product tradeoff: remote processing is acceptable for explicitly submitted, user-reviewed transcript text; no automatic background data, audio, camera, full metrics, or reminder lists are sent. Free-tier use is restricted to synthetic/non-sensitive test utterances; real personal commands require an explicit terms/privacy decision and an eligible tier.
2. Confirm current Gemini terms, supported region, chosen model availability, quotas, and whether the intended personal project use is allowed.
3. Add an explicit UI opt-in and visible “Cloud assistant enabled” status. Default it off until the user enables it.
4. Add a data minimization notice near the input and a redaction policy. Never log transcript, request content, API key, or provider response by default. Make result-to-Gemini phrasing a separate opt-in from sending the transcript for intent parsing.

**Acceptance:** no provider request happens without cloud enablement and an explicit send action; disabling or missing network/key falls back locally. No audio is uploaded; no tool-result payload is sent unless result-sharing consent is separately enabled. Free-tier tests contain only synthetic/non-sensitive input.

### G2 — Provider adapter in shadow/evaluation mode

1. Add one isolated backend adapter for the official Gemini API / supported Google GenAI SDK. Do not modify the existing deterministic routes yet.
2. Read the key only from environment configuration, apply connect/read timeouts, a strict response-size limit, and at most one retry for transient 429/5xx with bounded backoff and `Retry-After` respect.
3. Set a small output-token ceiling and request structured JSON / function declarations. Use only non-sensitive user text and a short tool catalog. Do not use Google Search grounding, remote MCP, URL-context, or code execution for MVP.
4. Parse the returned intent and reject unknown names, extra arguments, wrong types, invalid durations, missing fields, or multiple calls. Never dispatch an unvalidated provider call.
5. Provide a development-only benchmark/report option with synthetic test phrases, no personal data, and no prompts persisted.

**Acceptance:** provider errors are handled without breaking the page; all actions remain local and deterministic after validating tool intents.

### G3 — Local speech I/O and opt-in Gemini command path

1. Implement push-to-talk UI and visible microphone state; capture a single utterance only after user action.
2. Evaluate the Realme C2's actual on-device speech-recognition path. Confirm offline operation by disabling internet during the device test. Do not rely on Web Speech API support claims alone. If not local/reliable, retain text entry.
3. Show transcript editable to the user. Submit only after an explicit Send action when cloud assistant is opted in.
4. Add provider setting `assistant.provider=local|gemini` or equivalent, default `local` until the privacy gate is passed. The Gemini route only interprets the approved transcript and returns a structured intent proposal.
5. Execute tools locally only after argument validation. Cancellation still asks the user to confirm; creating/editing/deleting any consequential item should follow existing confirmation rules.
6. Format ordinary result text locally. A separate setting/consent may enable sending a minimal, sanitized result summary to Gemini for response phrasing; do not pass the full status payload or reminder records.
7. Use the browser/phone's system speech synthesis only after confirming its voice works offline on the Realme C2. If unavailable, display the response without blocking the action.
8. Add response/source labels (“Gemini cloud” vs “Local fallback”) and distinguish provider outage, offline, rate limit, invalid response, and unsupported command.

**Acceptance:** local functionality works after disconnecting internet; no audio/media is uploaded; Gemini path works only when enabled and the reviewed transcript is explicitly sent; free-tier evaluation uses synthetic/non-sensitive input only; result sharing is separately controlled; TTS is verified device-local or gracefully replaced by visible text; invalid output is safely rejected.

### G3b — Optional local wake-word trigger (after push-to-talk passes)

1. First verify push-to-talk speech capture, on-device transcription, cancellation, and battery behavior on the target phone.
2. Evaluate a small on-device wake-word detector for “Hello Desk” separately from speech recognition and Gemini. The detector only triggers command capture; it does not interpret commands and does not upload audio.
3. Start with foreground/visible operation on the existing web dashboard if the Android browser supports it. Measure false activations, missed triggers, CPU/battery drain, heat, and behavior during screen-off/background states.
4. If reliable background/lock-screen wake is a hard requirement and the browser fails, treat a native Android foreground-service client as a separately scoped mobile project. It must show a persistent listening indicator/notification, provide immediate stop/disable controls, and avoid storing raw audio.
5. Keep push-to-talk and typed input available as permanent alternatives; wake-word listening is opt-in and off by default.

**Acceptance:** wake phrase is detected locally, raw audio is not transmitted or retained, user-visible listening state and stop controls work, measured battery/resource costs are acceptable on the Realme C2, and limitations for background/locked operation are documented. If the target device cannot meet those checks, do not implement always-on listening; retain push-to-talk.

### G4 — Hardening and release decision

- Add tests with a fake Gemini client for timeouts, quota/429, 5xx, malformed JSON, unknown tool, extra arguments, incorrect integer/string types, missing/oversized values, and fallback behavior.
- Add tests proving no reminder body, metrics, hostname, API key, or provider output is logged or transmitted unexpectedly.
- Test network loss, invalid/revoked key without exposing it in errors, quota exhaustion, service restart, multiple phones, and duplicate submit behavior.
- Verify the phone speech-recognition and speech-synthesis implementations in offline mode; document Android/browser/foreground limitations. Test microphone cancellation and ensure no background recording.
- Review costs/quotas and usage in AI Studio. Keep any billing disabled unless the user explicitly elects paid service.
- Document data flows, retention, disable/reset steps, and provider limitations in security and deployment docs.
- Do not promote Gemini to default until privacy/terms are accepted and accuracy, latency, quota, and fallback acceptance criteria are met.

## Limitations and trade-offs

1. This design is **not offline-first for AI**. Internet or Google availability is needed for Gemini features; an offline fallback remains, but it will understand fewer phrasings.
2. Free-tier data may be used to improve Google products and reviewed. Do not send personal reminder details, status telemetry, raw speech, camera imagery, or secrets. Treat a voice transcript itself as potentially personal. If sending the user's command text is unacceptable, do not enable Gemini for that request.
3. Free quotas can change, vary by account/model, and be exhausted; an assistant request may be throttled or unavailable. A “free” tier should not be treated as a service-level guarantee.
4. Provider terms currently state a professional/business developer use purpose; verify personal-use eligibility before proceeding.
5. A server-side key protects it from the browser, but a personal backend exposed on a LAN still needs access controls if untrusted people can reach it. Gemini's API key is not a substitute for user authentication.
6. Model output can still be semantically wrong even when valid JSON. Server-side validation, limits, confirmations, audit-safe results, and explicit unsupported responses remain necessary.
7. Cloud response speed may improve relative to local CPU inference but depends on network, region, quotas, and service load; benchmark actual latency before choosing it.
8. Switching provider/model, API semantics, rate limits, and pricing are external dependencies that can change. Pin integration versions where possible and keep the adapter replaceable.
9. Browser speech recognition or speech synthesis may be unsupported, unavailable offline, or unreliable while the page is backgrounded on the Realme C2. Text input and visible response remain required fallbacks.
10. Continuous wake-word detection is distinct from local speech recognition and from Gemini. A browser-only implementation may stop when backgrounded or screen-locked; dependable background wake may require a native Android foreground service, which adds maintenance, battery, permission, and device-compatibility costs.

## Release recommendation

Proceed only with G1 and synthetic G2 evaluation first. Do not send actual reminders, system metrics, or real command history to the free Gemini tier. If privacy and terms pass review, compare a short synthetic intent benchmark and latency against the Qwen local benchmark. Then decide whether the faster but cloud-dependent option is worth enabling as an explicit opt-in while keeping the local assistant fallback.

## Official references checked 2026-10-23

- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Gemini API Additional Terms](https://ai.google.dev/gemini-api/terms)
- [Function calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Structured output](https://ai.google.dev/gemini-api/docs/structured-output)
- [API key management](https://ai.google.dev/gemini-api/docs/api-key)
- [Gemini 3.5 Flash-Lite model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
