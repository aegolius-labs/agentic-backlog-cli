---
document_type: prd
title: "Migrate the MCP Integration to Python SDK v2"
author: "Felix / Codex"
date: "2026-08-20"
status: "Valid - Unprocessed"
---
# Migrate the MCP Integration to Python SDK v2

## 1. Introduction

Migrate the AIO Agentic SDLC MCP server from the official Python SDK v1 compatibility line to stable SDK v2 while preserving the Codex plugin stdio contract and the existing public tools, resources, and prompts.

## 2. Objectives

- Adopt the official stable MCP Python SDK v2 and MCPServer API.
- Preserve all existing MCP names, schemas, behavior, and stdio startup.
- Validate the complete public surface through the real v2 in-memory Client in modern and legacy modes.
- Prove stateful synchronous handlers remain deterministic and thread-safe under v2 worker-thread concurrency.

## 3. Scope

- Update the MCP dependency constraint and UV lock to a supported 2.x release while excluding unsupported future majors.
- Port the server construction/imports to MCPServer without changing business logic.
- Add protocol-level contract tests for tools, resources, prompts, schemas, errors, and URI handling.
- Add focused concurrency tests around backlog, workspace migration, mapping approval, locks, path resolution, and working-directory independence.
- Update plugin and installation documentation and regenerate canonical Reality/reconciliation evidence.

## 4. Requirements

1. A clean frozen UV sync installs MCP 2.x and cannot resolve MCP 1.x or an unsupported future major.
2. The existing aio-agentic-sdlc-mcp entry point continues serving over stdio with the same public tool, resource, and prompt names.
3. A v2 Client in auto mode discovers and exercises the server; a legacy-mode client can connect and use the preserved contract.
4. Every synchronous stateful handler is safe when v2 executes calls concurrently in worker threads; no workspace, lock, cwd, audit, or backlog corruption is permitted.
5. Invalid inputs, invalid output schemas, unsafe URIs/paths, and server errors fail closed with stable protocol-visible semantics.
6. Direct function tests may remain for unit isolation, but protocol-level client tests are the acceptance authority.

## 5. User Stories

- As a Codex user, I can install and run the plugin after an ordinary dependency resolve without the MCP server crashing on a removed import.
- As a maintainer, I can call every published MCP operation through the real SDK client and know schemas match the wire contract.
- As a repository owner, concurrent agent calls cannot corrupt canonical local state.
- As a legacy MCP host user, I can still connect while migrating to the current protocol.

## 6. Success Metrics

- All published tools, resources, and prompts are listed and exercised through MCP Client.
- Modern and legacy client contract suites pass on Windows and CI.
- Focused concurrent state-mutation tests pass repeatedly without stale writes, split audit history, cwd leakage, or lock violations.
- Full warning-strict tests, static checks, package build, plugin/skill validators, and canonical evidence reproduction pass.
- pyproject excludes future unsupported majors and uv.lock records the reviewed SDK release.

## 7. Dependencies

- Official MCP Python SDK 2.0.0 stable line and its exact locked transitive dependencies, including mcp-types and httpx2.
- Existing transactional workspace, backlog, mapping, and DAG lock contracts.
- Codex plugin UV/stdio launcher.

## 8. Non-Functional Requirements

- Python 3.10+ and Windows support remain intact.
- No weakening of path, symlink/reparse-point, locking, atomic-write, or provenance protections.
- Public JSON schemas and error outcomes remain deterministic and bounded.
- The migration must not introduce an alternate MCP framework dependency or a second state authority.

## 9. Out of Scope

- Adding new MCP product capabilities such as HTTP deployment, authentication, subscriptions, sampling, elicitation, or resolver dependencies.
- Renaming public tools/resources/prompts or changing their product behavior.
- Removing legacy-protocol compatibility.
- Allowing unbounded future MCP major upgrades.

## 10. Viability Research

The official SDK declares v2.0.0 stable and identifies MCPServer as the FastMCP replacement. Decorator-built tools, resources, and prompts remain supported.

The migration guide identifies worker-thread execution for synchronous handlers, stricter schema/result validation, RFC 6570 URI handling, and the first-class in-memory Client with auto and legacy modes as the primary compatibility risks.

Sources:

- [Official v2 overview](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md)
- [Official migration guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md)
- [MCP 2.0.0 on PyPI](https://pypi.org/project/mcp/2.0.0/)

## 11. Changelog

- 2026-08-20: Initial approved migration PRD compiled from the recovery roadmap, user authorization, and official SDK v2 documentation.
