import heapq
import os

import yaml

from .config import load_config
from .state import load_backlog as _load_backlog
from .state import mutate_backlog as _mutate_backlog
from .state import save_backlog as _save_backlog
from .workspace import INTENTION_DAG_FILE, REALITY_DAG_FILE, SPECS_DIR

VALID_STATUSES = ("New", "In Progress", "Completed", "Blocked")


class BacklogOperationError(ValueError):
    """Raised for an expected, user-correctable backlog operation failure."""


def _get_status(item):
    return item.get("status", "New")


def _get_blockers(item):
    return item.get("blockers", [])


def validate_hierarchy(item_type, parent_id, data, project_path, *, config=None):
    if not item_type and not parent_id:
        return
    if config is None:
        config = load_config(project_path)
    hierarchy = config.get("hierarchy")
    if not hierarchy:
        hierarchy = {"1": ["Epic"], "2": ["Feature"], "3": ["Task", "Bug"]}

    level = None
    if item_type:
        for level_key, types in hierarchy.items():
            if item_type in types:
                level = int(level_key)
                break
        if level is None:
            raise BacklogOperationError(
                f"Invalid item_type '{item_type}'. Valid types: {hierarchy}"
            )

    if parent_id and parent_id in data.get("nodes", {}):
        parent_type = data["nodes"][parent_id].get("item_type", "Task")
        parent_level = None
        for level_key, types in hierarchy.items():
            if parent_type in types:
                parent_level = int(level_key)
                break
        if parent_level is None:
            parent_level = max([int(x) for x in hierarchy.keys()])

        validation_mode = config.get("core", {}).get("validation_mode", "flex")
        if level is not None:
            if validation_mode == "strict":
                if level != parent_level + 1:
                    raise BacklogOperationError(
                        f"Strict Mode Violation: Child '{item_type}' (Level {level}) must be exactly Parent '{parent_type}' (Level {parent_level}) + 1."
                    )
            else:
                if level <= parent_level:
                    raise BacklogOperationError(
                        f"Flex Mode Violation: Child '{item_type}' (Level {level}) must be > Parent '{parent_type}' (Level {parent_level})."
                    )


def load_backlog(project_path="."):
    return _load_backlog(project_path)


def save_backlog(data, project_path=".", *, operation="backlog.save"):
    return _save_backlog(data, project_path, operation=operation)


def get_edges(data, from_node=None, to_node=None, relation=None):
    return [
        e
        for e in data.get("edges", [])
        if (from_node is None or e["from"] == from_node)
        and (to_node is None or e["to"] == to_node)
        and (relation is None or e["relation"] == relation)
    ]


def get_requires(data, node):
    return [e["to"] for e in get_edges(data, from_node=node, relation="requires")]


def set_requires(data, node, reqs):
    data["edges"] = [
        e
        for e in data.get("edges", [])
        if not (e["from"] == node and e["relation"] == "requires")
    ]
    for r in reqs:
        data["edges"].append({"from": node, "to": r, "relation": "requires"})


def get_parent(data, node):
    edges = get_edges(data, from_node=node, relation="parent")
    return edges[0]["to"] if edges else None


def set_parent(data, node, parent_id):
    data["edges"] = [
        e
        for e in data.get("edges", [])
        if not (e["from"] == node and e["relation"] == "parent")
    ]
    if parent_id:
        data["edges"].append({"from": node, "to": parent_id, "relation": "parent"})


def ensure_dependencies(data, requires):
    warnings = []
    for req in requires:
        if req not in data.get("nodes", {}):
            warnings.append(
                f"Missing dependency '{req}' automatically created as AI-driven. Update its impact/effort soon!"
            )
            data["nodes"][req] = {
                "item_type": "Task",
                "impact": 1,
                "effort": 1,
                "category": "Nice-to-haves",
                "ai_driven": True,
                "status": "New",
                "blockers": [],
                "scores": {"base": 5, "final": 5},
            }
    return warnings


