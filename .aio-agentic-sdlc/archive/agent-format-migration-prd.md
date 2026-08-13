# Product Requirement Document (PRD)

## Feature
Agent Definition Format Migration (JSON to MD Frontmatter)

## Summary
The framework's custom agents were partially migrated to the modern `agent.md` format (YAML frontmatter + markdown instructions). However, several agents remain stuck on the legacy `agent.json` + `system_prompt.md` split format. Because the Reality DAG (RDAG) models high-level architectural components rather than specific file-format compliance, the Diffing Engine cannot dynamically auto-detect this syntax inconsistency. This feature explicitly tasks the implementation swarm with normalizing all agent configurations.

## User Stories
- As a framework maintainer, I want all custom agents to use the unified `agent.md` format so that I only have one file to edit when updating an agent's prompt or tools.
- As the Orchestrator, I need all my peer agents to be properly formatted so the underlying Antigravity runtime can load their system prompts successfully.

## Requirements
- **Directory Scan**: The swarm MUST scan the `.agents/agents/` directory and identify any agent subdirectories utilizing the legacy format (`agent.json` or `system_prompt.md`).
- **Consolidation**: For each legacy agent, the metadata within `agent.json` (e.g., name, description, model, tools) MUST be extracted and converted into YAML frontmatter at the top of a new `agent.md` file.
- **Prompt Migration**: The raw instructions contained within the legacy `system_prompt.md` MUST be appended directly beneath the YAML frontmatter in the new `agent.md` file.
- **Cleanup**: The legacy `agent.json` and `system_prompt.md` files MUST be permanently deleted to prevent runtime conflicts.

## Out of Scope
- Altering the actual instructions or toolsets of the agents during the migration (this is purely a format conversion).

## Acceptance Criteria
1. Every directory within `.agents/agents/` contains only an `agent.md` file defining the agent.
2. All `agent.md` files possess valid YAML frontmatter and retain their full system instructions.
3. No `agent.json` or `system_prompt.md` files remain in the `.agents/agents/` tree.
