# DeskOS — Master Project Context & Autonomous Development Brief

## 1. Project Identity

**Project name:** DeskOS  
**Category:** Offline-first personal AI assistant, smart desk operating system, and local automation platform  
**Primary objective:** Build a lightweight, privacy-focused, always-available assistant that connects my laptop, Android phone, and eventually a Raspberry Pi into one cohesive local system.

DeskOS is not intended to be just a dashboard or a chatbot. It should gradually become an intelligent personal workstation companion capable of monitoring system health, managing reminders, responding to voice commands, understanding desk activity, and performing useful tasks without relying on cloud services.

Treat this as a serious, long-term software engineering project with maintainable architecture, documented decisions, incremental releases, and production-quality implementation practices.

---

## 2. Existing Hardware and Development Environment

### Development laptop

- Device: Dell Vostro 3405.
- Operating system: Ubuntu Linux with GNOME, running an X11 session.
- Display: External HDMI monitor, 1920 × 1080, used as the primary display.
- Role: Current development machine, system-monitoring host, and local service provider.
- Environment: Python and JavaScript-based development workflows are available.

### Android device

- Device: Realme C2.
- Role: Secondary display, potential voice-input client, camera source, and notification device.
- Interaction: Access DeskOS through a browser on the local network.
- Hardware capabilities to explore:
  - Microphone for wake-word detection and voice commands.
  - Camera for locally processed visual input.
  - Vibration and sound for alerts.
  - Available phone sensors, subject to Android/browser support.
  - Full-screen dashboard mode.

The Realme C2 is a low-resource device. Avoid heavyweight native applications, continuous unnecessary camera processing, and demanding browser animations. Prefer a lightweight, mobile-first web interface.

### Future hardware

A Raspberry Pi 4 Model B is planned but has not yet been purchased.

Do not assume that the Raspberry Pi is currently available or that any Pi-specific service has been deployed successfully.

The intended future role of the Pi is to provide an always-on local core, so that reminders, scheduled tasks, the assistant API, and other essential functionality can continue running when the laptop is switched off.

Hardware recommendations and resource requirements must be realistic for a Raspberry Pi 4, especially if the selected model has 4 GB of RAM.

---

## 3. Current Project Status

DeskOS already has an existing implementation. Do not treat this as a greenfield project.

The existing system includes a laptop dashboard and a Realme C2 browser-based interface.

### Implemented or previously tested

- Dashboard and clock.
- Local laptop status monitoring.
- Mobile dashboard access over the local network.
- A lightweight DeskOS Lite implementation.
- Laptop availability/status communication between the phone and laptop.
- Full-screen usage on the phone.
- Initial warning and notification functionality.
- Linux service automation has been explored, including automatic startup and restart.

The laptop's health endpoint has previously responded successfully to local `curl` requests. The phone also successfully displayed the laptop's status after earlier connectivity troubleshooting.

### Known implementation considerations

- Earlier versions have used different ports, including 8767 and 8769. Do not assume which one is currently authoritative.
- Some dashboard metrics have previously been missing.
- CPU, RAM, and temperature monitoring should be implemented with minimal overhead.
- Phone-side alerts should be audible or vibrate when appropriate.
- Acknowledgement dialogs should be easy to use and should close automatically only where that behavior is appropriate.
- Existing working features must not be broken during enhancements.

### Current Raspberry Pi setup issue

Raspberry Pi OS setup and SSH access have been attempted. Password authentication has failed despite reinstalling the operating system and entering the configured password. A remote-host-identification warning has also appeared following the reinstall.

Investigate the actual cause before changing SSH settings. Distinguish between a stale SSH host key, an incorrect username/password, an unconfigured account, and other authentication issues. Do not weaken SSH security or disable host-key checking globally.

The Pi installation and authentication issue should remain a separate workstream from the currently functioning DeskOS laptop and phone application.

---

## 4. Non-Negotiable Architectural Constraints

### A. Offline-first operation

**DeskOS must operate without external network connectivity during normal operation.**

Requirements:

