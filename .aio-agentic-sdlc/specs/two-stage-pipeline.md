# Two-Stage Pipeline Epic: Implementation Plan

## 1. Overview
The Two-Stage Pipeline aims to split the requirements gathering and architectural design phases into two distinct steps. The Intake Agent will solely be responsible for writing Product Requirement Documents (PRDs) into an `.aio-agentic-sdlc/inbox/` directory. The Architect Agent will then process these PRDs during the `plan` phase, mapping them to the `.aio-agentic-sdlc/intention-dag.yaml` and moving them to `.aio-agentic-sdlc/specs/`.

## 2. Structural Implementation Steps

### Step 1: Intake Agent Refactor (Completed)
- **File to Update:** `.agents/agents/sdlc_intake/system_prompt.md`
- **Changes:**
  - Removed permissions to modify `.aio-agentic-sdlc/intention-dag.yaml`.
  - Updated the objective to focus on acting as a Product Manager.
  - Specified that output should be written as Markdown PRDs into the `.aio-agentic-sdlc/inbox/` directory.

### Step 2: Update `.aio-agentic-sdlc/intention-dag.yaml` (Completed)
- **File to Update:** `.aio-agentic-sdlc/intention-dag.yaml`
- **Changes:**
  - Updated `sdlc-intake-agent` description.
  - Added `sdlc-architect-agent` node as a core agent responsible for reading PRDs from `.aio-agentic-sdlc/inbox/` and updating the DAG.
  - Added `inbox-directory` entity.
  - Added edges mapping the intake agent writing to the inbox and the architect agent reading from it.

### Step 3: Architect Subagent Setup
- **Action:** Create the `sdlc_architect` agent definition.
- **Files to Create/Update:**
  - `.agents/agents/sdlc_architect/system_prompt.md` (or equivalent location)
- **Prompt Details:**
  - Define the persona as a Technical Architect.
  - Objective: Read PRDs from `.aio-agentic-sdlc/inbox/`, perform technical research, map requirements into architectural nodes in `.aio-agentic-sdlc/intention-dag.yaml`, and move the processed PRDs to `.aio-agentic-sdlc/specs/`.
  - Allowed tools: Reading PRDs, updating DAG files, and moving files.

### Step 4: CLI `plan` Refactor
- **File to Update:** `src/aio_agentic_sdlc/cli.py` (specifically `plan_cmd`)
- **Changes:**
  1. Add logic to check if `.aio-agentic-sdlc/inbox/` directory exists and has any Markdown files.
  2. If files exist:
     - Programmatically invoke the `sdlc_architect` subagent.
     - Provide the subagent with the list of files in `.aio-agentic-sdlc/inbox/`.
     - The subagent will process each file, update `.aio-agentic-sdlc/intention-dag.yaml`, and move the files to `.aio-agentic-sdlc/specs/`.
  3. Once the `.aio-agentic-sdlc/inbox/` is completely processed (or if it was empty initially):
     - Instantiate the `DiffingEngine` (as currently done).
     - Compute the differences between `.aio-agentic-sdlc/intention-dag.yaml` and `.aio-agentic-sdlc/reality-dag.yaml`.
     - Print the Execution Backlog (diff) to the terminal.

### Step 5: Verify CLI `apply` command
- **File to Review:** `src/aio_agentic_sdlc/cli.py` and `src/aio_agentic_sdlc/orchestrator_loop.py`
- **Changes:** No functional changes required for `apply`. It will execute the calculated diff as usual.

## 3. Future Considerations
- Adding robust error handling when the architect subagent encounters conflicting PRDs.
- Emitting standard logging messages during the `plan` step to notify the user of architect activities.
