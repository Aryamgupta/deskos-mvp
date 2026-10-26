# DeskOS — Google Workspace Integration & Personal Voice Assistant Roadmap

## 1. Project Context

I am developing DeskOS, a personal, voice-controlled desktop assistant that runs through a dedicated console interface displayed on a Realme C2 smartphone in landscape mode.

The application is currently running on my Ubuntu laptop for development. Once development and testing are complete, the plan is to deploy it on a Raspberry Pi for continuous operation.

The assistant already uses Google's Gemini LLM for natural-language understanding and supports several existing commands.

**Your first responsibility is to understand the existing implementation and design a plan that extends it without unnecessarily replacing or breaking working functionality.**

Do not immediately start coding. First inspect the repository, understand the existing architecture, identify dependencies and integration points, and prepare a detailed implementation plan.

## 2. Existing Technology Stack

The current implementation uses:

- Python for the backend.
- HTML, CSS, and JavaScript for the lightweight frontend.
- Gemini API for natural-language understanding and response generation.
- A database for storing and retrieving existing assistant information, commands, reminders, and metadata as applicable.
- A wake-word-based voice interaction flow.
- Speech-to-text conversion before sending user instructions to Gemini.
- An existing backend action/query processing mechanism.
- A dedicated console interface optimized for the Realme C2 in landscape mode.

Do not assume a particular database engine, web framework, speech recognition library, or database schema. Inspect the repository and establish the actual implementation.

Avoid introducing React, a heavyweight frontend framework, unnecessary microservices, or additional infrastructure unless the existing implementation genuinely requires them.

## 3. Current Voice Processing Pipeline

The existing flow is approximately:

1. The user says the wake phrase, such as "Hello Desk."
2. The assistant activates voice input.
3. The spoken instruction is converted into text.
4. The text is sent to Gemini along with the existing system prompt.
5. Gemini returns a response containing a query, intent-related information, or metadata used by the application.
6. The Python backend processes the returned information and executes the appropriate existing operation, including database interactions.
7. The result is presented through the frontend and/or voice response mechanism.

The assistant already supports commands such as:

- Activating ambient mode.
- Resting or entering a low-activity mode for the day.
- Reporting laptop status.
- Creating or managing reminders through the existing mechanism.
- Other existing DeskOS commands discovered during repository inspection.

Treat this pipeline as an existing system to extend, not a system to rebuild.

Preserve the existing command behavior, response format, wake-word handling, speech recognition, and console functionality wherever possible.

## 4. Primary Objective

Extend DeskOS into a personal productivity assistant that can interact with my personal Google account through official Google APIs.

The intended integrations are:

1. Google Calendar API.
2. Gmail API.
3. Google Docs API.
4. A local reminder and scheduling engine that continues to operate independently of temporary Google service failures.

The integration must work with the existing Gemini-based assistant and Python backend.

The project should remain free for personal use wherever possible. Prefer official APIs, free tools, the existing hardware, and minimal dependencies. Do not introduce paid infrastructure or subscriptions without identifying the need and obtaining approval.

The initial implementation will be online. Fully offline LLM inference is not required.

## 5. Phase 0 — Repository Audit and Planning

Before writing code, inspect the repository and document:

- Current directory structure and important files.
- Backend entry point and framework.
- Gemini API integration and system prompt.
- Gemini response schema, including the query and metadata fields.
- Existing command routing and database execution flow.
- Database engine, schema, migrations, and reminder storage.
- Speech-to-text and wake-word implementation.
- Text-to-speech or voice-response mechanism, if present.
- Existing scheduler, background services, and notification implementation.
- HTML console architecture and frontend-to-backend communication.
- Configuration files, environment variables, dependencies, and startup scripts.
- Existing tests and known architectural constraints.
- Raspberry Pi deployment requirements and compatibility risks.

Identify the best extension points for the new integrations.

Produce a proposed architecture, a phased task breakdown, a dependency list, a security plan, and a testing strategy.

Identify any assumptions that need my approval before implementation.

Do not expose existing secrets while inspecting configuration files or generating reports.

**Deliverable:** A repository-specific implementation plan with file-level recommendations, dependency choices, API scopes, acceptance criteria, and a list of questions requiring clarification.

Wait for my approval before making substantial code changes.

## 6. Phase 1 — Google Cloud and OAuth Setup

Plan a secure integration with my personal Google account.

Required setup:

- Create or select a Google Cloud project.
- Enable Calendar API, Gmail API, and, when needed, Google Docs API.
- Configure the OAuth consent screen and appropriate testing or production access.
- Register an appropriate OAuth client for the application architecture.
- Implement the authorization flow suitable for a locally hosted Python backend that will later run on a Raspberry Pi.
- Request offline access when appropriate so the application can refresh access tokens without requiring interactive login for every API call.
- Securely store credentials and refresh tokens.
- Handle token expiration, revoked access, failed authorization, and reconnection.
- Document any account-specific verification, quota, or billing requirements.

Prefer the narrowest Google OAuth scopes that support the required features.

Start with read-only Calendar access if that helps validate the integration before enabling write access.

Never place OAuth client secrets, refresh tokens, access tokens, or private credentials in frontend JavaScript, Git repositories, application logs, or public documentation.

Personal-use operation must not depend on a paid hosting service.

**Deliverable:** An OAuth setup guide and an implementation design that explains the authorization flow, token storage, refresh strategy, and required permissions.

## 7. Phase 2 — Google Calendar Integration

Integrate Calendar functionality into the existing assistant.

### Required initial capabilities

1. Retrieve today's events.
2. Retrieve upcoming events for a configurable period.
3. Create a calendar event or reminder.
4. Retrieve event details.
5. Update an existing event.
6. Delete an event only after explicit confirmation.
7. Handle all-day events and timed events correctly.
8. Configure appropriate event notifications where supported.
9. Handle ambiguous dates and times by asking the user for clarification.
10. Prevent duplicate events during retries.

### Example voice commands

- "Hello Desk, what meetings do I have today?"
- "Create a reminder for tomorrow to call Risha."
- "Schedule a meeting for Friday at 3 PM."
- "What is my next meeting?"
- "Move my next meeting to 4 PM."
- "Cancel the meeting I created for tomorrow."

The assistant must distinguish between a personal reminder, a calendar event, and a task when their semantics differ.

Use the Asia/Kolkata timezone for date interpretation unless the existing configuration specifies otherwise.

Relative expressions such as "tomorrow," "next Friday," and "in two hours" must be resolved consistently. If the user does not specify a time, do not silently invent an arbitrary meeting time.

For reminders without a specified time, ask whether the user wants an all-day reminder or a specific notification time, unless the existing product design already defines an appropriate default.

Calendar modifications must be validated before execution.

### Suggested service boundaries

Evaluate whether the existing architecture supports equivalent functions to:

- `get_today_events`
- `get_upcoming_events`
- `create_calendar_event`
- `update_calendar_event`
- `delete_calendar_event`

These are suggested interfaces, not mandatory names. Follow existing project conventions.

**Deliverable:** A tested Calendar integration with clear error handling, appropriate confirmations, and a documented voice-command mapping.

## 8. Phase 3 — Gmail Integration

Integrate Gmail through the official Gmail API.

Implement the features incrementally.

### Initial features

1. Search for emails by sender, subject, date, and relevant query criteria.
2. Retrieve the minimum message content needed to answer a request.
3. Summarize selected emails using Gemini.
4. Create email drafts.
5. Retrieve existing drafts when required.
6. Allow the user to review and revise a draft through voice commands.
7. Send an email only after explicit user confirmation.
8. Handle API failures, malformed addresses, missing recipients, and ambiguous requests.

### Example voice commands

- "Hello Desk, check my unread emails."
- "Find the latest email from HR."
- "Summarize the latest email from my manager."
- "Draft an email requesting leave for tomorrow."
- "Reply to that email saying I will attend the meeting."
- "Change the subject of the draft."
- "Read the draft before sending."
- "Send this email."

### Draft and send safety

Drafting and sending must be separate operations.

Before sending, present or speak a confirmation summary containing:

- Recipient.
- Subject.
- A preview or accessible representation of the body.
- Any attachments, if attachment support is added later.

Require a clear confirmation before sending.

A vague response such as "okay" must not be interpreted as approval if the action or draft is unclear.

Do not automatically send emails merely because Gemini generated a complete draft.

Use the least-privilege Gmail permissions that support the chosen features. Evaluate whether draft creation can be implemented without granting broader mailbox access. Request message-reading and sending scopes only when those features are enabled.

Do not transmit an entire mailbox or unnecessary private email content to Gemini. Retrieve only relevant messages and handle sensitive content carefully.