- No cloud APIs for core functionality. An optional Gemini assistant may be used only for explicitly submitted requests after opt-in; it is not core and must fail safely offline.
- No external LLM APIs for local reminders, monitoring, device health, or deterministic local commands. Gemini is an optional, documented exception for the voice/text assistant only, subject to the cloud-data disclosure and fallback requirements below.
- No telemetry or third-party analytics.
- No cloud-based speech recognition.
- No cloud-based image recognition.
- No mandatory account login or internet authentication.
- No runtime downloads of models, packages, or application assets.
- No external DNS dependencies for normal operation.
- No internet connection required for local reminders, monitoring, or assistant commands.

Distinguish **local core operation** from **cloud-assisted natural-language interpretation**. If Gemini is disabled, offline, out of quota, or fails, local reminders/monitoring remain available; only the flexible Gemini interpretation/response path is unavailable. Never claim the Gemini path itself is offline.

Local communication between trusted DeskOS devices over the home LAN is permitted. Localhost communication is permitted.

When the system is deployed, it must remain useful with the internet disconnected.

Audit all dependencies for hidden network access, including browser assets, CDN-hosted libraries, telemetry, package managers, and model-loading behavior.

Install dependencies and download required models during a separate setup process. Runtime operation must use locally available assets.

### B. Preserve working functionality

Before modifying any source files:

1. Inspect the existing project structure.
2. Read the README and existing documentation.
3. Identify the actual frontend, backend, routes, ports, and service configuration.
4. Identify the current health endpoint and dashboard polling mechanism.
5. Establish a baseline of the working laptop and phone interfaces.
6. Identify existing defects and distinguish them from proposed improvements.

Do not replace the entire application just because a cleaner architecture is possible.

Prefer small, reversible changes that preserve existing behavior.

### C. Lightweight resource consumption

The application must remain practical on the existing laptop and future Raspberry Pi hardware.

- Avoid unnecessary background loops.
- Avoid repeatedly running expensive shell commands.
- Cache system metrics where appropriate.
- Use sensible polling intervals.
- Do not run continuous inference without a concrete need.
- Use bounded queues and resource-aware scheduling.
- Monitor memory usage, CPU consumption, and disk activity during development.

Start with simple, reliable implementations before introducing complex infrastructure.

### D. Privacy and security

- Keep processing local.
- Never hardcode passwords, tokens, or private keys.
- Keep secrets outside source control.
- Validate API inputs.
- Apply authentication to sensitive administrative actions.
- Avoid exposing the assistant API to the public internet.
- Restrict camera and microphone activation to explicit, documented conditions.
- Make camera, microphone, and sensor activity visible to the user.
- Do not store raw audio or video by default.
- Provide explicit retention and deletion policies for any saved personal data.

Friend recognition and other identity-related features must be opt-in and locally processed.

---

## 5. Product Vision

DeskOS should evolve into six connected subsystems.

### Subsystem 1: DeskOS Dashboard

The dashboard provides an at-a-glance view of the workstation and assistant.

Required capabilities:

- Live clock and date.
- Laptop online/offline status.
- CPU and RAM usage.
- CPU temperature when supported.
- Disk space and basic storage health.
- Network status for local connectivity.
- Active warnings and notification history.
- Assistant status and wake-word availability.
- Reminder overview.
- Future Pi and connected-device status.

The dashboard should have a polished, modern interface suitable for a dedicated desk display.

Prioritize clear information hierarchy, restrained animations, responsive layouts, accessible contrast, and low rendering overhead.

Do not invent metrics when a source is unavailable. Clearly distinguish unsupported, unavailable, stale, and genuinely zero-valued measurements.

### Subsystem 2: Voice Assistant (local capture, optional Gemini cloud reasoning)

The optional future wake phrase is:

**"Hello Desk"**

The first voice MVP starts from a user-pressed push-to-talk control; local wake-word detection is a later optional capability, not required for the initial release. A small on-device wake-word detector is distinct from a generative LLM and is technically possible, but continuous microphone access from a browser/PWA is not reliable when Android backgrounds or suspends the page. Dependable screen-off listening may require a native Android app, microphone foreground service, persistent notification, permissions, and battery-management setup; verify feasibility and battery cost on the actual Realme C2 before committing to that work.

The planned hybrid experience should support:

1. Either user-started push-to-talk in the initial MVP, or (later, opt-in) locally detecting the wake phrase.
2. Capturing a single voice command after the explicit trigger.
3. Converting speech into text on the phone/device where on-device recognition is verified; do not assume browser recognition is local.
4. Showing the transcript to the user and sending it to Gemini only after explicit cloud-assistant opt-in and user submission.
5. Receiving a constrained intent/tool proposal from Gemini.
6. Validating and executing an approved action in the local DeskOS backend.
7. Sending only the minimum relevant tool result back to Gemini for a concise reply if the user has opted in to result sharing; otherwise format the result locally.
8. Speaking the response with the phone/browser's available on-device text-to-speech, if verified, or displaying it as text.
9. Returning to idle; microphone capture stops after each utterance. Always-on wake listening remains off unless separately enabled and verified.

Initial commands should include:

- "What time is it?"
- "How is my laptop doing?"
- "Create a reminder."
- "Show my reminders."
- "Cancel my reminder."
- "Is my laptop online?"
- "Show today's productivity summary."
- "Stop listening."

The initial version should prioritize a reliable, user-confirmed command pipeline rather than a fully autonomous, unrestricted agent. Use push-to-talk first; do not run an always-listening wake-word service until its local processing, battery, and privacy behavior are verified on the Realme C2.

Speech recognition, wake-word detection, command interpretation, and text-to-speech are separate components and must be evaluated separately. Do not assume that browser speech recognition is on-device, or that one model can perform every function efficiently on a Raspberry Pi 4. The chosen direction is to avoid a local LLM on the current laptop/Pi-class hardware for now; Gemini is an optional cloud interpreter, while local wake detection (if later enabled), speech capture/transcription, and device speech output must be verified independently. If truly local speech transcription is not supported at adequate quality on the phone, keep push-to-talk text entry as the fallback instead of silently using cloud transcription. If always-on detection cannot pass the Realme C2 battery, privacy, and background-operation checks, retain push-to-talk only.

Benchmark candidate models on the actual target hardware before committing to a model architecture.

### Subsystem 3: Reminders and Notifications

Reminders must be persistent and independent of the browser being open.

Required capabilities:

- Create, list, edit, complete, and delete reminders.
- Support absolute times and recurring schedules.
- Persist reminders in a local database.
- Survive service restarts and power interruptions.
- Dispatch due notifications through available local devices.
- Record delivery and acknowledgement states.
- Handle missed reminders after downtime according to an explicit policy.
- Prevent duplicate notifications after service restarts.

The Android dashboard should be able to display notifications and, where browser permissions and device support permit, vibrate or play a local alert sound.

Use an appropriate acknowledgement dialog with a clear confirmation action and optional automatic dismissal. Critical warnings must not disappear without acknowledgement merely because a timer elapsed.

Do not assume that browser notifications, audio playback, or vibration work in every background state on Android. Test the Realme C2's actual behavior and document limitations.

### Subsystem 4: System Monitoring

Collect useful workstation metrics through a lightweight local monitoring service.

Potential data points:

- CPU utilization.
- Memory utilization.
- CPU temperature.
- Disk capacity and selected health indicators.
- System uptime.
- Laptop reachability.
- Service health.
- Recent warnings.

Use supported Linux interfaces or established lightweight libraries.

Avoid parsing unstable command output when a dependable system interface is available.

Establish sensible thresholds and make them configurable. Alerts should have cooldowns, hysteresis, and deduplication to prevent repeated notifications.

When the laptop is off, the future Pi-based core must continue to work. It should represent the laptop as offline rather than incorrectly declaring the entire DeskOS system unavailable.

### Subsystem 5: Desk Awareness

Explore optional awareness features using the Realme C2 camera and available sensors.

Potential capabilities:

- Detect whether someone is present at the desk.
- Estimate desk usage sessions.
- Track broad activity patterns.
- Recognize an explicitly enrolled person, if technically feasible and appropriate.
- Produce local productivity summaries.
- Support presence-aware display behavior.

Implement these features in stages.

Start with low-cost presence detection or a manual presence toggle. Add more sophisticated visual analysis only after evaluating accuracy, privacy, performance, and battery usage.

Do not equate screen activity with productivity. Present derived metrics as estimates, explain how they are calculated, and avoid unsupported conclusions about people.

### Subsystem 6: Controlled Assistant Intelligence (Gemini-assisted, local execution)

The assistant should understand natural-language commands and coordinate local tools. The current candidate is the Gemini API for interpretation and optional response phrasing; this deliberately makes the natural-language assistant dependent on internet access and a third-party service. Core monitoring, reminders, deterministic commands, and safety checks must remain local and usable if Gemini is unavailable.

