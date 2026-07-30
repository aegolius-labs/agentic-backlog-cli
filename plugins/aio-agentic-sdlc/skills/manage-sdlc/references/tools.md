# Tool map

Tool names may be namespaced by the Codex host. Match them by the operation names below.

| Intent | MCP operation | UV CLI fallback |
| --- | --- | --- |
| Get next work | `get_next_task` | `uv run agb next` |
| Add work | `add_task` | `uv run agb add ...` |
| Update work | `update_task` | `uv run agb update ...` |
| Change status | `update_task_status` | `uv run agb status ...` |
| Remove work | `remove_task` | `uv run agb remove ...` |
| Reprioritize | `prioritize_backlog` | `uv run agb prioritize` |
| Add blocker | `block_task` | `uv run agb block ...` |
| Generate framework document | `generate_document` | No manual-file fallback |
| Check PRD overlap | `check_duplicate_prd` | Use the Python API if MCP is unavailable |
| Validate GUID links | `validate_traceability` | Use the Python API if MCP is unavailable |
| Generate Reality DAG | `generate_reality` | `uv run dag-tool generate-reality ...` |
| Reconcile DAG identity evidence | `reconcile_dags` | `uv run dag-tool reconcile ...` |
| Create intent node | `create_intent_node` | `uv run dag-tool intent create-node ...` |
| Revise Intent IR | `set_intent` | `uv run dag-tool intent set ...` |
| Validate Intent IR | `validate_intent` | `uv run dag-tool validate-intent --file ...` |
| Review Intent IR | `review_intent` | `uv run dag-tool intent-summary --file ...` |
| Promote accepted spec | `promote_spec` | No manual-move fallback |

Always pass an absolute `project_path`. For `generate_document`, also pass the absolute project
root so its containment checks apply to the target repository instead of the MCP process location.

Treat warnings and string results beginning with `Error:` as failed operations. Re-read state after
a write before claiming success. Do not fall back to manual edits for protected state.
