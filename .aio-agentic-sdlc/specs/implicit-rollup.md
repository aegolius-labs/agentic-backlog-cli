# Implicit Roll-up Traversal Algorithm

## Objective
Enhance the Diffing Engine to perform "Implicit Roll-up". When evaluating unmapped Reality nodes, the engine should determine if they are mere implementation details of higher-level components that *are* mapped in the Intention DAG. If so, they should be ignored rather than flagged for removal.

## Design

### 1. Identify Unmapped Reality Nodes
During the execution of `DiffingEngine.calculate_diff()`, we evaluate Extraneous Nodes (nodes present in Reality but absent in Intention). Currently, a "Remove" task is generated for every extraneous node. We will insert a gatekeeping mechanism to verify if the node is an implementation detail.

### 2. Lineage Traversal Algorithm (`_is_implementation_detail`)
Add a private helper method `_is_implementation_detail(self, node_id: str) -> bool` to the `DiffingEngine` class.

**Algorithm Steps:**
1. Initialize a `visited` set to track traversed node IDs and prevent infinite recursion (even though valid DAGs are acyclic, this is a safety measure).
2. Define a recursive inner function `check_ancestors(current_id: str) -> bool`.
3. Inside `check_ancestors`:
   - If `current_id` in `visited`, return `False`.
   - Add `current_id` to `visited`.
   - Find all parent nodes in the Reality DAG. This is done by querying reality edges for type `EdgeType.CONTAINS` where `target == current_id`. The parent node ID is the `source` of the edge.
   - For each parent ID:
     - Check if `parent_id` exists in `self.intention.nodes`. If it does, the current unmapped node is an implementation detail. Return `True`.
     - Otherwise, recursively call `check_ancestors(parent_id)`. If it returns `True`, propagate `True` upwards.
   - If no parents match and all recursive paths return `False`, return `False`.
4. Call `check_ancestors(node_id)` and return its result.

### 3. Modifying `calculate_diff()`
Update the Extraneous Nodes loop in `calculate_diff()` to use the new algorithm. Also, update the imports at the top of `diffing_engine.py` to include `EdgeType` from `aio_agentic_sdlc.dag_models`.

```python
# Updated imports
from aio_agentic_sdlc.dag_models import Node, Edge, EdgeType

# Extraneous Nodes Logic
for node_id, reality_node in self.reality.nodes.items():
    if node_id not in self.intention.nodes:
        # Implicit Roll-up Check
        if self._is_implementation_detail(node_id):
            continue # Treat as implementation detail, do not generate 'Remove' task
            
        task_name = f"Remove {reality_node.type.value.capitalize()} '{reality_node.name}'"
        # ... generate backlog item
```

## TDD Plan

The following test cases should be added to `tests/test_diffing_engine.py` to verify the Implicit Roll-up behavior.

### Test Case 1: Unmapped node with no parents
- **Setup**: Create an Intention DAG with node A. Create a Reality DAG with node A and an unmapped node B. Node B has no incoming CONTAINS edges.
- **Assertion**: Diff contains a "Remove" task for node B.

### Test Case 2: Unmapped node with an unmapped parent
- **Setup**: Create a Reality DAG with unmapped nodes B and C. Edge: `B -> CONTAINS -> C`. Intention DAG only has node A.
- **Assertion**: Diff contains a "Remove" task for both node B and node C.

### Test Case 3: Unmapped node with a mapped parent (Immediate Implementation Detail)
- **Setup**: Intention DAG has node A. Reality DAG has node A and unmapped node B. Edge: `A -> CONTAINS -> B`.
- **Assertion**: Diff does NOT contain a "Remove" task for node B.

### Test Case 4: Unmapped node with a mapped grandparent (Deep Implementation Detail)
- **Setup**: Intention DAG has node A. Reality DAG has node A, unmapped node B, and unmapped node C. Edges: `A -> CONTAINS -> B` and `B -> CONTAINS -> C`.
- **Assertion**: Diff does NOT contain a "Remove" task for either B or C.

### Test Case 5: Circular Dependency Resiliency
- **Setup**: Create a Reality DAG with unmapped nodes B, C, D. Edges: `B -> CONTAINS -> C`, `C -> CONTAINS -> D`, and `D -> CONTAINS -> B` (assuming mock edges bypassing strict DAG validation). No nodes mapped to Intention.
- **Assertion**: The function should safely return `False` without a recursion limit error, and Diff contains "Remove" tasks for B, C, and D.