def _compute_sorted_items(nodes, edges):
    visited = set()
    temp_mark = set()
    order = []

    requires_map = {n: [] for n in nodes}
    for e in edges:
        if e["relation"] == "requires" and e["from"] in requires_map:
            requires_map[e["from"]].append(e["to"])

    def visit(n):
        if n in temp_mark:
            raise BacklogOperationError(
                f"Circular dependency detected involving [{n}]. Analyze items to clarify what genuinely depends on what."
            )
        if n not in visited:
            temp_mark.add(n)
            for dep in requires_map.get(n, []):
                if dep in nodes:
                    visit(dep)
            temp_mark.remove(n)
            visited.add(n)
            order.append(n)

    for node in nodes:
        if node not in visited:
            visit(node)

    for name, item in nodes.items():
        if _get_status(item) == "Completed":
            if "scores" not in item:
                item["scores"] = {}
            item["scores"]["base"] = 0
        else:
            base = item.get("impact", 1) + (5 - item.get("effort", 1))
            if "scores" not in item:
                item["scores"] = {}
            item["scores"]["base"] = base

    final_scores = {}
    for node in reversed(order):
        if _get_status(nodes[node]) == "Completed":
            final_scores[node] = 0
            nodes[node]["scores"]["final"] = 0
        else:
            base = nodes[node]["scores"].get("base", 0)
            dependents = [n for n in order if node in requires_map.get(n, [])]
            boost = 0.5 * sum(final_scores.get(d, 0) for d in dependents)
            final_scores[node] = base + boost
            nodes[node]["scores"]["final"] = final_scores[node]

    def get_cat_weight(cat):
        c = (cat or "").lower()
        if "security" in c:
            return 4
        if "reliability" in c:
            return 3
        if "business" in c:
            return 2
        return 1

    in_degree = {n: len(requires_map.get(n, [])) for n in nodes}
    adj = {n: [] for n in nodes}
    for n in nodes:
        for req in requires_map.get(n, []):
            if req in adj:
                adj[req].append(n)

    pq = []
    for n in nodes:
        if in_degree[n] == 0:
            heapq.heappush(
                pq,
                (
                    -nodes[n]["scores"].get("final", 0),
                    -get_cat_weight(nodes[n].get("category", "")),
                    n,
                ),
            )

    final_ordered_keys = []
    while pq:
        _, _, n = heapq.heappop(pq)
        final_ordered_keys.append(n)
        for dep in adj[n]:
            if dep in in_degree:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    heapq.heappush(
                        pq,
                        (
                            -nodes[dep]["scores"].get("final", 0),
                            -get_cat_weight(nodes[dep].get("category", "")),
                            dep,
                        ),
                    )

    return final_ordered_keys


def prioritize_items(project_path="."):
    def mutate(data):
        if not data.get("nodes"):
            return False, False

        nodes = data["nodes"]
        edges = data.get("edges", [])
        final_ordered_keys = _compute_sorted_items(nodes, edges)

        new_nodes = {k: nodes[k] for k in final_ordered_keys}
        data["nodes"] = new_nodes

        for item in new_nodes.values():
            if _get_blockers(item) and _get_status(item) != "Completed":
                item["status"] = "Blocked"
            elif _get_status(item) == "Blocked" and not _get_blockers(item):
                item["status"] = "New"
        return True, True

    return _mutate_backlog(
        project_path,
        operation="backlog.prioritize",
        mutator=mutate,
    )


def get_next_item(project_path="."):
    import copy

    data = load_backlog(project_path)
    if not data.get("nodes"):
        return None, "Backlog is empty."

    nodes = copy.deepcopy(data["nodes"])
    edges = copy.deepcopy(data.get("edges", []))
    try:
        ordered_keys = _compute_sorted_items(nodes, edges)
    except BacklogOperationError as e:
        return None, str(e)

    top_key = ordered_keys[0] if ordered_keys else None
    target_key = None
    for key in ordered_keys:
        item = nodes[key]
        if _get_status(item) != "Completed" and not _get_blockers(item):
            target_key = key
            break

    if target_key is None:
        return (
            None,
            "No workable items remain. All items are either completed or blocked.",
        )

    target_item = nodes[target_key]
    target_data = {
        "name": target_key,
        "item_type": target_item.get("item_type", "Task"),
        "impact": target_item.get("impact"),
        "effort": target_item.get("effort"),
        "category": target_item.get("category"),
        "description": target_item.get("description", ""),
        "status": _get_status(target_item),
        "blockers": _get_blockers(target_item),
        "requires": get_requires(data, target_key),
        "scores": target_item.get("scores", {}),
    }

    warning = None
    if top_key and top_key != target_key:
        top_item = nodes[top_key]
        if _get_status(top_item) not in ["Completed", "Done"]:
            top_blockers = _get_blockers(top_item)
            warning = f"Top item '{top_key}' has the highest priority but is blocked by: {top_blockers}"

    return target_data, warning


