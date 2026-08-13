# Specification: Subagent Output Templates

## 1. Overview
To ensure the SDLC Orchestrator can compile clean, human-readable summaries of parallel sessions and effectively parse subagent responses, all subagents must adhere to standardized structured reporting templates. This specification defines the token-optimized communication formats for each specialized subagent.

## 2. Core Principles
*   **Structured Parsing:** The Orchestrator must be able to programmatically extract status, metrics, and actionable items from any subagent's response.
*   **Token Optimization:** Templates should be concise and omit conversational pleasantries.
*   **Uniformity:** Common fields (e.g., `status`, `agent_role`, `execution_time`) must be present across all templates.
*   **Human-Readable Fallback:** While optimized for parsing, the raw text should still be legible if presented directly.

## 3. General Output Template Structure
All subagents must return a JSON-formatted response Block within markdown code fences or as a raw JSON string.

### 3.1 Common Fields
| Field | Type | Description |
| --- | --- | --- |
| `agent_role` | String | The role of the subagent (e.g., "Implementer", "Linter"). |
| `status` | String | Must be one of `SUCCESS`, `FAILURE`, or `NEEDS_INPUT`. |
| `execution_time_ms` | Integer | Total time taken by the subagent in milliseconds. |
| `summary` | String | A concise, human-readable summary (max 2 sentences). |
| `artifacts_produced` | Array | List of relative file paths generated or modified. |

## 4. Subagent-Specific Templates

### 4.1 Cartographer (State Manager)
```json
{
  "agent_role": "Cartographer",
  "status": "SUCCESS",
  "execution_time_ms": 1200,
  "summary": "Intention DAG updated and Diff calculated.",
  "artifacts_produced": [".aio-agentic-sdlc/intention-dag.yaml", ".aio-agentic-sdlc/backlog.json"],
  "payload": {
    "diff_count": 3,
    "diff_items": ["Added node X", "Updated edge Y"]
  }
}
```

### 4.2 DevOps Manager
```json
{
  "agent_role": "DevOps Manager",
  "status": "SUCCESS",
  "execution_time_ms": 800,
  "summary": "Branch created and PR opened.",
  "artifacts_produced": [],
  "payload": {
    "branch_name": "feature/subagent-templates",
    "pr_url": "https://github.com/org/repo/pull/123",
    "commits": ["feat: define structured templates"]
  }
}
```

### 4.3 Researcher
```json
{
  "agent_role": "Researcher",
  "status": "SUCCESS",
  "execution_time_ms": 4500,
  "summary": "Completed research on templating standards.",
  "artifacts_produced": ["doc/research/templating.md"],
  "payload": {
    "sources_cited": ["https://docs.example.com"],
    "key_findings": ["Use JSON for structured logs."]
  }
}
```

### 4.4 Architect
```json
{
  "agent_role": "Architect",
  "status": "SUCCESS",
  "execution_time_ms": 3200,
  "summary": "Implementation plan formulated.",
  "artifacts_produced": [".aio-agentic-sdlc/specs/implementation-plan.md"],
  "payload": {
    "tasks": ["Create spec", "Update DAG", "Write schema validations"]
  }
}
```

### 4.5 Implementer
```json
{
  "agent_role": "Implementer",
  "status": "SUCCESS",
  "execution_time_ms": 12500,
  "summary": "Code logic and unit tests implemented.",
  "artifacts_produced": ["src/templates.py", "tests/test_templates.py"],
  "payload": {
    "lines_added": 145,
    "lines_removed": 12,
    "tests_passed": true
  }
}
```

### 4.6 Linter
```json
{
  "agent_role": "Linter",
  "status": "FAILURE",
  "execution_time_ms": 1500,
  "summary": "Flake8 detected 2 formatting errors.",
  "artifacts_produced": [],
  "payload": {
    "formatters_run": ["black", "prettier"],
    "linters_run": ["flake8"],
    "errors": [
      "src/templates.py:12:1: E302 expected 2 blank lines, found 1"
    ]
  }
}
```

### 4.7 QA / Tester
```json
{
  "agent_role": "QA / Tester",
  "status": "SUCCESS",
  "execution_time_ms": 8000,
  "summary": "All adversarial test cases passed.",
  "artifacts_produced": ["reports/qa-report.json"],
  "payload": {
    "tests_executed": 45,
    "tests_failed": 0,
    "coverage_percentage": 94.2
  }
}
```

## 5. Orchestrator Processing
The Orchestrator will:
1. Parse the JSON block from each subagent.
2. Aggregate the `summary` fields and `status` fields into a unified session report.
3. Use the `status` field to determine control flow (e.g., routing failures back to Implementation).
