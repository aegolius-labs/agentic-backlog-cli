# Product Requirement Document (PRD): Canonical GUID Traceability & Mappings

## 1. Overview
Currently, mapping elements across the AIO-Agentic-SDLC framework can lead to mismatches and relies on language-specific approaches. To eliminate these mismatches and enforce a true stack-agnostic approach, we require a standardized ecosystem-wide adoption of strict Node IDs (UUIDs) across the Intention DAG, Reality DAG, specifications, and source code. 

## 2. Goals & Objectives
* **Eliminate Mismatches**: Prevent misalignments between intention nodes, reality nodes, specifications, and implemented code.
* **Full Traceability**: Ensure an uninterrupted, auditable trail across the board by creating a deterministic 1:1 mapping between architecture and implementation.
* **Stack Agnosticism**: Ensure the framework can track implementations across any language without relying on language-specific features (e.g., Python decorators).

## 3. Core Requirements
1. **Intention Owns the ID:** The Intention DAG is the absolute source of truth for all node UUIDs.
2. **Implementation Embeds the ID:** The codebase must explicitly embed these UUIDs so the Reality DAG Generator can extract them and deterministically map them 1:1 back to the Intention DAG.
3. **Strict Stack Agnosticism (Code):** The in-code ID insertion MUST NOT be language-specific (e.g., no decorators). It must use standard language comments (e.g., `# aio-sdlc-node: <uuid>` or `// aio-sdlc-node: <uuid>`) so it works regardless of the technology stack.
4. **Agent Files (Frontmatter):** For agent configuration and instruction files (`.md`), the Node ID must be placed as a subfield in the YAML frontmatter (e.g., `metadata: { node_id: <uuid> }`). This ensures the GUIDs do not pollute the prompt context for LLM instructions.

## 4. Pipeline Execution Instructions
* **Research Phase:** The Architect MUST invoke the `sdlc_researcher` to conduct a technical spike on how to cleanly extract multi-language comments using Tree-Sitter before writing the Software Design Document (SDD).
* **Architecture Phase:** The Architect must map the necessary components to `.aio-agentic-sdlc/intention-dag.yaml` and draft an explicit SDD in `.aio-agentic-sdlc/specs/` based on the Researcher's findings.
