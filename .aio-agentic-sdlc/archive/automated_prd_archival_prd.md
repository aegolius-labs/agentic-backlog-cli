# Product Requirement Document (PRD): Automated PRD Archival

## 1. Overview
The AIO-Agentic-SDLC framework currently requires the SDLC Architect agent to manually move processed Product Requirement Documents (PRDs) from the `.aio-agentic-sdlc/inbox/` directory to the `.aio-agentic-sdlc/archive/` directory. This manual step is error-prone and adds unnecessary overhead to the agent's workflow. This project aims to automate the archival process using a deterministic, scripted step (e.g., via a CLI script or a dedicated MCP tool) that automatically archives PRDs once they have been successfully processed.

## 2. Goals & Objectives
- **Automate Archival:** Eliminate the need for the SDLC Architect agent to manually move files.
- **Ensure Determinism:** The archival process should be a predictable, reliable, and scripted step executed automatically after PRD processing.
- **Maintain State:** Ensure that `.aio-agentic-sdlc/inbox/` only contains pending PRDs and `.aio-agentic-sdlc/archive/` contains all successfully processed PRDs.

## 3. Scope
**In Scope:**
- Creation of a script or tool (CLI or MCP) to move a specified PRD from `.aio-agentic-sdlc/inbox/` to `.aio-agentic-sdlc/archive/`.
- Integration of this script/tool into the standard SDLC processing pipeline (e.g., triggered immediately after the Architect successfully parses and acts on the PRD).
- Error handling (e.g., what happens if the file doesn't exist, or if a file with the same name already exists in the archive).

**Out of Scope:**
- Changes to how PRDs are generated or read.
- Deletion of PRDs (they must be archived, not deleted).

## 4. Functional Requirements
- **F1 - File Movement:** The system shall provide a programmatic way to move a file from a source path (e.g., `.aio-agentic-sdlc/inbox/prd.md`) to a destination path (e.g., `.aio-agentic-sdlc/archive/prd.md`).
- **F2 - Auto-creation of Archive Directory:** If the `.aio-agentic-sdlc/archive/` directory does not exist, the system shall create it automatically before attempting to move the file.
- **F3 - Name Collision Handling:** If a file with the same name already exists in the `.aio-agentic-sdlc/archive/` directory, the system shall rename the incoming file (e.g., by appending a timestamp) to prevent overwriting.
- **F4 - Integration:** The archival step shall be triggerable by the framework's workflow orchestration (e.g., as a distinct step in `.aio-agentic-sdlc/intention-dag.yaml` or as part of a post-processing script).

## 5. Non-Functional Requirements
- **Reliability:** The script must reliably move the file without data loss.
- **Performance:** The file move operation should be nearly instantaneous.
- **Platform Agnosticism:** The script/tool should be compatible with the operating system running the framework (e.g., cross-platform Python script).

## 6. Acceptance Criteria
- A script or tool exists that takes a PRD filename/path as input and moves it to the `.aio-agentic-sdlc/archive/` directory.
- The `.aio-agentic-sdlc/archive/` directory is created if it does not exist.
- Processing a PRD through the pipeline automatically results in the PRD being moved to the `.aio-agentic-sdlc/archive/` directory without manual intervention from the SDLC Architect agent.
- Archiving a PRD with a name that already exists in `.aio-agentic-sdlc/archive/` does not overwrite the existing file.