def add_item(
    name,
    impact,
    effort,
    category,
    description=None,
    requires=None,
    ai_driven=False,
    status="New",
    blockers=None,
    project_path=".",
    item_type="Task",
    parent_id=None,
):
    if not description or not str(description).strip():
        raise BacklogOperationError(
            "Description cannot be empty. Please provide a detailed description of the task."
        )

    config = load_config(project_path)

    def mutate(data):
        if name in data.get("nodes", {}):
            raise BacklogOperationError(f"Item '{name}' already exists.")

        validate_hierarchy(
            item_type,
            parent_id,
            data,
            project_path,
            config=config,
        )

        requires_list = [r.strip() for r in requires.split(",")] if requires else []
        warnings = ensure_dependencies(data, requires_list)
        blockers_list = [b.strip() for b in blockers.split(",")] if blockers else []

        data["nodes"][name] = {
            "item_type": item_type,
            "impact": impact,
            "effort": effort,
            "category": category,
            "description": description or "",
            "ai_driven": ai_driven,
            "status": status,
            "blockers": blockers_list,
            "scores": {},
        }
        set_requires(data, name, requires_list)
        set_parent(data, name, parent_id)
        return warnings, True

    return _mutate_backlog(project_path, operation="backlog.add", mutator=mutate)


def update_item(
    name,
    impact=None,
    effort=None,
    category=None,
    description=None,
    requires=None,
    ai_driven=None,
    status=None,
    blockers=None,
    project_path=".",
    item_type=None,
    parent_id=None,
):
    if description is not None and not str(description).strip():
        raise BacklogOperationError(
            "Description cannot be empty. Please provide a detailed description of the task."
        )

    def mutate(data):
        if name not in data.get("nodes", {}):
            raise BacklogOperationError(f"Item '{name}' not found.")

        item = data["nodes"][name]
        warnings = []

        if item_type is not None:
            item["item_type"] = item_type
        if impact is not None:
            item["impact"] = impact
        if effort is not None:
            item["effort"] = effort
        if category is not None:
            item["category"] = category
        if requires is not None:
            requires_list = [r.strip() for r in requires.split(",")] if requires else []
            warnings = ensure_dependencies(data, requires_list)
            set_requires(data, name, requires_list)
        if ai_driven is not None:
            item["ai_driven"] = ai_driven
        if status is not None:
            item["status"] = status
        if description is not None:
            item["description"] = description
        if blockers is not None:
            blockers_list = [b.strip() for b in blockers.split(",")] if blockers else []
            item["blockers"] = blockers_list
        if parent_id is not None:
            set_parent(data, name, parent_id)
        return warnings, True

    return _mutate_backlog(project_path, operation="backlog.update", mutator=mutate)


def set_status(name, new_status, project_path="."):
    def mutate(data):
        if name not in data.get("nodes", {}):
            raise BacklogOperationError(f"Item '{name}' not found.")
        data["nodes"][name]["status"] = new_status
        return None, True

    return _mutate_backlog(
        project_path,
        operation="backlog.set-status",
        mutator=mutate,
    )


def add_blocker(name, reason, project_path="."):
    def mutate(data):
        if name not in data.get("nodes", {}):
            raise BacklogOperationError(f"Item '{name}' not found.")
        item = data["nodes"][name]
        blockers = _get_blockers(item)
        if reason not in blockers:
            blockers.append(reason)
        item["blockers"] = blockers
        if _get_status(item) != "Completed":
            item["status"] = "Blocked"
        return None, True

    return _mutate_backlog(
        project_path,
        operation="backlog.add-blocker",
        mutator=mutate,
    )


def remove_blocker(name, reason, project_path="."):
    def mutate(data):
        if name not in data.get("nodes", {}):
            raise BacklogOperationError(f"Item '{name}' not found.")
        item = data["nodes"][name]
        blockers = _get_blockers(item)
        if reason in blockers:
            blockers.remove(reason)
        item["blockers"] = blockers
        if not blockers and _get_status(item) == "Blocked":
            item["status"] = "New"
        return None, True

    return _mutate_backlog(
        project_path,
        operation="backlog.remove-blocker",
        mutator=mutate,
    )


