# Product Requirement Document (PRD)

## Feature
Customizable Agent Personas & Personalities

## Summary
To make the agentic framework more engaging and tailored to user preferences, this feature allows users to configure persistent names and custom personalities for human-facing agents (like the Intake Agent and the Orchestrator). By injecting these traits into the agents' system prompts, the user experience transforms from interacting with a rigid CLI into collaborating with a personalized, recognizable virtual team.

## User Stories
- As a user, I want to assign specific, persistent names to the agents I chat with so that my workspace feels more familiar and conversational.
- As a user, I want to define a "personality" setting (e.g., "British English and extra polite" or "Very short, direct sentences") so that I can control the tone, dialect, and verbosity of the AI's responses to fit my working style.

## Requirements
- **Configuration Schema**: Expand the new `.aio-agentic-sdlc/config.json` configuration file to include an `agents.personas` block. It MUST support `name` and `personality` string fields for user-facing agents (e.g., `intake` and `orchestrator`).
- **Dynamic Prompt Injection**: The framework MUST read these fields at boot and dynamically inject them into the respective agent's base system prompt (e.g., `"Your name is {name}. {personality}"`).
- **Defaults**: If the persona block is missing or fields are omitted from the config, the framework MUST fall back to generic, professional defaults (e.g., Name: "Intake Agent", Personality: "Helpful, concise, and professional").

## Out of Scope
- Applying personas or personalities to headless background "implementation swarms" or QA agents that do not interact with the user via chat.
- Complex stateful memories about the user's personal life (this is strictly regarding the agent's output style and name).

## Acceptance Criteria
1. The framework successfully parses the `name` and `personality` fields from `.aio-agentic-sdlc/config.json`.
2. When a user interacts with the configured agent in the CLI, the agent introduces itself using the custom name.
3. The agent's generated text strongly adheres to the linguistic traits, tone, or constraints defined in the custom personality string.