**Deliverable:** A Gmail integration supporting email search, selected-message summaries, draft creation, revision, and explicitly confirmed sending.

## 9. Phase 4 — Google Docs Integration and Daily Summary

Add the ability to save personal notes and daily summaries to Google Docs.

### Desired capabilities

1. Create a dedicated daily log document or an appropriately organized document structure.
2. Create a daily summary on request.
3. Append voice notes to the relevant daily log.
4. Summarize selected calendar events and tasks.
5. Optionally summarize selected email information when authorized.
6. Save a concise, structured report.
7. Avoid generating duplicate entries when a request is retried.
8. Allow the user to preview a summary before saving it when appropriate.

### Example voice commands

- "Hello Desk, create today's summary."
- "Save today's summary to Google Docs."
- "Note that I completed the authentication module today."
- "Add this to my daily journal."
- "What did I accomplish yesterday?"
- "Summarize my meetings and pending tasks for tomorrow."

### Suggested daily summary structure

- Date.
- Important events and meetings.
- Completed tasks.
- Pending tasks.
- Notes captured through voice.
- Relevant email follow-ups.
- Priorities for tomorrow.

Do not invent completed tasks, meeting outcomes, or email facts. Build summaries from actual available records and clearly distinguish generated recommendations from recorded information.

Keep a local copy or source records where appropriate so that a temporary Google API failure does not destroy user-entered information.

Use the Google Docs API for document creation and editing.

**Deliverable:** A working daily-summary workflow with safe document updates, duplicate prevention, and clear failure handling.

## 10. Phase 5 — Reminder Engine and Notifications

Extend the current reminder mechanism rather than creating competing reminder systems.

The reminder engine should distinguish between:

- Local reminders stored in the existing database.
- Reminders represented by Google Calendar events.
- Notification schedules associated with those reminders.
- The synchronization state between DeskOS and Google services.

Plan for the following:

- Persistent scheduling across application restarts.
- Correct timezone handling.
- Reminder status and completion tracking.
- Snooze and dismiss operations.
- Retries and duplicate prevention.
- Recovery after temporary network outages.
- Notifications when the frontend is connected.
- Appropriate behavior when the laptop or Raspberry Pi is unavailable.
- Clear status when a reminder could not be synchronized.

When a reminder is intended to exist in both DeskOS and Calendar, define one source of truth and a reliable synchronization strategy.

Do not assume that creating a Google Calendar event automatically causes the DeskOS console to announce it.

The backend must have a functioning scheduler or another dependable event-delivery mechanism.

The HTML frontend should be able to display an alert, and the existing voice/audio or vibration functionality should be reused if supported.

**Deliverable:** A documented reminder lifecycle and a reliable scheduler that works independently of continuous frontend activity.

## 11. Phase 6 — Gemini Action Routing

Adapt the existing Gemini response mechanism to support multiple action types without breaking current behavior.

The assistant currently produces a query and metadata used by the Python backend. Inspect this contract before proposing changes.

The preferred conceptual structure is a validated action envelope containing:

- Intent or action type.
- Structured parameters.
- Required permissions.
- Confirmation requirements.
- Execution status.
- User-facing response.

For example, a Calendar request should route to a Calendar service, while an existing laptop-status request should continue through the existing status logic.

Potential action categories include:

- Existing database operations.
- Laptop status.
- Ambient mode.
- Rest mode.
- Local reminders.
- Calendar operations.
- Gmail operations.
- Google Docs operations.

Do not allow model-generated SQL, arbitrary shell commands, or unrestricted API requests to bypass existing security controls.

If the current implementation executes Gemini-generated database queries directly, assess the security and reliability implications and propose a safer migration strategy that preserves current functionality.

Use explicit allowlisted action handlers, parameter validation, authorization checks, and structured results.

If supported by the existing Gemini SDK and model, evaluate native function calling as an alternative to the current free-form query mechanism. Do not change the model or API integration unnecessarily.

**Deliverable:** An extensible action-routing design and a migration strategy compatible with existing DeskOS commands.

## 12. Phase 7 — HTML Console Integration

Preserve the lightweight HTML/CSS/JavaScript frontend.

Do not introduce a frontend framework merely to support Google APIs.

The console should support:

- Google account connection status.
- Calendar synchronization status.
- Gmail availability status.
- Upcoming events.
- Pending reminders.
- Draft review and send confirmation.
- Error and retry notifications.
- A daily summary action.
- Clear visual feedback when a request is awaiting confirmation.

