# Product Requirement Document (PRD)

## Feature
MCP-First Architecture Alignment

## Summary
While the framework supports a standalone CLI for human and CI/CD use, its primary interface for AI agents must be the Model Context Protocol (MCP). Recent feature specifications unintentionally drifted toward CLI-centric workflows for agents (e.g., instructing agents to run bash scripts). This PRD re-aligns the framework to be explicitly MCP-First, ensuring agents interact via structured tools and dynamic data sources rather than parsing `stdout` from fragile shell commands.

## User Stories
- As an AI agent (Architect or Orchestrator), I want to interact with the SDLC framework using strictly typed MCP Tools rather than running CLI commands, so that I receive deterministic, machine-readable JSON responses.
- As a framework user, I want the live, dynamically generated backlog to be continuously exposed to the agentic environment as an MCP Resource, so the Orchestrator always has real-time context without needing to manually generate a file.

## Requirements
- **Core MCP Tools**: All core programmatic actions introduced in recent PRDs MUST be exposed natively as MCP Tools. This includes:
  - `generate_spec_template`: Scaffolds the deterministic Markdown SDD.
  - `get_framework_version`: (Already defined in previous PRD).
  - `trigger_pipeline`: Signals the daemon to execute the diff.
- **MCP Resources (Dynamic Data Sources)**: The execution backlog—calculated by the Diffing Engine comparing the Intention DAG to the Reality DAG—MUST be exposed as a dynamic MCP Resource (e.g., `aio-sdlc://backlog/diff`). The MCP server handles the calculation on-the-fly when the agent reads the resource.
- **CLI as Secondary**: The CLI (e.g., `aio-sdlc plan`) remains fully supported for human users, Daemons, and CI/CD pipelines, but agents MUST default to the MCP server.

## Out of Scope
- Deprecating the CLI entirely (it is still required for human use, daemons, and bootstrap scripts).

## Acceptance Criteria
1. The framework successfully runs as an MCP server, exposing the required tools (`generate_spec_template`, etc.).
2. Agents can read the dynamically generated DAG diff seamlessly by subscribing to or reading the exposed MCP Resource, without a static `.aio-agentic-sdlc/backlog.json` file ever being written to disk.
3. The Orchestrator's standard workflow operates completely without executing a single `aio-sdlc` shell command.
