# Product Requirement Document (PRD)

## Feature
Anonymous Telemetry & Crash Reporting

## Summary
To continually improve the framework, monitor user adoption, track stability, and audit potential commercial licensing violations, the `aio-sdlc` CLI requires a lightweight telemetry module. This feature will securely "phone home" with anonymized usage metrics and crash reports while ensuring sensitive codebase data remains strictly local.

## User Stories
- As a product owner, I want to see aggregate usage metrics and IP distributions so I can track adoption trends across different companies and identify potential commercial license violators.
- As the framework maintainer, I want to receive automated crash reports and stack traces when the CLI fails, allowing me to proactively fix bugs without waiting for users to submit issues.
- As a privacy-conscious user, I want a clear and documented way to opt-out of telemetry so my local execution data remains entirely private.

## Requirements
- **Zero-Infra Telemetry Provider**: The system MUST utilize a managed, serverless SaaS provider (e.g., the free tier of PostHog or Sentry). The implementation MUST NOT require deploying or maintaining a custom backend server.
- **Data Collection Scope**: The telemetry payload MUST be limited to:
  - CLI commands executed (e.g., `plan`, `apply`, `daemon start`).
  - Environment metadata (OS type, CPU architecture, CLI version).
  - A persistently generated, anonymized Machine ID (e.g., a UUID stored in the local config).
  - Stack traces for unhandled exceptions and Orchestrator crash logs.
- **Licensing Audit Trail**: The backend receiving the telemetry MUST implicitly capture the public IP address of the request to aid in auditing corporate domain usage.
- **Opt-Out Mechanism**: The framework MUST respect standard opt-out practices. It MUST disable all outgoing telemetry if the `telemetry: false` flag is set in `.aio-agentic-sdlc/config.json` or if the `AIO_SDLC_DO_NOT_TRACK=1` environment variable is present.

## Out of Scope
- Uploading any user-generated content, including source code, PRD contents, Intention/Reality DAGs, or LLM prompts. Only metadata and error traces are permitted.

## Acceptance Criteria
1. Executing standard CLI commands emits an anonymized event to the telemetry backend.
2. An unhandled exception or agent crash automatically fires a stack trace report to the backend.
3. Setting the opt-out configuration flag completely silences all network calls to the telemetry server.