def remove_item(name, project_path="."):
    def mutate(data):
        if name not in data.get("nodes", {}):
            raise BacklogOperationError(f"Item '{name}' not found.")

        data["edges"] = [
            edge
            for edge in data.get("edges", [])
            if edge["from"] != name and edge["to"] != name
        ]
        del data["nodes"][name]

        for item in data["nodes"].values():
            if "blockers" in item and name in item["blockers"]:
                item["blockers"].remove(name)
        return None, True

    return _mutate_backlog(project_path, operation="backlog.remove", mutator=mutate)


# aio-sdlc-mapping-approval: {"candidate_reality_id":"4332ee05-cded-51dc-b884-7249af9d97cd","identity_approval":{"approved_at":"2026-08-13T19:29:14.286017-04:00","approved_by":"Felix","candidate_reality_id":"4332ee05-cded-51dc-b884-7249af9d97cd","evidence_digest":"785fb78003c07acecef12413f387caffdf6eb17b2676b55ee734a51006195c08","intent_id":"685b1d12-3eed-48f6-9fa8-b8ec88a5587f","rationale":"Approved the TraceabilityValidator source identity; responsibility and validate API match, without claiming behavioral verification.","schema_version":1,"source_path":"src/aio_agentic_sdlc/core.py","source_sha256":"89b340f7032a84e0c9e7f032814ee15441ed06d4e4409e8d3d790ed6585faa2d","symbol_kind":"class","symbol_name":"TraceabilityValidator"},"intent_id":"685b1d12-3eed-48f6-9fa8-b8ec88a5587f","maintenance_approval":{"approved_at":"2026-08-21T23:03:05.512658-04:00","approved_by":"Felix","evidence_digest":"b4abf4522e3c6ec90c755dbcf4b4034bb7149d5591b525a8815cb69f6c6514d3","rationale":"Felix approved refreshing the existing TraceabilityValidator mapping receipt to bind current source after unrelated same-file changes; identity remains unchanged and legacy Intent completeness remains unresolved.","supersedes_receipt_sha256":"98141c7e83e1fd3c82ea6b0002a67d349a430af3b81b43033568287a3d00e639"},"schema_version":2,"source_path":"src/aio_agentic_sdlc/core.py","source_sha256":"815994a1ffd8e4d25a6b778096d76afd15a63ba3f57cea214bde1f7821e4ef59","symbol_kind":"class","symbol_name":"TraceabilityValidator"}
# aio-sdlc-node: 685b1d12-3eed-48f6-9fa8-b8ec88a5587f
class TraceabilityValidator:
    def __init__(
        self,
        intention_path=INTENTION_DAG_FILE,
        reality_path=REALITY_DAG_FILE,
        specs_dir=SPECS_DIR,
        code_dir="src",
    ):
        self.intention_path = intention_path
        self.reality_path = reality_path
        self.specs_dir = specs_dir
        self.code_dir = code_dir

    def validate(self):
        errors = []
        intention_ids = self._get_dag_ids(self.intention_path)
        reality_ids = self._get_dag_ids(self.reality_path)

        # 1. Intention vs Reality
        if os.path.exists(self.reality_path):
            for i_id in intention_ids:
                if i_id not in reality_ids:
                    errors.append(
                        f"Traceability Error: Intention Node {i_id} is missing in Reality DAG."
                    )

            for r_id in reality_ids:
                if r_id not in intention_ids:
                    errors.append(
                        f"Traceability Error: Reality Node {r_id} is missing in Intention DAG."
                    )

        # 2. Specs linkage
        if os.path.exists(self.specs_dir):
            for filename in os.listdir(self.specs_dir):
                if filename.endswith(".md"):
                    filepath = os.path.join(self.specs_dir, filename)
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                        found = any(i_id in content for i_id in intention_ids)
                        if not found and intention_ids:
                            errors.append(
                                f"Traceability Error: Spec {filename} does not reference any known Node ID."
                            )

        return errors

    def _get_dag_ids(self, path):
        if not os.path.exists(path):
            return set()
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            nodes = data.get("nodes", [])
            return {
                str(n.get("id")) for n in nodes if isinstance(n, dict) and "id" in n
            }