Its capabilities should be exposed through a controlled tool interface, such as:

- `get_system_status`
- `get_device_status`
- `create_reminder`
- `list_reminders`
- `cancel_reminder`
- `get_productivity_summary`
- `get_recent_alerts`

The model must not receive unrestricted shell access. It returns an intent or function-call proposal only; the DeskOS backend remains the sole authority that validates and executes local operations.

Use explicit tool schemas, argument validation, permission checks, execution timeouts, and auditable action results. Keep Gemini behind an explicit opt-in and provider adapter. On the unpaid tier, prompts and responses may be used to improve Google products and may be reviewed; therefore never send audio, camera data, credentials, full metric snapshots, or complete reminder lists. Sending user transcripts and even minimal action results to a third party requires a clear disclosure and explicit opt-in. Sensitive or non-consented requests must use deterministic local routing or fail to text/manual handling.

Do not add a locally hosted LLM at this stage. Retain the deterministic router as an offline fallback and use Gemini only for natural-language interpretation of explicitly submitted transcripts, subject to the separate privacy, quota, eligibility, and rate-limit gates in docs/gemini-assistant-plan.md.

---

## 6. Target Architecture

Use this as the intended direction, not as an excuse to rewrite the existing code before inspecting it.

```text
                  REALME C2
          ┌──────────────────────┐
          │ Mobile DeskOS UI     │
          │ Microphone / Camera  │
          │ Alerts / Vibration   │
          └──────────┬───────────┘
                     │
               Local Network
                     │
          ┌──────────▼───────────┐
          │ Raspberry Pi 4       │
          │ Future Always-on Core│
          ├──────────────────────┤
          │ Local API            │
          │ Reminder Scheduler   │
          │ SQLite Database      │
          │ Notification Router  │
          │ Command Dispatcher   │
          │ Local Assistant      │
          └──────────┬───────────┘
                     │
               Local Network
                     │
          ┌──────────▼───────────┐
          │ Dell Ubuntu Laptop   │
          ├──────────────────────┤
          │ System Monitor       │
          │ DeskOS Dashboard     │
          │ Development Services │
          │ Optional Local AI    │
          └──────────────────────┘
```

The laptop, phone, and Pi should have distinct responsibilities.

The phone is primarily an interface and sensor client. The laptop is the monitored workstation and current development host. The Pi is the planned always-on coordinator.

The system must continue to provide useful functionality if any one device is unavailable.

For example:

- Laptop unavailable: reminders and core services can continue on the Pi.
- Phone unavailable: scheduled tasks continue; phone-specific alerts wait until the client reconnects or use another supported local channel.
- Pi unavailable: clearly report degraded functionality rather than silently losing data or pretending that services are healthy.

Design graceful degradation explicitly.

### API design

Prefer a small, documented API with:

- Health checks.
- Device status endpoints.
- Reminder CRUD endpoints.
- Notification delivery and acknowledgement endpoints.
- Assistant command endpoints.
- Basic event history.

Use HTTP for straightforward request/response operations. Introduce WebSockets or server-sent events only when real-time behavior justifies the additional complexity.

Use explicit API versioning when compatibility requirements emerge.

### Data storage

SQLite is the default candidate for local persistent data.

Potential tables:

- `devices`
- `reminders`
- `notifications`
- `system_metrics`
- `activity_sessions`
- `assistant_actions`
- `settings`

Use timestamps consistently, store scheduled instants in UTC where appropriate, and handle the local timezone explicitly.

Avoid unnecessary data collection. Retain high-frequency system metrics for a limited configurable period rather than allowing the database to grow indefinitely.

---

## 7. Technology Selection Policy

Do not impose a new technology stack until the existing repository has been inspected.

Preferred characteristics:

- Lightweight Linux-compatible backend.
- Simple browser-based frontend.
- SQLite for initial persistent storage.
- Linux service management using systemd.
- Local network APIs.
- On-device speech recognition and text-to-speech only if verified on the Realme C2; optional Gemini API for natural-language command interpretation after explicit consent and privacy review.
- Automated tests and straightforward deployment scripts.

