# Agentic Backlog Manager

A deterministic, 3-Dimensional Impact/Effort/Dependency backlog manager designed for AI/Agentic workflows.

It replaces token-heavy LLM prioritization of Markdown files with a strict, deterministic JSON-based tracking system. It calculates recursive dependency scores, performs topological sorting to ensure prerequisites come first, and auto-generates human-readable Markdown exports.

## Architectural Highlights

The `aio-agentic-sdlc` framework includes several built-in features that ensure deterministic, secure, and traceable agentic operations:

- **Canonical GUID Traceability**: Node IDs map natively and consistently across your PRDs, codebase comments, and DAG structures.
- **QA Sandbox Isolation**: QA agents operate strictly within robust `.qa-sandbox/<session-id>/` environments to ensure they cannot leak or destructively modify core source files.
- **MCP Server Integration**: The official Python MCP SDK v2 `MCPServer` exposes the Agentic Backlog server over stdio with 23 tools, two resources, and one prompt; the two additive tools maintain source-identity receipts.
- **Versioned Local State**: The execution backlog uses explicit schema and revision numbers, atomic replacement, stale-writer protection, and a local transaction audit log.
- **Auditable Intent IR**: Intention nodes can preserve source provenance, assumptions, ambiguities, confidence, evidence-bound acceptance criteria, revision history, and approval state in a strict versioned schema.
- **Evidence-Gated Reconciliation**: GUID matches are confirmed deterministically, structural matches remain review candidates, and unmatched Reality observations never become deletion work by default.
- **Read-Only DAG Visualization**: Name-first human, safe Mermaid, and JSON views compare bounded Intention and Reality evidence without exposing raw YAML or mutating framework state.
- **Approval-Aware Drift Triage**: Safe-plan work is withheld from implementation until accepted intent, Reality observability, and digest-bound classification evidence agree.
- **SDLC Scribe Agent**: An automated Scribe agent executes before the DevOps agent steps to ensure user-facing documentation (like this README) stays perfectly aligned with the codebase's true reality.

## Licensing Note

This project is intended for **Personal / Non-Commercial Use Only**. When you publish this to GitHub, it is highly recommended to select a license like the **PolyForm Noncommercial License 1.0.0** or **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** from the GitHub license templates.

## Installation & Configuration

Because `aio-agentic-sdlc` is an agentic-first toolkit, the easiest way to install and integrate the MCP Server into your IDE (VS Code, Cursor, Windsurf, Claude Desktop) is by using `uvx` to fetch the server directly from GitHub. This requires **zero local installation**.

The package supports `mcp>=2.0.0,<3`; the reviewed development lock resolves MCP 2.0.0. The
launcher remains stdio-based, so existing host configuration does not need a transport change for
the SDK v2 migration.

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

