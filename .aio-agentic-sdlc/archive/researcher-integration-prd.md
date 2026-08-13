# Product Requirement Document (PRD)

## Feature
Architect-Researcher Swarm Integration

## Summary
Currently, the Architect Agent acts as a monolith, attempting to perform deep technical research on its own while drafting Software Design Documents (SDDs). This leaves the `sdlc_researcher` agent entirely orphaned from the pipeline. This feature integrates the Researcher back into the workflow by upgrading the Architect into a sub-orchestrator. The Architect will delegate complex technical spikes, API documentation reading, and feasibility studies to the Researcher *before* finalizing any technical specs.

## User Stories
- As an Architect Agent, I want to delegate deep technical research (e.g., reading external API docs or finding the right library) to a specialized Researcher subagent so I can focus strictly on IDAG mapping and system design.
- As a framework user, I want my SDDs to be backed by actual, documented research rather than relying on the Architect to hallucinate implementation details.

## Requirements
- **Subagent Tooling**: Update the `sdlc_architect` agent configuration (`agent.md`) to grant it the `invoke_subagent` and `manage_subagents` tools.
- **Prompt Refactor**: Update the Architect's system instructions to explicitly mandate spawning the `sdlc_researcher` whenever a new PRD requires unknown dependencies, external APIs, or complex algorithms.
- **Research Artifacts**: The `sdlc_researcher` MUST output its findings as structured Markdown "Research Spikes" in a dedicated directory (e.g., `.aio-agentic-sdlc/specs/research/`).
- **SDD Synthesis**: The Architect MUST read and synthesize these Research Spikes before scaffolding the final SDD template and updating the Intention DAG.

## Out of Scope
- Having the Researcher interact directly with the Implementer agents. The Researcher answers strictly to the Architect during the planning phase.

## Acceptance Criteria
1. The `sdlc_architect` possesses the tools required to spawn subagents.
2. When processing a complex PRD, the Architect successfully spawns the `sdlc_researcher` and waits for its findings.
3. The Researcher generates tangible research artifacts that the Architect demonstrably uses to write the final SDD.
