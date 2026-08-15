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
| Triage reconciliation drift | `triage_reconciliation_drift` | `uv run dag-tool triage ...` |
| Review a source mapping | `review_mapping` | `uv run dag-tool mapping review ...` |
| Approve an exact reviewed mapping | `approve_mapping` | `uv run dag-tool mapping approve ...` |
| Create intent node | `create_intent_node` | `uv run dag-tool intent create-node ...` |
| Revise Intent IR | `set_intent` | `uv run dag-tool intent set ...` |
| Inventory legacy intent | Not yet exposed | `uv run dag-tool intent inventory ...` |
| Plan legacy Intent IR migration | Not yet exposed | `uv run dag-tool intent plan-migration ...` |
| Apply legacy Intent IR migration | Not yet exposed | `uv run dag-tool intent apply-migration ...` |
| Validate Intent IR | `validate_intent` | `uv run dag-tool validate-intent --file ...` |
| Review Intent IR | `review_intent` | `uv run dag-tool intent-summary --file ...` |
| Promote accepted spec | `promote_spec` | No manual-move fallback |

Always pass an absolute `project_path`. For `generate_document`, also pass the absolute project
root so its containment checks apply to the target repository instead of the MCP process location.

Treat warnings and string results beginning with `Error:` as failed operations. Re-read state after
a write before claiming success. Do not fall back to manual edits for protected state.

Run drift triage after safe reconciliation and before creating or selecting implementation work.
Review-required, draft, rejected, or missing Intent IR cannot authorize implementation. Explicit
triage decisions must match the current plan digest and include concrete evidence, an actor, and a
timezone-aware timestamp. Only `missing_implementation` on approved intent may be routed to the
implementer; tooling drift goes to the framework, and obsolete or unapproved intent goes back to
Intake/Architecture.

Mapping is a two-step approval gate. Run `review_mapping` immediately before presenting a decision.
Present the decision brief first: intended responsibility and acceptance criteria, actual symbol
documentation and public API, related tests, and unresolved gaps. Explain that test references are
not proof and that approval links identity rather than approving behavior. Show GUIDs and the digest
last as audit inputs. Call `approve_mapping` only after an authorized human explicitly accepts that
exact identity linkage. Never approve ambiguous, unmapped, unsupported, stale, or mismatched
evidence.
