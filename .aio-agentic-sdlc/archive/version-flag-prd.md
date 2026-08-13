# Product Requirement Document (PRD)

## Feature
Add `--version` flag to the `aio-sdlc` CLI and a `get_version` tool to the MCP server.

## Summary
The goal of this feature is to allow users and agents to quickly identify which version of the `aio-sdlc` framework they are currently running. By providing a `--version` flag on the CLI entrypoint and a dedicated MCP tool, humans and agents can easily verify the active deployment or debug environment setup issues.

## User Stories
- As a user, I want to type `aio-sdlc --version` in my terminal so that I can see the currently installed version of the framework.
- As a developer/support engineer, I want users to easily output their framework version so that I can provide accurate troubleshooting assistance.
- As an AI agent utilizing the `aio-sdlc` MCP server, I want to invoke a `get_version` tool to understand the capabilities of the runtime I am interacting with.

## Requirements
- **CLI Flag:** The entrypoint `aio-sdlc` MUST support a `-v` and `--version` argument.
- **Fast Execution / Bypass:** The CLI version flag MUST be processed before any API token validation or complex environment initialization, ensuring it always returns successfully regardless of setup state.
- **Output:** When the flag is passed, the CLI MUST output the current framework version to standard output (e.g., `aio-sdlc version 1.2.3`) and immediately exit with a `0` exit code.
- **MCP Tool:** The `aio-sdlc` MCP Server MUST expose a `get_version` tool that returns the exact same version string.
- **Dependency Integration:** The version string should ideally be sourced dynamically from the project's metadata (e.g., `pyproject.toml`, package version) to avoid hardcoding.

## Out of Scope
- Command-line help text refactoring (beyond adding the version flag description).
- Upgrading or self-updating functionality.

## Acceptance Criteria
1. Running `aio-sdlc --version` prints the version string without requiring API tokens or environment setup.
2. Running `aio-sdlc -v` prints the version string.
3. The CLI exits cleanly (exit code 0) after printing the version without executing any other logic.
4. Calling the `get_version` tool via MCP successfully returns the framework version.
