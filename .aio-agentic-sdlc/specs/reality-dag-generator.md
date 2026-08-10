# Reality DAG Generator Specification

## 1. Core Strategy & Tooling
To guarantee safety and prevent side effects from executing untrusted code, the generator will primarily use **Static Analysis**.

| Tool | Purpose |
| --- | --- |
| **tree-sitter (Multi-language AST parsing)** | Ideal for high-level structure extraction (modules, classes, functions, docstrings) and accurate import resolution. |
| **LSIF / tree-sitter queries (Deep semantic/call-graph inspection)** | Used for deep inspection (e.g., call graphs, dependency injection, and decorator extraction). |
| **Static OpenAPI Spec Ingestion / Generic Annotation Scanning** | For precision with `endpoint` and `entity` nodes, an optional sandboxed process can import the Web framework / API server to dump its OpenAPI schema natively. |

## 2. Ontology Mapping Strategy
The Reality DAG Generator maps source code elements to the Intention DAG ontology:

| Intention DAG Node | Source Code Mapping |
| --- | --- |
| `system` | Root Project / Repository (from Config or Root folder name) |
| `container` | Deployable apps (API, workers) (from Configured top-level directories or heuristics) |
| `module` | Packages & source code files (from tree-sitter file/module nodes) |
| `component` | Core logic Classes/Functions (from tree-sitter class/struct queries) |
| `endpoint` | API Routes (from Language-agnostic annotation/decorator queries) |
| `entity` | Data Models (Generic ORM/Data struct detection via tree-sitter) |

## 3. Relationship (Edge) Inference Strategy
Edges in the Reality DAG represent relationships between structural elements:

| Edge Type | Inference Method |
| --- | --- |
| `contains` | Hierarchy (natively from file system paths and tree-sitter scope blocks and file system hierarchy) |
| `depends_on` | Imports & DI (from file-level imports and parameter Dependency Injection) |
| `calls` | Invocations (tree-sitter call expression queries / LSIF textDocument/references targeting known components) |
| `reads` / `writes` | DB/Model interactions (Analyzing ORM calls. Map data mutations on Entities to writes, queries to reads) |
| `implements` | Protocol matching (Linking endpoint functions to the logical Component that houses them, or ABC inheritance) |

## 4. Step-by-Step Build Instructions

### Step 1: Configuration Engine
- Define a `reality_config.yaml` to specify overrides: container boundaries, ignored directories, and domain mappings based on folder paths.

### Step 2: The Parsing Phase (Nodes)
- Initialize tree-sitter parser with language-specific grammar.
- Walk the tree to create `module` nodes.
- Classify classes into `entity` or `component`.
- Classify functions with routing decorators as `endpoint` nodes.

### Step 3: The Linking Phase (Edges)
- `contains`: Generate automatically based on nested structure.
- `depends_on`: Map module-level imports to target nodes.
- `calls`, `reads`, `writes`: Use LSIF for semantic references and tree-sitter for AST traversal. Map data mutations on Entities to writes, queries to reads.

### Step 4: Hybrid Enrichment (OpenAPI)
- If enabled, parse explicitly provided OpenAPI/Swagger specs statically.
- Reconcile endpoints and Data validation schemas / ORM models with statically extracted nodes.

### Step 5: Assembly & Validation
- Construct final graph in memory.
- Serialize to Intention DAG JSON/YAML format.
- Validate payload against `.aio-agentic-sdlc/specs/intention-dag-schema.md`.
- Output validated `.aio-agentic-sdlc/reality-dag.yaml`.