Maintain the existing landscape-oriented, machine-console experience. Avoid unnecessary mobile-style scrolling and do not overload the interface with too many controls.

Voice interaction should remain the primary control mechanism. Visual controls are a complementary fallback.

The frontend must never receive Google refresh tokens or privileged API credentials.

**Deliverable:** A console design and implementation plan consistent with the existing UI.

## 13. Phase 8 — Testing and Raspberry Pi Deployment

Test all integrations on the existing Ubuntu laptop before moving them to the Raspberry Pi.

The test plan should include:

- Correct recognition and routing of voice commands.
- Date and timezone interpretation.
- Successful and unsuccessful OAuth authorization.
- Token refresh and revocation.
- Calendar read, create, update, and delete workflows.
- Gmail search and draft creation.
- Draft revision and confirmed sending.
- Google Docs creation and updates.
- Duplicate prevention.
- Network interruption and recovery.
- API rate limits and quota errors.
- Invalid or incomplete user instructions.
- Existing command regression tests.
- Application restart and reminder persistence.
- Memory and CPU usage on the Raspberry Pi.
- Startup automation and service recovery.

Never use real email sending or destructive Calendar operations in tests without explicit authorization. Prefer test fixtures, mock services, or controlled test records.

For Raspberry Pi deployment, plan:

- A persistent backend service.
- Secure configuration and token storage.
- Restart behavior.
- Logs with secrets and private content redacted.
- Local database persistence.
- A reliable scheduler.
- Network recovery.
- A documented backup and recovery process.

Do not make the Raspberry Pi deployment dependent on a continuously running development laptop.

**Deliverable:** A laptop-tested release candidate, a Raspberry Pi deployment checklist, and measured resource usage.

## 14. Cost and Dependency Constraints

The project should have no additional mandatory recurring cost.

Prioritize:

- Official Google APIs.
- Existing hardware.
- The current Gemini integration.
- Free and open-source Python packages.
- Local storage and scheduling.
- Existing frontend technologies.

Do not assume that every Google API, Gemini model, or account configuration will remain free indefinitely. Check current quotas, applicable free-tier restrictions, OAuth requirements, and billing policies before implementation.

Avoid paid hosting, paid schedulers, third-party automation platforms, or new subscriptions unless there is a clear technical requirement and I approve it.

Do not add a database, queue, framework, or service that duplicates an existing capability without a demonstrated need.

## 15. Required Planning Output

After inspecting the repository, produce a plan with the following sections:

1. Current architecture and confirmed implementation details.
2. Existing functionality that must remain unchanged.
3. Recommended target architecture.
4. Proposed action-routing contract and compatibility strategy.
5. Google Cloud setup and OAuth scopes.
6. Required Python dependencies and justification.
7. File-by-file changes proposed for each phase.
8. Database changes and migration requirements.
9. Error handling, security, and confirmation rules.
10. Testing strategy and acceptance criteria.
11. Raspberry Pi deployment considerations.
12. Expected resource usage and cost considerations.
13. Risks, unknowns, and decisions requiring my input.
14. A prioritized implementation sequence with dependencies between tasks.

For every phase, include:

- Objective.
- Prerequisites.
- Proposed changes.
- Files likely to change.
- Acceptance criteria.
- Test cases.
- Risks and rollback strategy.

Separate confirmed repository facts from assumptions and recommendations.

Do not invent files, functions, database tables, or existing capabilities. Inspect the code and reference actual paths wherever possible.

## 16. Execution Rules

For this initial task:

- Inspect and understand the repository.
- Do not delete or replace existing functionality.
- Do not perform broad refactoring.
- Do not modify the existing Gemini prompt or response schema without explaining the compatibility implications.
- Do not create or use Google credentials without my authorization.
- Do not send real emails or modify my personal Calendar during planning.
- Do not expose secrets in your output.
- Do not begin substantial implementation until I approve the plan.

The immediate goal is to produce a repository-specific technical plan, not to generate a generic architecture or start coding prematurely.

Once I approve the plan, implement it incrementally, beginning with the smallest useful Calendar integration, followed by Gmail drafts, Google Docs summaries, and reminder synchronization.

**Success criterion:** DeskOS becomes a reliable, secure, low-cost personal voice assistant that retains all existing functionality while adding Google Workspace capabilities through a clean, testable, and Raspberry Pi-compatible architecture.