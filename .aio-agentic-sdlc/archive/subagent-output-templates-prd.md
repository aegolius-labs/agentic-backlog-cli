# Product Requirement Document (PRD)

## Feature
Subagent Output Templates

## Summary
Define structured reporting templates for each subagent. This enables the Orchestrator to compile a clean, human-readable summary of the entire parallel session, providing users with a clear and concise overview of all completed work.

## User Stories
- As a user, I want a standardized, easy-to-read summary of what each agent accomplished during a run, so I can quickly understand the system's output.
- As a system orchestrator, I need subagents to provide their results in a predictable structure so I can aggregate them efficiently.

## Requirements
- **Standardized Schema**: Define a standard JSON/YAML schema or Markdown template for subagent execution outputs.
- **Implementation**: All existing subagents MUST be updated to return their final status and summaries adhering to this template.
- **Aggregation Logic**: The Orchestrator MUST include logic to parse these templates and compile them into a unified session report.
- **Human Readability**: The final aggregated report MUST be formatted in clean, readable Markdown for the end user.

## Out of Scope
- Real-time streaming of subagent outputs to the user UI (only post-execution summary is required).

## Acceptance Criteria
1. Subagents produce outputs matching the defined structural template.
2. The Orchestrator successfully compiles outputs from multiple subagents into a single Markdown summary document.
3. The final summary accurately reflects the work performed by all spawned subagents.
