# UX Layer Implementation Plan for AIO-Agentic-SDLC

This document outlines the structural implementation plan for the User Experience (UX) layer of the AIO-Agentic-SDLC framework, handling both agentic intake and manual execution.

## 1. Intake Agent (`sdlc_intake`)

The `sdlc_intake` subagent acts as the intelligent interface between the user and the framework. It distills user requirements into structured specifications and updates the system DAG representation, without triggering execution.

### Components to Create:

*   **`.agents/agents/sdlc_intake/system_prompt.md`**:
    *   Define the role: Act as a product manager and architect.
    *   Responsibilities: Chat with the user, solicit requirement details, and formulate formal technical specs.
    *   Output: Write Markdown specifications to the `.aio-agentic-sdlc/specs/` directory.
    *   Graph Updates: Update `.aio-agentic-sdlc/intention-dag.yaml` strictly with the structural changes.
    *   Constraint: **Never** write execution code or trigger the SDLC loop.

*   **`.agents/agents/sdlc_intake/agent.md`**:
    *   Provide the basic subagent definition metadata (`name`, `description`, `model`).
    *   Specify necessary tool bindings (e.g., file system reading/writing for `.aio-agentic-sdlc/specs/` and `.aio-agentic-sdlc/intention-dag.yaml`).

## 2. CLI Entrypoint (`aio_agentic_sdlc/cli.py`)

A command-line interface acts as the manual invocation point for the user to plan and execute the derived SDLC tasks.

### Features & Updates:

*   **`src/aio_agentic_sdlc/cli.py`**:
    *   Define a CLI entrypoint for SDLC operations.
    *   **`plan` Command**: 
        *   Instantiates and runs the `DiffingEngine`.
        *   Calculates the diff between the reality DAG and `.aio-agentic-sdlc/intention-dag.yaml`.
        *   Outputs the generated backlog/diff directly to the terminal for user review.
    *   **`apply` Command**: 
        *   Executes `orchestrator_loop.py`.
        *   Spawns subagents to consume the prioritized backlog and execute changes.

*   **`pyproject.toml` Integration**:
    *   Update `[project.scripts]` section to include the CLI tool mapping:
        ```toml
        aio-sdlc = "aio_agentic_sdlc.cli:main"
        ```

## 3. Workflow Integration

1.  **Ideation**: User interacts with the `sdlc_intake` agent.
2.  **Specification**: `sdlc_intake` generates `.aio-agentic-sdlc/specs/*` and updates `.aio-agentic-sdlc/intention-dag.yaml`.
3.  **Review**: User runs `aio-sdlc plan` to review proposed structural differences in the DAGs.
4.  **Execution**: User runs `aio-sdlc apply` to deploy subagents for automated implementation.