The two fixed resources, `backlog://current` and `backlog://hierarchy-rules`, read the repository
that was the MCP server's working directory when it started. Tools that accept `project_path`
should receive an absolute repository path and are the safer choice when one server may address a
different checkout. See the [Codex plugin guide](doc/codex-plugin.md#mcp-sdk-v2-runtime-contract)
for the verified protocol contract and validation commands.

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

### Migrating an Existing Checkout

Before using a project created with the former root-level layout, run:

```bash
aio-sdlc migrate-state
```

The command moves recognized framework state into `.aio-agentic-sdlc/`: root
`backlog.json`, `.aio-agentic-sdlc.json`, `intention-dag.yaml`,
`reality-dag.yaml`, and the former `.aio-sdlc` audit/legacy state. The retired
GitHub configuration is removed while hierarchy and validation settings are
preserved with local mode enforced. Each moved file is recorded with hashes in
the canonical audit log before backlog schema migration continues.

Migration fails without choosing a winner when both old and new paths exist,
when a source is a symlink, or when its content is not a valid framework
artifact. Normal state commands also fail with a migration instruction instead
of silently starting an empty backlog. Generic host directories such as
`specs/`, `changes/`, `archive/`, `inbox/`, and `research-spikes/` are never
claimed automatically. The migrator bridges the former and current state and mapping locks,
discards known obsolete lock files after release, removes `.aio-sdlc/` when it
is empty, and reports rather than deletes any unknown entries that remain.

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
- **Canonical Traceability**: PRDs in `.aio-agentic-sdlc/specs/` are anchored to both DAGs using `aio-sdlc-node` GUID tags, allowing subagents to detect architectural drift and execute Just-In-Time (JIT) TDD loops from explicit evidence.

Intent IR can be validated strictly or reviewed without reading raw YAML:

```bash
uv run dag-tool intent create-node --file .aio-agentic-sdlc/intention-dag.yaml --node-id <guid> \
  --type component --name "Capability" --payload-file intent.json
uv run dag-tool validate-intent --file .aio-agentic-sdlc/intention-dag.yaml
uv run dag-tool intent-summary --file .aio-agentic-sdlc/intention-dag.yaml
```

Use `--allow-partial` during migration while legacy nodes do not yet contain Intent IR. Strict
validation remains the default.

Legacy DAGs can be compiled and migrated without hand-editing canonical YAML:

```bash
uv run dag-tool intent inventory --project-path . --max-items 100
uv run dag-tool intent plan-migration --project-path . \
  --recorded-at <timezone-aware-iso-timestamp> \
  --actor <actor> \
  --generator-version <version> \
  --output .aio-agentic-sdlc/changes/legacy-intent-ir-migration/plan.json
uv run dag-tool intent apply-migration --project-path . \
  --plan-file .aio-agentic-sdlc/changes/legacy-intent-ir-migration/plan.json
```

The deterministic compiler preserves exact legacy descriptions and relationship evidence. It
does not infer semantic completeness: every migrated payload retains an open ambiguity and the
`review_required` approval state. Apply is all-or-nothing and rejects stale plans or protected
output paths before changing canonical state. It also recompiles the expected plan, so editing and
re-digesting a valid payload cannot bypass the deterministic compiler. Source identities hash the
validated DAG content model rather than checkout bytes, so equivalent LF and CRLF files share one
identity. Inventory, planning, migration, single-node Intent updates, structural DAG commands, and
legacy ID migration coordinate on the same per-DAG lock.

Reconcile identity evidence before creating an execution backlog:

```bash
uv run dag-tool reconcile \
  --intention .aio-agentic-sdlc/intention-dag.yaml \
  --reality .aio-agentic-sdlc/reality-dag.yaml \
  --max-items 100 \
  --max-candidates 20
uv run dag-tool diff \
  --intention .aio-agentic-sdlc/intention-dag.yaml \
  --reality .aio-agentic-sdlc/reality-dag.yaml \
  --max-tasks 100 \
  --max-candidates 20
uv run dag-tool triage \
  --intention .aio-agentic-sdlc/intention-dag.yaml \
  --reality .aio-agentic-sdlc/reality-dag.yaml \
  --max-items 100
```

Inspect the same canonical workspace without reading raw DAG YAML:

```bash
uv run dag-tool visualize --project-path /absolute/project \
  --view comparison --max-items 100 --max-edges 200 --max-candidates 20 \
  --format human
uv run dag-tool visualize --project-path /absolute/project \
  --view comparison --focus-node <guid> --depth 1 --format mermaid
```

Visualization is read-only and available through the equivalent `visualize_dag` MCP tool. Human
output leads with names and classifications; Mermaid uses synthetic identifiers and escaped,
bounded labels. Use JSON to inspect complete totals, truncation, reconciliation details, and exact
source locations. Source locations are included only when fresh in-memory Reality generation
exactly matches the loaded canonical Reality DAG, and visualization never claims behavioral
verification. See [DAG visualization and comparison](doc/dag-visualization.md) for view semantics,
bounds, self-dogfood commands, and the mapping-review workflow.

Reconciliation and safe diffing are read-only. Safe diffing is the default: it asks for mapping review or additional
implementation evidence rather than interpreting a missing GUID as permission to create or delete
code. The historical structural algorithm requires the explicit `--mode legacy-structural` option.
Both top-level records and nested candidate identities are bounded while complete totals and
truncation metadata remain visible. Report output refuses to overwrite DAG, backlog, audit, or lock
state.

Triage is also read-only. It automatically withholds draft, review-required, rejected, or missing
Intent IR as `obsolete_or_unapproved_intent`; it does not turn those nodes into coding work.
Relationships whose endpoint intent is unapproved are withheld, and relationship shapes the
Reality parser cannot emit are classified as `framework_tooling_drift`. Remaining approved gaps
require a `TriageDecisionSet` whose digest matches the exact validated Intention and Reality
content. Only an explicit `missing_implementation` decision on approved intent is marked actionable.
The default human view presents names and reasons first and leaves GUIDs and hashes in its final
audit section. Use `--format json` for automation, `--decisions <file>` for explicit classifications,
and `--output <file>` for an atomically written derived report.

Map one unique Python class or function only through a fresh review followed by a separate human
approval. Automatic name matching remains the default:

```bash
uv run dag-tool mapping review --project-path /absolute/project --intent-id <guid>
# Machine consumers can request the complete report explicitly:
uv run dag-tool mapping review --project-path /absolute/project --intent-id <guid> --format json
uv run dag-tool mapping approve --project-path /absolute/project --intent-id <guid> \
  --candidate-reality-id <reviewed-guid> --evidence-digest <reviewed-digest> \
  --approved-by <identity> --approved-at <timezone-aware-iso8601> \
  --rationale "Why this exact source symbol is the intended identity boundary"
```

When the intended responsibility and implementation symbol have different names, nominate an
exact GUID from the current Reality observations during review and replay that selection mode only
after a human approves the resulting digest:

```bash
uv run dag-tool mapping review --project-path /absolute/project --intent-id <guid> \
  --candidate-reality-id <observed-reality-guid>
uv run dag-tool mapping approve --project-path /absolute/project --intent-id <guid> \
  --candidate-reality-id <reviewed-guid> --evidence-digest <reviewed-digest> \
  --selection-mode explicit_observed_guid \
  --approved-by <identity> --approved-at <timezone-aware-iso8601> \
  --rationale "Why this exact source symbol is the intended identity boundary"
```

Review and refresh a stale receipt for an already confirmed marker as another two-step decision:

```bash
uv run dag-tool mapping receipt review --project-path /absolute/project --intent-id <guid>
uv run dag-tool mapping receipt refresh --project-path /absolute/project --intent-id <guid> \
  --evidence-digest <reviewed-digest> \
  --approved-by <identity> --approved-at <timezone-aware-iso8601> \
  --rationale "Why the refreshed whole-file evidence preserves this source identity"
```

Review regenerates Reality in memory and defaults to a human decision brief. The brief puts the
intended responsibility, acceptance criteria, relationships, implementation documentation, public
API, and related tests ahead of GUIDs and hashes. Related tests are references, not proof; mapping
approval links source identity and does not approve the Intent IR or claim behavioral completion.
The machine report and its digest bind the reviewed intent semantics and the exact source evidence
without changing canonical state. Approval repeats that review under a dedicated lock, rejects
stale or ambiguous evidence, atomically inserts the canonical marker and audit receipt, and rolls
back unless a fresh scan confirms the intended GUID at the same symbol.

Explicit candidate review and receipt review are read-only. Each exact digest requires its own
human approval; approval of one candidate or receipt never authorizes another. Receipt refresh
preserves the canonical marker and replaces only its adjacent receipt. Evidence currently hashes
the whole annotation-neutral file, so even an unrelated edit in that file intentionally makes the
receipt stale. Only observed Python classes and functions are supported. Use these tools or their
Python API equivalents—never insert, replace, or repair mapping markers and receipts manually.
