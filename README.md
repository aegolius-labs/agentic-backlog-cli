# Agentic Backlog Manager

A deterministic, 3-Dimensional Impact/Effort/Dependency backlog manager designed for AI/Agentic workflows.

It replaces token-heavy LLM prioritization of Markdown files with a strict, deterministic JSON-based tracking system. It calculates recursive dependency scores, performs topological sorting to ensure prerequisites come first, and auto-generates human-readable Markdown exports.

## Architectural Highlights

The `aio-agentic-sdlc` framework includes several built-in features that ensure deterministic, secure, and traceable agentic operations:

- **Canonical GUID Traceability**: Node IDs map natively and consistently across your PRDs, codebase comments, and DAG structures.
- **QA Sandbox Isolation**: QA agents operate strictly within robust `.qa-sandbox/<session-id>/` environments to ensure they cannot leak or destructively modify core source files.
- **MCP Server Integration**: Downstream subagents securely interact with the system via integrated MCP servers, most notably the Agentic Backlog server.
- **Versioned Local State**: The execution backlog uses explicit schema and revision numbers, atomic replacement, stale-writer protection, and a local transaction audit log.
- **Auditable Intent IR**: Intention nodes can preserve source provenance, assumptions, ambiguities, confidence, evidence-bound acceptance criteria, revision history, and approval state in a strict versioned schema.
- **Evidence-Gated Reconciliation**: GUID matches are confirmed deterministically, structural matches remain review candidates, and unmatched Reality observations never become deletion work by default.
- **SDLC Scribe Agent**: An automated Scribe agent executes before the DevOps agent steps to ensure user-facing documentation (like this README) stays perfectly aligned with the codebase's true reality.

## Licensing Note

This project is intended for **Personal / Non-Commercial Use Only**. When you publish this to GitHub, it is highly recommended to select a license like the **PolyForm Noncommercial License 1.0.0** or **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** from the GitHub license templates.

## Installation & Configuration

Because `aio-agentic-sdlc` is an agentic-first toolkit, the easiest way to install and integrate the MCP Server into your IDE (VS Code, Cursor, Windsurf, Claude Desktop) is by using `uvx` to fetch the server directly from GitHub. This requires **zero local installation**.

### Codex plugin

Codex users can install the repository-scoped plugin from `.agents/plugins/marketplace.json`. It
packages the `manage-sdlc` workflow skill and starts this project's MCP server through UV. See the
[Codex plugin guide](doc/codex-plugin.md) for the architecture, local installation, migration map,
and validation commands.

Add the following to your IDE's `mcp.json` or equivalent configuration file:

```json
"mcpServers": {
  "aio-agentic-sdlc": {
    "command": "uvx",
    "args": [
      "--from",
      "git+https://github.com/aegolius-labs/aio-agentic-sdlc",
      "aio-agentic-sdlc-mcp"
    ]
  }
}
```

### Global Installation (Optional)

If you plan to use the CLI frequently and prefer not to type the full `uvx` GitHub URL every time, you can permanently install the CLI globally using `uv`:

```bash
uv tool install git+https://github.com/aegolius-labs/aio-agentic-sdlc
```

Once installed, you can invoke the CLI natively:

```bash
agb init
agb add "my-feature" --impact 5 --effort 3 --category "Security"
agb prioritize
agb export
agb migrate-state --retire-legacy
```

*(Note: `aio-agentic-sdlc` can also be used if you prefer the full name)*

### Zero-Install Execution (via uvx)

If you prefer not to install the CLI globally, you can execute commands entirely on-the-fly directly from GitHub:

```bash
uvx --from git+https://github.com/aegolius-labs/aio-agentic-sdlc agb init
uvx --from git+https://github.com/aegolius-labs/aio-agentic-sdlc agb export
```

## Spec-Driven Development (SDD)

`aio-agentic-sdlc` utilizes its own Spec-Driven Development (SDD) framework to bridge the gap between high-level architectural planning and deterministic code execution.

Instead of relying on token-heavy LLM context windows or external integrations, the framework strictly enforces:

- **Intention DAG (I-DAG)**: A graph-based structural representation of planned features and dependencies.
- **Reality DAG (R-DAG)**: A deterministic reflection of the actual codebase logic.
- **Canonical Traceability**: PRDs (Product Requirement Documents) in the `specs/` directory are firmly anchored to both DAGs using `aio-sdlc-node` GUID tags, allowing subagents to detect architectural drift automatically and execute Just-In-Time (JIT) TDD loops with zero hallucination.

Intent IR can be validated strictly or reviewed without reading raw YAML:

```bash
uv run dag-tool intent create-node --file intention-dag.yaml --node-id <guid> \
  --type component --name "Capability" --payload-file intent.json
uv run dag-tool validate-intent --file intention-dag.yaml
uv run dag-tool intent-summary --file intention-dag.yaml
```

Use `--allow-partial` during migration while legacy nodes do not yet contain Intent IR. Strict
validation remains the default.

Reconcile identity evidence before creating an execution backlog:

```bash
uv run dag-tool reconcile \
  --intention intention-dag.yaml \
  --reality reality-dag.yaml \
  --max-items 100 \
  --max-candidates 20
uv run dag-tool diff \
  --intention intention-dag.yaml \
  --reality reality-dag.yaml \
  --max-tasks 100 \
  --max-candidates 20
```

Both commands are read-only. Safe diffing is the default: it asks for mapping review or additional
implementation evidence rather than interpreting a missing GUID as permission to create or delete
code. The historical structural algorithm requires the explicit `--mode legacy-structural` option.
Both top-level records and nested candidate identities are bounded while complete totals and
truncation metadata remain visible. Report output refuses to overwrite DAG, backlog, audit, or lock
state.

Promote one unique Python class or function candidate only through an explicit two-step decision:

```bash
uv run dag-tool mapping review --project-path /absolute/project --intent-id <guid>
uv run dag-tool mapping approve --project-path /absolute/project --intent-id <guid> \
  --candidate-reality-id <reviewed-guid> --evidence-digest <reviewed-digest> \
  --approved-by <identity> --approved-at <timezone-aware-iso8601> \
  --rationale "Why this exact source symbol implements the intent"
```

Review regenerates Reality in memory and binds the candidate to its exact source path, symbol,
line, and SHA-256 without changing canonical state. Approval repeats that review under a dedicated
lock, rejects stale or ambiguous evidence, atomically inserts the canonical marker and audit
receipt, and rolls back unless a fresh scan confirms the intended GUID at the same symbol.