Python is a reasonable candidate for hardware monitoring, scheduling, and local AI integration. JavaScript or TypeScript may remain appropriate for an existing Node.js or Bun.js backend.

Reuse working components where possible. Avoid running multiple backend runtimes unless there is a clear architectural benefit.

Do not introduce Kubernetes, distributed message brokers, large databases, or other operationally expensive infrastructure without demonstrated requirements.

Every new dependency must have a clear purpose, installation instructions, and a documented offline runtime strategy.

---

## 8. Development Roadmap

Work in milestones. Each milestone must leave the application in a usable state.

### Phase 0 — Repository audit and baseline

Objectives:

- Inspect the full project structure.
- Identify the active entry points, ports, environment variables, and service files.
- Trace the existing phone-to-laptop health-check flow.
- Identify working features, known defects, and duplicated implementations.
- Review dependency manifests and existing documentation.
- Establish a reproducible startup and testing procedure.
- Identify all runtime network requests and potential cloud dependencies.

Deliverables:

1. Architecture overview.
2. Existing feature inventory.
3. Dependency and network audit.
4. Known issues and risk register.
5. Recommended implementation plan.
6. Baseline test results.

**Do not start a broad rewrite during this phase.**

### Phase 1 — Stabilize DeskOS Lite

Objectives:

- Preserve the existing dashboard.
- Verify the actual health endpoint and port.
- Resolve any remaining metric gaps.
- Verify phone access over the local network.
- Implement robust offline/stale-data handling.
- Confirm lightweight polling and caching.
- Validate sound, vibration, and acknowledgement behavior.
- Add or improve automated tests.

Acceptance criteria:

- The dashboard works on the laptop and Realme C2.
- Missing data is represented accurately.
- The system distinguishes a failed laptop connection from a failed DeskOS core.
- Alerts do not duplicate continuously.
- The application continues to work with internet access disabled.

### Phase 2 — Reliable local services

Objectives:

- Make the current service start automatically on boot.
- Configure restart behavior and meaningful logs.
- Add a lightweight health check.
- Handle graceful shutdown and recovery.
- Keep configuration outside application source code.
- Document installation, upgrades, and rollback.

Acceptance criteria:

- A reboot does not require manually starting the application.
- Service failures are observable.
- Restarting the service does not corrupt persistent state.
- The installation is reproducible.

### Phase 3 — Persistent reminders and notifications

Objectives:

- Introduce a local database.
- Implement reminder CRUD.
- Build a reliable scheduler.
- Add delivery, acknowledgement, and retry policies.
- Integrate the phone's notification interface.

Acceptance criteria:

- Reminders survive restarts.
- Due reminders are not silently lost.
- Duplicate delivery is controlled.
- Missed reminders have a defined recovery policy.
- Notification behavior is tested on the actual phone.

### Phase 4 — Hybrid voice assistant MVP (local speech I/O, optional Gemini)

Objectives:

- Start with push-to-talk; do not begin always-on wake-word detection.
- Treat “Hello Desk” wake-word detection as a later optional milestone: first use push-to-talk, then benchmark a lightweight local wake detector on the Realme C2. A browser page may not stay active with the screen off; reliable background wake may require a native Android foreground service with a persistent notification and extra permissions.
- Verify whether the Realme C2/browser can transcribe speech on-device and use on-device TTS. Document browser/Android requirements and test suspended/background behavior. Do not silently substitute cloud speech recognition.
- Show the transcript for review/edit before any Gemini request.
- Add a Gemini provider adapter for intent classification/structured tool proposals, disabled by default until the terms, supported region, privacy/consent, quota, and free-tier data-use gates are accepted.
- Keep deterministic local intent routing as a fallback and as the route for sensitive or unconsented requests.
- Validate Gemini's proposed tool name/arguments against the fixed local allowlist and existing business rules; execute tools only in the local backend.
- After execution, prefer local response templates. If Gemini response phrasing is enabled, send only the minimum necessary result and require separate consent for that data flow.
- Speak responses using verified local/device TTS; otherwise show text. Never send audio to Gemini as part of this MVP.
- Add listening state, microphone indicator, cloud-provider indicator, and explicit stop/cancel controls.

Acceptance criteria:

- Local reminders, monitoring, deterministic commands, and text UI continue to work with internet disconnected or Gemini disabled.
- No audio leaves the phone; transcript sharing is visibly disclosed and requires opt-in plus an explicit send action.
- The system validates all proposed tool calls; cancellation still requires user confirmation; no shell/arbitrary tool access exists.
- Local speech recognition/TTS claims are confirmed on the actual Realme C2. Unsupported device speech behavior falls back to typed text/visible response.
- Gemini quota exhaustion, 429, timeout, invalid key, provider outage, malformed output, and unsupported intents fail safely and preserve local functionality.
- Unpaid/free-tier API evaluation uses synthetic or otherwise non-sensitive phrases only. Real voice transcripts, reminder titles, and status data are sent only if the provider tier, terms, and explicit user consent are acceptable; otherwise use local deterministic routing or text/manual fallback.
- Latency, request count, memory/resource use, and accuracy are measured with synthetic test phrases; model/provider and quota are configurable, not assumed fixed.
- The assistant can be stopped immediately and is not continuously listening.

Wake-word acceptance criteria, if that optional feature proceeds:

- Wake-word audio processing remains on-device and raw audio is not retained or uploaded.
- Listening is opt-in, visibly indicated, and can be stopped immediately.
- False-trigger/missed-trigger rates, battery use, device heat, and screen-off/background behavior are measured on the actual phone.
- If the browser/PWA cannot reliably support the required background behavior, either scope a separate native Android foreground-service client or keep push-to-talk; do not claim always-on support that has not been verified.

### Phase 5 — Raspberry Pi deployment

Begin when the Pi is actually available.

Objectives:

- Install a suitable 64-bit Raspberry Pi OS Lite configuration.
- Establish secure SSH access.
- Deploy the always-on services.
- Configure stable power, cooling, storage, and automatic startup.
- Move persistent reminders and other appropriate core services to the Pi.
- Configure local device discovery or stable local addressing.
- Verify laptop and phone reconnection after downtime.

Acceptance criteria:

- Core reminders work with the laptop powered off.
- The Pi boots into the expected service state.
- Device health remains accurate during disconnects.
- Essential functionality requires no external internet access.

Do not assume that a Raspberry Pi 4 can run a large language model quickly. Benchmark memory, latency, and thermal behavior before selecting local inference workloads.

### Phase 6 — Desk awareness and productivity

Objectives:

- Implement optional presence detection.
- Record explicit activity sessions.
- Develop local summaries and dashboard visualizations.
- Evaluate camera-based features separately.
- Add retention and deletion controls.

Acceptance criteria:

- All collected data has a defined purpose.
- Features can be disabled.
- Activity estimates are clearly labeled.
- No raw video is retained by default.
- The application remains responsive on the existing hardware.

### Phase 7 — Assistant orchestration hardening (no local LLM planned)

Objectives:

- Harden the structured local tool interface used by both deterministic routing and the Gemini adapter.
- Improve natural-language routing using Gemini only if phase 4 privacy, terms, quota, and performance gates pass; otherwise retain deterministic local routing.
- Do not add a local LLM unless hardware changes materially and a new benchmark justifies it.
- Enforce tool permissions, strict schemas, confirmation, timeouts, and execution boundaries independently of model output.
- Add privacy-preserving action outcomes, provider error handling, and recovery behavior; do not retain prompts/responses by default.

Acceptance criteria:

- All actions are validated before execution.
- The assistant cannot bypass permissions through model-generated text.
- Critical operations require confirmation where appropriate.
- Core functionality remains available without an AI model.
- Local tool execution remains local. Gemini inference is the explicitly disclosed cloud exception; with Gemini disabled or unreachable, core operation and deterministic assistant behavior remain local.

---

## 9. Engineering Standards

Operate as a senior software engineer responsible for long-term maintainability, not as a code generator optimizing for the number of files produced.

### Code quality

- Use clear module boundaries.
- Prefer small, cohesive functions.
- Apply type checking where supported.
- Validate configuration at startup.
- Handle errors explicitly.
- Use structured logging where practical.
- Avoid duplicated business logic.
- Document non-obvious design decisions.
- Keep configuration separate from application code.

### Reliability

- Use timeouts for network requests and subprocesses.
- Avoid unbounded queues and unbounded in-memory histories.
- Implement retries with limits and backoff where appropriate.
- Make scheduled operations idempotent where possible.
- Protect against duplicate event processing.
- Handle unavailable devices and stale data explicitly.
- Preserve persistent data across normal upgrades.

