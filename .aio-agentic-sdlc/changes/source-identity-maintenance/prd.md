---
document_type: prd
title: "Add Explicit Source Identity Maintenance"
author: "Felix / Codex"
date: "2026-08-21"
status: "Valid - Unprocessed"
---
# Add Explicit Source Identity Maintenance

## 1. Introduction

Extend the existing approval-gated source mapping capability so Cartographer can review an exact differently named Reality symbol and refresh stale approval evidence for an already marker-confirmed symbol.

The extension closes a framework-tooling gap discovered while dogfooding the MCP SDK v2 migration. It must preserve canonical GUID authority and the rule that every exact identity digest requires separate human approval.

## 2. Objectives

- Let a reviewer explicitly nominate one current Reality class or function when deterministic name matching returns no candidate.
- Produce a fresh, bounded, source-bound decision brief and digest before any identity mutation.
- Review and atomically refresh an existing confirmed mapping receipt without replacing its canonical marker.
- Preserve Python API, CLI, MCP, and Codex workflow parity with fail-closed concurrency and path safety.

## 3. Scope

- Extend `MappingEngine` review and approval flows with an explicit observed-candidate mode.
- Add a receipt-refresh review and approval mode for one uniquely marker-confirmed Python symbol.
- Bind both modes to fresh canonical DAGs, Reality observations, source bytes, symbol identity, adjacent receipts, and deterministic evidence digests.
- Add bounded human and JSON output, CLI and MCP adapters, workflow documentation, and adversarial tests.
- Dogfood the capability against the MCP v2 representative symbol and the stale `RealityDAGGenerator` and `TraceabilityValidator` receipts.

## 4. Requirements

1. Explicit candidate review accepts a canonical Intent GUID and exact observed Reality GUID, then independently verifies the current supported symbol rather than trusting caller-supplied source metadata.
2. Receipt-refresh review requires one existing canonical marker, one adjacent parseable receipt for the same intent and symbol, and a fresh Reality confirmation.
3. Both reviews emit deterministic source-bound evidence and a human brief that separates identity evidence from behavioral proof.
4. Approval requires the exact fresh digest and explicit approver, timestamp, and rationale; stale or mismatched evidence is rejected.
5. Candidate approval inserts one marker and receipt using the existing rollback contract. Receipt refresh preserves the marker and atomically replaces only the receipt.
6. Path escape, symlink, reparse-point, hardlink, duplicate marker or receipt, source swap, stale writer, concurrent approval, or post-write verification failure cannot leave a partial mutation.
7. Python API, CLI, MCP, and Codex workflow guidance expose the same bounded operation and approval semantics.
8. The three MCP dogfood identities remain unmodified until their exact fresh evidence is presented to and separately approved by Felix.

## 5. User Stories

- As a Cartographer, I can propose the exact implementation boundary even when a good class name differs from the Intention title.
- As a repository owner, I can understand and explicitly approve the exact symbol and digest before any GUID marker or receipt changes.
- As a maintainer, I can refresh stale identity provenance caused by unrelated same-file edits without removing and recreating a valid marker.
- As a QA reviewer, I can prove failed or concurrent maintenance operations leave source and canonical state intact.

## 6. Success Metrics

- Explicit differently named candidate review produces one stable digest and decision brief for the MCP v2 implementation boundary.
- Confirmed receipt review produces fresh stable digests for `RealityDAGGenerator` and `TraceabilityValidator`.
- CLI and MCP reports are object-equivalent and bounded.
- Focused adversarial and concurrency tests, full warning-strict tests, static checks, build, plugin validators, and deterministic Reality/reconciliation reproduction pass.
- No source marker, receipt, canonical DAG, backlog, or audit artifact changes before exact human identity approval.

## 7. Dependencies

- Existing `Approval-Gated Source Mapping` Intent and `MappingEngine`.
- Evidence-gated reconciliation, Reality generation, source marker parsing, guarded paths, and persistent file locks.
- Approved MCP SDK v2 implementation and its formal QA evidence.

## 8. Non-Functional Requirements

- Preserve deterministic output, bounded reports, atomic rollback, Windows reparse-point protection, Python 3.10+, and local-first authority.
- Do not introduce a new dependency or external service.
- Do not weaken duplicate-ID, stale-evidence, path-containment, or concurrency safeguards.
- Unexpected MCP failures remain sanitized and expected decision failures remain bounded and actionable.

## 9. Out of Scope

- Changing receipts from whole-file hashes to symbol-scoped hashes.
- Automatically approving any identity based on names, tests, or structural proximity.
- Treating identity approval as behavioral verification or requirement acceptance.
- Supporting module variables, arbitrary source ranges, or languages not currently represented as exact class/function source locations.
- Renaming implementation symbols merely to create an automatic name match.

## 10. Viability Research

Repository inspection shows the extension can reuse `MappingEngine`, `ReconciliationEngine`, `RealityDAGGenerator`, guarded path primitives, persistent mapping locks, and the current atomic marker rollback path without adding a dependency.

Current review accepts only a single automatic structural candidate, while confirmed mappings cannot emit a refresh digest. These are bounded contract gaps rather than an ontology rewrite.

The semantic duplicate tool could not run locally because its embedding model attempted external metadata access, which was not authorized. A deterministic canonical inspection establishes that this PRD amends the existing `Approval-Gated Source Mapping` capability rather than creating a competing product feature.

## 11. Changelog

- 2026-08-21: Initial approved extension PRD compiled from MCP v2 post-QA dogfooding, recovery roadmap section 1.8, canonical mapping intent, and Felix's explicit tooling authorization.
