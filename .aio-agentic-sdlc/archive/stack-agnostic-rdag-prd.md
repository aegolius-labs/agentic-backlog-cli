# Product Requirement Document: Stack-Agnostic Reality DAG Generator

## 1. Overview
The `RealityDAGGenerator` currently hardcodes the `tree-sitter-python` binding and restricts file parsing strictly to `.py` files. This violates the core design principle that the AIO-Agentic-SDLC framework must be stack-agnostic. 

## 2. Goals & Objectives
* Refactor the Reality DAG Generator to support a multi-language, plugin-style architecture.
* Replace hardcoded python checks with a robust language detection strategy.
* Specifically implement a parser for `.md` files that extracts YAML frontmatter to support mapping Agent configurations (e.g. in `.agents/agents/`) into the Reality DAG.

## 3. Core Requirements
1. **Tree-Sitter Language Factory:** The generator must dynamically load Tree-Sitter grammars based on file extension rather than hardcoding python.
2. **Markdown / Agent Support:** The system must scan the `.agents/agents/` directory (or `.md` files globally), parse YAML frontmatter, and instantiate corresponding `DAGNode` objects for agents, tools, etc.
3. **Extensibility:** The architecture must make it trivial to add support for TypeScript, Go, Rust, or other languages in the future.

## 4. Pipeline Execution Instructions
* **Research Phase:** The Architect MUST spawn the `sdlc_researcher` to draft a Research Spike on the best design patterns for multi-language Tree-Sitter support in Python, and how to effectively structure the visitor pattern for heterogeneous file types.
* **Architecture Phase:** The Architect must map the necessary components to `.aio-agentic-sdlc/intention-dag.yaml` and draft an explicit Software Design Document (SDD) in `.aio-agentic-sdlc/specs/`.