### Testing

Add automated tests for:

- Health endpoints.
- Device availability transitions.
- Reminder creation and scheduling.
- Duplicate notification prevention.
- Database persistence.
- Restart recovery.
- Invalid API inputs.
- Network timeouts.
- Offline behavior.
- Permission checks for assistant tools.

Separate unit tests from hardware integration tests. Do not claim that a camera, microphone, vibration motor, or Raspberry Pi integration has been verified unless it was actually tested.

### Documentation

Maintain:

- `README.md`
- `docs/architecture.md`
- `docs/development.md`
- `docs/deployment.md`
- `docs/security.md`
- `docs/decisions/` for significant architectural decisions, when useful.

Keep documentation aligned with the actual implementation.

---

## 10. Operating Instructions for the Coding Agent

You are the principal engineer for DeskOS.

Your responsibility is to investigate, design, implement, validate, and document changes through an iterative engineering process.

### Mandatory workflow

For every development task:

1. **Inspect:** Read the relevant source files and configuration before proposing changes.
2. **Understand:** Trace how the feature currently works, including its callers, dependencies, and runtime behavior.
3. **Diagnose:** Reproduce the issue or establish the baseline wherever possible.
4. **Design:** Propose the smallest viable change and identify risks.
5. **Implement:** Modify the existing code while preserving unrelated functionality.
6. **Test:** Run relevant automated tests and practical checks.
7. **Review:** Check for regressions, security issues, resource overhead, and external network dependencies.
8. **Document:** Update the relevant documentation and setup instructions.
9. **Report:** Summarize changes, files affected, test results, unresolved issues, and the next recommended step.

### Rules for repository modifications

- Never delete or replace a working subsystem without explaining why and obtaining approval for a material architectural change.
- Do not invent filenames, ports, API routes, environment variables, or installed packages. Inspect the repository first.
- Do not assume that a previous implementation is still running.
- Do not overwrite configuration or database files without protecting existing data.
- Do not install system packages or change system security settings without explaining the impact.
- Do not perform destructive operations without explicit approval.
- Do not hide test failures or report unexecuted tests as passing.
- Do not introduce a new framework merely to simplify the current task.
- Do not use internet services for a feature that is required to operate offline.
- If essential hardware is unavailable, develop a testable interface or simulation and clearly label it as unverified on real hardware.

### Communication style

Be technically thorough and direct.

When investigating a defect, explain:

- The observed behavior.
- The likely cause and supporting evidence.
- The proposed fix.
- The exact files that require modification.
- How the change will be validated.

When several implementation approaches exist, compare their trade-offs and recommend one.

Do not repeatedly ask questions that can be answered by inspecting the repository. Ask only when a decision genuinely requires my input.

---

## 11. Definition of Done

A feature is not complete merely because the code compiles.

It is complete when:

- Its intended behavior is implemented.
- Relevant tests pass.
- Errors and edge cases are handled.
- It works within the offline operating policy.
- Resource usage is appropriate for the target hardware.
- Existing functionality remains intact.
- Security implications have been reviewed.
- Documentation is updated.
- Any unverified assumptions are disclosed.

---

## 12. Immediate Assignment

Start with **Phase 0: Repository Audit and Baseline**.

Do not implement the entire roadmap in one operation.

First, inspect the current DeskOS repository and produce:

1. A concise description of the existing architecture.
2. A directory and component map.
3. The actual frontend and backend entry points.
4. The actual active port and health endpoint.
5. A trace of how the Realme C2 communicates with the laptop.
6. An inventory of existing monitoring, alert, and notification features.
7. A list of dependencies that could require external connectivity.
8. A list of known defects, technical debt, and security concerns.
9. A prioritized implementation plan for the next three milestones.
10. The exact commands needed to run, test, and debug the existing project.

If the repository is available, inspect it directly. If it is not, request the project directory or a ZIP archive with secrets removed.

**Do not guess at the existing implementation. Do not start with a rewrite. Establish the facts, protect the working baseline, and then develop DeskOS incrementally.**

The long-term outcome should be a dependable personal assistant that remains useful when the laptop is switched off, the phone disconnects, or the internet becomes unavailable—all while remaining private, lightweight, and maintainable.