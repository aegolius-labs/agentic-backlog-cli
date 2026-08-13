---
document_type: prd
title: "Bootstrapping an Existing Project / Legacy Reingestion"
author: "sdlc_intake"
date: "2026-07-14"
status: "Valid - Unprocessed"
---
# Bootstrapping an Existing Project / Legacy Reingestion

## 1. Introduction
This feature introduces a bootstrapping mechanism for existing projects to establish a baseline where the Intention DAG (I-DAG) maps 1-to-1 to the Reality DAG (R-DAG). It also provides a robust way to re-ingest legacy PRDs (processed before `aio-sdlc-node` GUID tags were introduced) by detecting existing implementations and retroactively adding GUID tags.

## 2. Objectives
- Establish an accurate baseline I-DAG for existing codebases that matches the R-DAG.
- Safely and retroactively apply `aio-sdlc-node` GUID tags to legacy code that already fulfills older PRDs.
- Expose bootstrapping capabilities via new MCP tools for the `sdlc_cartographer`.

## 3. Scope
- Adding new MCP tools for the `sdlc_cartographer` to perform semantic mapping and codebase bootstrapping.
- Detecting overlapping requirements between legacy PRDs and existing implementations.
- Retroactive tagging of legacy code without destructive modification.

## 4. Requirements
- The system must treat the existing codebase as "by design" when bootstrapping from scratch, generating an I-DAG that maps 1-to-1 to the R-DAG.
- When re-ingesting legacy PRDs, the system must process them as new requirements but check for existing overlap in the codebase.
- If a legacy PRD is fully implemented, the system must retroactively add `aio-sdlc-node` GUID tags to the corresponding code.
- If a legacy PRD is partially implemented or missing, the system must process it accordingly and align the states.
- The `sdlc_cartographer` must use advanced, language-aware AST or parsing tools to ensure code structure is preserved during tag injection.

## 5. User Stories
- As a developer, I want to run the framework on my existing codebase so that it starts tracking drift from a clean 1-to-1 I-DAG/R-DAG baseline.
- As a developer, I want the framework to automatically map and tag my legacy PRDs to the existing codebase so that I do not have to manually add GUID tags to old code.

## 6. Success Metrics
- 100% of legacy codebase mapped to a baseline I-DAG without manual intervention.
- Zero broken builds or syntax errors introduced during retroactive tag injection.

## 7. Dependencies
- Language-specific AST/parsing tools for safe tag injection.
- LLM or Semantic Search capabilities for accurately mapping natural language requirements to existing code logic.

## 8. Non-Functional Requirements
- **Token & Context Limits**: Strict chunking, RAG, or hierarchical summarization must be implemented to handle large repositories safely.
- **API Rate Limiting**: Backoff mechanisms must be used to handle large repository scanning.
- **Idempotency**: The bootstrapping process must be perfectly idempotent, allowing safe re-runs if failures occur.

## 9. Out of Scope
- Universal language support on day one (a whitelist of supported languages will be documented based on comment syntax).
- Automatic tagging of files exceeding maximum token limits (these must be flagged for manual review).
- Tag injection into auto-generated or minified files (e.g., `dist/`, `build/`).

## 10. Viability Research
Viability analysis indicates **High complexity** in semantic mapping and non-destructive tagging. Key edge cases include partial implementations, overlapping requirements, and strict linting rules. Major risks include hallucinated LLM mappings and silent code corruption. A chunking/RAG strategy is required to overcome large codebase context limits, and language-specific AST tools are necessary for safe modification.

## 11. Changelog
- 2026-07-14: Initial PRD created.
