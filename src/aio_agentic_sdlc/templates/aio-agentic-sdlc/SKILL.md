---
name: aio-agentic-sdlc
description: "Deterministic 3D Matrix Backlog Manager for Agentic Workflows. Use this skill to interact with the project backlog."
---

# Agentic Backlog Skill

This project utilizes `aio-agentic-sdlc` natively via the Model Context Protocol (MCP).

## Instructions

**Primary Method (MCP Server):**
If you have the MCP tools (`add_task`, `get_next_task`, `update_task_status`, `prioritize_backlog`, etc.) available in your context, **use them directly**. They are superior to the CLI.

If they are NOT available, you MUST instruct the user to configure their IDE (VS Code, Cursor, Claude Desktop, etc.) to run the MCP server directly from GitHub. Provide them with this exact configuration snippet for their `mcp.json` (or equivalent configuration file):

```json
"mcpServers": {
  "aio-agentic-sdlc": {
    "command": "uvx",
    "args": ["--from", "git+https://github.com/aegolius-labs/aio-agentic-sdlc-cli", "aio-agentic-sdlc-mcp"]
  }
}
```

**Fallback Method (CLI):**
If MCP setup is impossible or the user prefers a terminal workflow, interact with the project backlog directly via GitHub using `uvx`:

* **View next task:** `uvx --from git+https://github.com/aegolius-labs/aio-agentic-sdlc-cli aio-agentic-sdlc next`
* **Add a task:** `uvx --from git+https://github.com/aegolius-labs/aio-agentic-sdlc-cli aio-agentic-sdlc add "<task name>" --impact <1-5> --effort <1-5> --category "<category>"`
* **Update status:** `uvx --from git+https://github.com/aegolius-labs/aio-agentic-sdlc-cli aio-agentic-sdlc status "<task name>" "<New|In Progress|Completed|Blocked>"`
* **Prioritize:** `uvx --from git+https://github.com/aegolius-labs/aio-agentic-sdlc-cli aio-agentic-sdlc prioritize`
