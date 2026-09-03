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
| Visualize or compare canonical DAGs | `visualize_dag` | `uv run dag-tool visualize --project-path ... --view ...` |
| Triage reconciliation drift | `triage_reconciliation_drift` | `uv run dag-tool triage ...` |
| Review a source mapping | `review_mapping` | `uv run dag-tool mapping review ...` |
| Approve an exact reviewed mapping | `approve_mapping` | `uv run dag-tool mapping approve ...` |
| Review a confirmed mapping receipt | `review_mapping_receipt` | `uv run dag-tool mapping receipt review ...` |
| Refresh an exact reviewed receipt | `refresh_mapping_receipt` | `uv run dag-tool mapping receipt refresh ...` |
| Create intent node | `create_intent_node` | `uv run dag-tool intent create-node ...` |
| Revise Intent IR | `set_intent` | `uv run dag-tool intent set ...` |
| Inventory legacy intent | Not yet exposed | `uv run dag-tool intent inventory ...` |
| Plan legacy Intent IR migration | Not yet exposed | `uv run dag-tool intent plan-migration ...` |
| Apply legacy Intent IR migration | Not yet exposed | `uv run dag-tool intent apply-migration ...` |
| Validate Intent IR | `validate_intent` | `uv run dag-tool validate-intent --file ...` |
| Review Intent IR | `review_intent` | `uv run dag-tool intent-summary --file ...` |
| Promote accepted spec | `promote_spec` | No manual-move fallback |

Always pass an absolute `project_path` to tools that accept it. For `generate_document`, also pass
the absolute project root so its containment checks apply to the target repository instead of the
MCP process location. The fixed `backlog://current` and `backlog://hierarchy-rules` resources do
not accept a project path; they resolve against the MCP server's launch directory. Prefer the
project-aware tools when that directory is not the target repository.

Treat warnings and MCP error results as failed operations. Expected domain, validation, and
guarded-path failures preserve a bounded explanatory message; unexpected failures are sanitized.
Re-read state after a write before claiming success. Do not fall back to manual edits for protected
state.

Run drift triage after safe reconciliation and before creating or selecting implementation work.
Review-required, draft, rejected, or missing Intent IR cannot authorize implementation. Explicit
triage decisions must match the current plan digest and include concrete evidence, an actor, and a
timezone-aware timestamp. Only `missing_implementation` on approved intent may be routed to the
implementer; tooling drift goes to the framework, and obsolete or unapproved intent goes back to
Intake/Architecture.

Use `visualize_dag` for read-only `intention`, `reality`, or `comparison` views; no raw-YAML review
is required. Prefer name-first `human` output for a concise brief, `mermaid` for a graph, and `json`
for complete limits, totals, truncation, and evidence. Keep `max_items`, `max_edges`, and
`max_candidates` bounded. Exact source locations are available only when fresh in-memory Reality
generation exactly matches the loaded canonical Reality DAG; visualization does not establish
behavioral verification.

Mapping is a review-first approval gate for observed Python classes and functions only. Before
asking for identity approval, present a human or Mermaid `comparison` from `visualize_dag`, then run
`review_mapping` immediately before presenting the decision. The decision brief must show intended
responsibility and acceptance criteria, actual symbol documentation and public API, related tests,
and unresolved gaps. Test references are not proof, and mapping approval links identity rather than
approving behavior, requirements, or Intent. Show GUIDs and the digest last as audit inputs.

Omitting `candidate_reality_id` keeps automatic name matching. For a differently named symbol, pass
one exact current observed Reality GUID to `review_mapping`; if the human approves that exact
digest, pass the same candidate and `selection_mode="explicit_observed_guid"` to `approve_mapping`.
Never trust or invent source metadata outside the fresh report.

For one confirmed marker with a stale adjacent receipt, call `review_mapping_receipt` and present
its read-only maintenance brief. Call `refresh_mapping_receipt` only after an authorized human
separately approves that exact fresh digest. Refresh preserves the marker and replaces only the
receipt. The evidence hashes the whole annotation-neutral file, so unrelated same-file edits also
make a receipt stale.

Every candidate or receipt digest requires separate human approval; one approval never authorizes
another digest. Reviews do not mutate source or canonical state. Never approve ambiguous,
unsupported, stale, or mismatched evidence, and never fall back to manual marker or receipt edits.
