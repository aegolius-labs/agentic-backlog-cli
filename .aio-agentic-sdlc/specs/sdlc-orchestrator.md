# Specification: SDLC Orchestrator

## 1. Overview
The SDLC Orchestrator is the central hub for the `aio-agentic-sdlc` framework. It acts as the single user-facing entity. It manages the Software Development Life Cycle by ingesting user ideas, navigating the Dual-DAG reconciliation loop, and delegating execution to specialized subagents.

## 2. Core Principles
- **Single Pane of Glass:** The user communicates exclusively with the Orchestrator.
- **Strict Delegation:** The Orchestrator does not perform heavy computation, graph generation, or coding. It delegates to specialized subagents.
- **Token-Optimized Communication:** Inter-agent communication relies on highly compressed, token-optimized data structures. Human pleasantries are strictly omitted.
- **The Backlog is a Diff:** The project backlog is entirely dynamic, generated anytime there is a Diff calculated between the Intention DAG and the Reality DAG.

## 3. Specialized Subagent Roles
*   **Cartographer (State Manager):** Updates DAGs and calculates the Diff.
*   **DevOps Manager:** Handles Git branching, conventional commits, and Pull Requests.
*   **Researcher:** Conducts deep research using official sources and creates traceable artifacts.
*   **Architect:** Responsible for Research, Breakdown, and Planning using Researcher artifacts.
*   **Implementer:** Executes code changes using TDD principles.
*   **Linter:** Runs static analysis, code formatters, and security checks.
*   **QA / Tester:** Responsible for adversarial testing and edge-case verification.

## 4. The Orchestrated SDLC Pipeline

### Phase 0: Bootstrap (One-Time Execution)
1.  **Trigger:** Orchestrator detects uninitialized workspace.
2.  **Delegation:** Spawns **Cartographer** to generate initial Reality DAG and baseline Intention DAG.

### Phase 1: Intake & State Update
1.  **Trigger:** User provides requirement.
2.  **Delegation:** Spawns **Cartographer** to update Intention DAG and return Diff (Backlog).

### Phase 2: VCS Initialization
1.  **Delegation:** Spawns **DevOps** to create a Conventional Branch (e.g., `feature/...`) off main based on the Diff.

### Phase 3: Deep Research & Curation
1.  **Delegation:** Spawns **Researcher** to investigate requirements using official docs/papers and produce a traceable artifact in `doc/research/`.

### Phase 4: Breakdown & Planning
1.  **Delegation:** Spawns **Architect** to formulate step-by-step structural implementation plan, utilizing the research artifact.

### Phase 5: Implementation (TDD)
1.  **Delegation:** Parses plan and spawns **Implementers** to write tests and code.

### Phase 6: Static Analysis & Formatting
1.  **Delegation:** Spawns **Linter** to run formatters (black, prettier) and static analysis (CodeQL, flake8).
2.  **Loop:** If failure, route failure context back to **Phase 5 (Implementation)**.

### Phase 7: Comprehensive Testing
1.  **Delegation:** Spawns **QA** for integration and adversarial testing.
2.  **Loop:** If failure, route failure context back to **Phase 5 (Implementation)**.

### Phase 8: Wrap-Up & VCS Finalization
1.  **Delegation:** Spawns **Cartographer** to rescan and verify empty Diff.
2.  **Delegation:** Spawns **DevOps** to commit changes (Conventional Commits), push the branch, and open a PR.
3.  **Completion:** Orchestrator reports success to the user.
