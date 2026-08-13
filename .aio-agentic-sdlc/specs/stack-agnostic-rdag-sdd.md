# Software Design Document: Stack-Agnostic Reality DAG Generator

## 1. Introduction
The Reality DAG Generator is being refactored to remove hardcoded python dependencies, enabling a stack-agnostic, plugin-style architecture capable of parsing multiple languages using Tree-Sitter, alongside native Markdown frontmatter parsing.

## 2. Architecture Components

### 2.1 ParserFactory (Component)
A central factory responsible for resolving the appropriate parser for a given file based on its extension. 
- Maintains a registry of `.py`, `.ts`, `.md`, etc.
- Instantiates and returns the configured `FileParser`.

### 2.2 FileParser (Interface)
An abstract contract ensuring all parsers implement a standardized `parse(filepath)` returning an intermediate AST or directly yielding `DAGNode` objects.

### 2.3 TreeSitterParser (Component)
Wraps the `tree-sitter` and `tree_sitter_languages` libraries. 
- Dynamically loads language grammars.
- Parses source code into a standard Tree-Sitter AST.

### 2.4 MarkdownParser (Component)
Specialized parser for `.md` files.
- Scans files (specifically in `.agents/agents/`).
- Extracts YAML frontmatter.
- Maps configuration schemas into specialized `DAGNode` entities.

### 2.5 ASTVisitor (Module)
Abstract visitor and language-specific implementations (e.g., `PythonVisitor`, `MarkdownVisitor`).
- Traverses the AST produced by parsers.
- Translates language-specific syntax nodes into agnostic Reality DAG nodes (Classes, Functions, Modules).

## 3. Data Flow
1. **Discovery**: `RealityDAGGenerator` scans the codebase and identifies files.
2. **Resolution**: For each file, it queries `ParserFactory` for the correct parser.
3. **Parsing**: The file is parsed (via `TreeSitterParser` or `MarkdownParser`).
4. **Translation**: The resulting AST/Data is traversed by a specific `ASTVisitor`.
5. **Integration**: Discovered nodes and edges are merged into the global Reality DAG.

## 4. Implementation Steps
1. Create `src/core/parsers/` directory.
2. Implement `ParserFactory` and parser classes.
3. Implement `ASTVisitor` hierarchy.
4. Refactor `RealityDAGGenerator` to consume the factory instead of hardcoded `tree-sitter-python`.
5. Add unit tests for multi-language and markdown parsing.
