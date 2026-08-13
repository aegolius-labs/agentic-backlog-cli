# All-in-One Agentic SDLC (aio-agentic-sdlc) Vision & North Star

## The Dual-DAG Reconciliation Engine

The ultimate "North Star" for this project is to evolve beyond passive task tracking into a fully autonomous, **All-in-One Agentic Software Development Life Cycle (SDLC)** orchestrator. It acts as the definitive reconciliation engine between software design and reality.

## Core Philosophy

1. **The Intention DAG:** We maintain a living Directed Acyclic Graph (DAG) that represents the *desired* state of the software. It documents how the project is supposed to work, structural decisions, requirements, and dependencies.
2. **The Reality DAG:** We generate a real-time DAG representing the *actual* state of the implemented codebase. To ensure we can compute an accurate delta, we must build our own Reality DAG generator so that it maps 1:1 with the ontology and schema of the Intention DAG.
3. **The Backlog as a Diff:** The "Backlog" is no longer a static list of user-created tasks. The Backlog is mathematically defined as the **Diff** between the Intention DAG and the Reality DAG. This diff precisely highlights missing dependencies, orphaned code, incomplete features, and architectural misalignments.
4. **Agentic Orchestration:** By calculating this Diff, our agentic SDLC framework knows exactly where the software is and where it needs to go. It can autonomously break down the Diff, formulate implementation plans, and delegate work to specialized subagents (Architects, Implementers, QA) to continuously pull the Reality DAG into alignment with the Intention DAG.

## Implications for Architecture

- **In-House Graph Generation:** Relying on third-party tools (like `graphify`) is insufficient if their output cannot map cleanly to our semantic Intention DAG. Both sides of the equation must speak the same structural language.
- **Local Persistence is Key:** The version-controlled `.aio-agentic-sdlc/intention-dag.yaml` is the source of truth for project intent. The Reality DAG and execution backlog are local derivatives with explicitly narrower responsibilities.
- **Hierarchy & Relationships are Fundamental:** Hierarchical types and dependency relationships are not organizational conveniences—they are the critical structural edges required to compute an accurate diff between Intention and Reality.
- **Remote Projections Are Future Work:** External tracker integrations are currently removed. If reintroduced, they must be one-way projections whose contents cannot override locally derived work.
