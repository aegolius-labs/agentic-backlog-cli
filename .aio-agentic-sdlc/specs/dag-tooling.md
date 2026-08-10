# DAG Tooling Specification

## 1. Overview & Purpose
In accordance with the `dag-integrity` rule, manual edits to the Intention DAG and Reality DAG files are strictly prohibited. To support automated, safe, and schema-compliant modifications, this specification outlines the design of a Python SDK and corresponding CLI tool for managing DAG state files.

The tooling ensures that:
- Structural changes strictly adhere to the `intention-dag-schema.md`.
- Constraints (e.g., acyclic dependencies, hierarchical composition) are validated.
- Read, write, and manipulate operations are atomic and safe.

## 2. Python SDK Design

### 2.1 Core Data Models (Pydantic / Dataclasses)

Using `pydantic` for automatic schema validation is recommended.

```python
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class NodeType(str, Enum):
    SYSTEM = "system"
    CONTAINER = "container"
    MODULE = "module"
    COMPONENT = "component"
    ENDPOINT = "endpoint"
    ENTITY = "entity"

class EdgeType(str, Enum):
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    CALLS = "calls"
    PUBLISHES = "publishes"
    SUBSCRIBES = "subscribes"
    READS = "reads"
    WRITES = "writes"
    IMPLEMENTS = "implements"

class Metadata(BaseModel):
    name: str
    version: str

class Node(BaseModel):
    id: str
    type: NodeType
    name: str
    domain: Optional[str] = None
    description: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None

class Edge(BaseModel):
    source: str
    target: str
    type: EdgeType
    description: Optional[str] = None
```

### 2.2 The `DAG` Manager Class

The core class to handle loading, validating, manipulating, and saving DAGs.

```python
class DAGManager:
    def __init__(self, metadata: Metadata, nodes: List[Node], edges: List[Edge]):
        self.metadata = metadata
        self.nodes = {n.id: n for n in nodes}
        self.edges = edges  # List, or a more optimized graph structure

    # --- IO Operations ---
    @classmethod
    def load(cls, filepath: str) -> "DAGManager":
        """Loads a YAML/JSON file, parses it, and validates against the schema."""
        pass

    def save(self, filepath: str):
        """Serializes the current state to YAML/JSON and writes safely to disk."""
        pass

    # --- Validation ---
    def validate(self):
        """
        Runs constraint checks:
        1. All edge sources and targets exist in nodes.
        2. 'contains' edges form a strict tree (no cycles, single parent).
        3. 'depends_on' and 'calls' form a Directed Acyclic Graph.
        """
        pass

    # --- Node Manipulation ---
    def add_node(self, node: Node):
        """Adds a new node. Raises error if ID already exists."""
        pass

    def update_node(self, node_id: str, **kwargs):
        """Updates attributes of an existing node."""
        pass

    def remove_node(self, node_id: str):
        """Removes a node and gracefully removes/cascades all edges connected to it."""
        pass

    def get_node(self, node_id: str) -> Node:
        pass

    def find_nodes(self, **filters) -> List[Node]:
        """Finds nodes matching specific properties (e.g., domain='catalog')."""
        pass

    # --- Edge Manipulation ---
    def add_edge(self, edge: Edge):
        """Adds an edge. Validates constraints before applying."""
        pass

    def remove_edge(self, source: str, target: str, edge_type: EdgeType):
        """Removes a specific edge."""
        pass

    def get_edges(self, source: str = None, target: str = None, edge_type: EdgeType = None) -> List[Edge]:
        """Queries edges based on filters."""
        pass
```

### 2.3 Constraint Checking Logic
- **Reference Integrity**: Before adding an edge, verify `source in self.nodes` and `target in self.nodes`.
- **Acyclic Check**: Implement a Topological Sort or Depth-First Search (DFS) cycle-detection algorithm specifically for `depends_on`, `calls`, and `contains` edge types.

## 3. CLI Tool Design (`dag-tool`)

A CLI wrapper around the Python SDK, using `click` or `argparse`, to allow shell scripts and agents to manipulate DAGs safely.

### 3.1 Global Options
- `--file <path>` (Required): Path to the `.aio-agentic-sdlc/intention-dag.yaml` or `.aio-agentic-sdlc/reality-dag.yaml`.
- `--format <json|yaml>`: Explicitly specify format, defaults to YAML.

### 3.2 Commands

#### Validation
```bash
dag-tool validate --file .aio-agentic-sdlc/intention-dag.yaml
```
*Exits with code 0 if valid, >0 with error details if invalid.*

#### Node Operations
```bash
# Add a node
dag-tool node add --file .aio-agentic-sdlc/intention-dag.yaml --id "user-db" --type "container" --name "User Database" --domain "users"

# Update a node
dag-tool node update --file .aio-agentic-sdlc/intention-dag.yaml --id "user-db" --description "Postgres database for users"

# Remove a node (will also remove edges connecting to it)
dag-tool node remove --file .aio-agentic-sdlc/intention-dag.yaml --id "user-db"

# List nodes (can filter by type/domain, outputs JSON for pipelining)
dag-tool node list --file .aio-agentic-sdlc/intention-dag.yaml --domain "users" --output json
```

#### Edge Operations
```bash
# Add an edge
dag-tool edge add --file .aio-agentic-sdlc/intention-dag.yaml --source "user-api" --target "user-db" --type "reads"

# Remove an edge
dag-tool edge remove --file .aio-agentic-sdlc/intention-dag.yaml --source "user-api" --target "user-db" --type "reads"
```

## 4. Implementation Plan

1. **Bootstrap Project**: Initialize Python project with `pydantic`, `pyyaml`, and `click`.
2. **Models & Schema**: Implement `NodeType`, `EdgeType`, `Node`, `Edge`, and `Metadata` models with Pydantic validation mapping to `.aio-agentic-sdlc/specs/intention-dag-schema.md`.
3. **Graph Engine (`DAGManager`)**:
   - Implement `load()` and `save()` wrappers handling YAML.
   - Implement graph cycle detection (DFS-based) for acyclic constraint enforcement.
4. **CRUD Methods**: Implement node and edge manipulation logic.
5. **CLI Wrapping**: Hook CLI commands to `DAGManager` functions.
6. **Testing**: Write unit tests for cycle detection, reference integrity, and invalid modifications.
