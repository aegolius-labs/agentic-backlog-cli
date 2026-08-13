# Specification: Canonical GUID Traceability & Mappings

## 1. Overview
To ensure deterministic, stack-agnostic mapping between architecture and implementation in the AIO-Agentic-SDLC framework, this feature enforces the ecosystem-wide adoption of strict Node IDs (UUIDs). This guarantees full traceability across the Intention DAG, Reality DAG, specifications, and source code.

## 2. Core Architecture
* **Intention Owns the ID:** The Intention DAG (`.aio-agentic-sdlc/intention-dag.yaml`) is the absolute source of truth for all node UUIDs.
* **Codebase Mappings (Tree-sitter):** The Node IDs are embedded in code files using language-specific comments (e.g., `# aio-sdlc-node: <uuid>` in Python, `// aio-sdlc-node: <uuid>` in TypeScript/Go). This stack-agnostic approach avoids reliance on language-specific features like decorators.
* **Agent Definitions (PyYAML):** For agent configurations (`.md`), Node IDs are embedded in the YAML frontmatter to prevent polluting the prompt context.

## 3. Implementation Details

### 3.1 Comment Extraction Strategy
Instead of brittle regex parsing over the entire file, the system utilizes **Tree-sitter** for accurate parsing:
1. Parse the source code into an AST using the appropriate Tree-sitter grammar.
2. Execute a universal query `(comment) @comment` to extract all comment nodes.
3. Apply regex (e.g., `r'#\s*aio-sdlc-node:\s*([a-f0-9\-]+)'`) exclusively over the extracted comment texts.

### 3.2 YAML Frontmatter Extraction Strategy
**PyYAML** is used to extract frontmatter safely:
1. Ensure the markdown content starts with `---`.
2. Split the document safely by `---` with a maximum split count of 2.
3. Parse the isolated frontmatter string using `yaml.safe_load()`.
4. Retrieve the `node_id` value from the parsed dictionary.

## 4. DAG Updates
A new component, `Canonical GUID Extractor`, is introduced into the core domain. It orchestrates the extraction logic by consuming the `Tree-Sitter Parser` and the `Markdown Parser` and feeding the extracted IDs to the `Reality DAG Generator`.
