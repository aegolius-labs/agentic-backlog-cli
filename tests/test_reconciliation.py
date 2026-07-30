import copy

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Metadata, Node, NodeType
from aio_agentic_sdlc.diffing_engine import DiffingEngine, DiffPolicy
from aio_agentic_sdlc.reconciliation import ReconciliationEngine


def _dag(nodes):
    return DAGManager(Metadata(name="Test", version="1.0"), nodes, [])


def _node(node_id, node_type, name):
    return Node(id=node_id, type=node_type, name=name)


def test_reconciliation_classifies_identity_without_inventing_mappings():
    confirmed_id = "00000000-0000-0000-0000-000000000001"
    unique_intent_id = "00000000-0000-0000-0000-000000000002"
    unique_reality_id = "00000000-0000-0000-0000-000000000102"
    ambiguous_intent_id = "00000000-0000-0000-0000-000000000003"
    unmatched_intent_id = "00000000-0000-0000-0000-000000000004"

    intention = _dag(
        [
            _node(confirmed_id, NodeType.COMPONENT, "Confirmed"),
            _node(unique_intent_id, NodeType.COMPONENT, "Diffing Engine"),
            _node(ambiguous_intent_id, NodeType.COMPONENT, "Worker"),
            _node(unmatched_intent_id, NodeType.ENTITY, "Configuration"),
        ]
    )
    reality = _dag(
        [
            _node(confirmed_id, NodeType.COMPONENT, "Renamed Confirmed"),
            _node(unique_reality_id, NodeType.COMPONENT, "DiffingEngine"),
            _node(
                "00000000-0000-0000-0000-000000000103",
                NodeType.COMPONENT,
                "Worker",
            ),
            _node(
                "00000000-0000-0000-0000-000000000104",
                NodeType.COMPONENT,
                "worker",
            ),
            _node(
                "00000000-0000-0000-0000-000000000105",
                NodeType.COMPONENT,
                "Configuration",
            ),
        ]
    )
    before_intention = copy.deepcopy(intention)
    before_reality = copy.deepcopy(reality)

    report = ReconciliationEngine(intention, reality).analyze(max_items=100)

    by_intent = {
        item["intent"]["id"]: item
        for item in report["items"]
        if item["subject_kind"] == "intent"
    }
    assert by_intent[confirmed_id]["classification"] == "confirmed"
    assert by_intent[confirmed_id]["requires_approval"] is False
    assert by_intent[confirmed_id]["evidence"] == [
        {"kind": "canonical_guid", "value": confirmed_id}
    ]

    candidate = by_intent[unique_intent_id]
    assert candidate["classification"] == "candidate"
    assert candidate["requires_approval"] is True
    assert [node["id"] for node in candidate["reality_candidates"]] == [
        unique_reality_id
    ]
    assert candidate["evidence"] == [
        {
            "kind": "normalized_name_and_type",
            "normalized_name": "diffingengine",
            "node_type": "component",
        }
    ]

    ambiguous = by_intent[ambiguous_intent_id]
    assert ambiguous["classification"] == "ambiguous"
    assert len(ambiguous["reality_candidates"]) == 2
    assert by_intent[unmatched_intent_id]["classification"] == "unmapped"

    assert report["summary"] == {
        "intention_nodes": 4,
        "reality_nodes": 5,
        "confirmed": 1,
        "candidate": 1,
        "ambiguous": 1,
        "unmapped": 1,
        "unclassified_reality": 4,
    }
    assert intention.nodes == before_intention.nodes
    assert intention.edges == before_intention.edges
    assert reality.nodes == before_reality.nodes
    assert reality.edges == before_reality.edges


def test_reconciliation_output_is_deterministic_and_bounded_without_hiding_totals():
    intention = _dag(
        [
            _node(
                f"00000000-0000-0000-0000-00000000000{index}",
                NodeType.COMPONENT,
                f"Intent {index}",
            )
            for index in range(1, 5)
        ]
    )
    reality = _dag([])
    engine = ReconciliationEngine(intention, reality)

    first = engine.analyze(max_items=2)
    second = engine.analyze(max_items=2)

    assert first == second
    assert first["summary"]["unmapped"] == 4
    assert first["limit"] == {
        "max_items": 2,
        "total_items": 4,
        "returned_items": 2,
        "truncated": True,
    }
    assert [item["intent"]["id"] for item in first["items"]] == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]


def test_one_reality_candidate_cannot_be_proposed_for_multiple_intents():
    intention = _dag(
        [
            _node(
                "00000000-0000-0000-0000-000000000001",
                NodeType.COMPONENT,
                "Worker",
            ),
            _node(
                "00000000-0000-0000-0000-000000000002",
                NodeType.COMPONENT,
                "worker",
            ),
        ]
    )
    shared_reality_id = "00000000-0000-0000-0000-000000000101"
    reality = _dag([_node(shared_reality_id, NodeType.COMPONENT, "Worker")])

    report = ReconciliationEngine(intention, reality).analyze(max_items=10)

    intent_items = [
        item for item in report["items"] if item["subject_kind"] == "intent"
    ]
    assert [item["classification"] for item in intent_items] == [
        "ambiguous",
        "ambiguous",
    ]
    assert all(
        item["reality_candidates"][0]["id"] == shared_reality_id
        for item in intent_items
    )
    assert report["summary"]["candidate"] == 0
    assert report["summary"]["ambiguous"] == 2


def test_safe_diff_requests_review_and_never_infers_creation_or_deletion():
    intent_id = "00000000-0000-0000-0000-000000000001"
    reality_id = "00000000-0000-0000-0000-000000000101"
    intention = _dag([_node(intent_id, NodeType.COMPONENT, "Diffing Engine")])
    reality = _dag(
        [
            _node(reality_id, NodeType.COMPONENT, "DiffingEngine"),
            _node(
                "00000000-0000-0000-0000-000000000102",
                NodeType.MODULE,
                "Unrelated module",
            ),
        ]
    )

    diff = DiffingEngine(intention, reality).calculate_diff()

    assert list(diff["nodes"]) == [
        "Review mapping for Component 'Diffing Engine' [00000000]"
    ]
    task = next(iter(diff["nodes"].values()))
    assert task["category"] == "Reconciliation"
    assert task["action"] == "review_mapping"
    assert task["evidence"]["candidate_reality_ids"] == [reality_id]
    assert not any(
        name.startswith(("Create ", "Remove ", "Disconnect ")) for name in diff["nodes"]
    )
    assert diff["meta"]["reconciliation"]["unclassified_reality"] == 2


def test_safe_diff_caps_review_work_and_preserves_complete_counts():
    intention = _dag(
        [
            _node(
                f"00000000-0000-0000-0000-00000000000{index}",
                NodeType.COMPONENT,
                f"Missing {index}",
            )
            for index in range(1, 5)
        ]
    )

    diff = DiffingEngine(
        intention,
        _dag([]),
        policy=DiffPolicy.safe(max_tasks=2),
    ).calculate_diff()

    assert len(diff["nodes"]) == 2
    assert diff["meta"] == {
        "mode": "safe",
        "max_tasks": 2,
        "total_tasks": 4,
        "returned_tasks": 2,
        "truncated": True,
        "reconciliation": {
            "intention_nodes": 4,
            "reality_nodes": 0,
            "confirmed": 0,
            "candidate": 0,
            "ambiguous": 0,
            "unmapped": 4,
            "unclassified_reality": 0,
        },
    }


def test_safe_diff_prioritizes_actionable_candidates_before_unmapped_intent():
    intention = _dag(
        [
            _node(
                "00000000-0000-0000-0000-000000000001",
                NodeType.COMPONENT,
                "Unknown implementation",
            ),
            _node(
                "00000000-0000-0000-0000-000000000002",
                NodeType.COMPONENT,
                "Diffing Engine",
            ),
        ]
    )
    reality = _dag(
        [
            _node(
                "00000000-0000-0000-0000-000000000102",
                NodeType.COMPONENT,
                "DiffingEngine",
            )
        ]
    )

    diff = DiffingEngine(
        intention,
        reality,
        policy=DiffPolicy.safe(max_tasks=1),
    ).calculate_diff()

    task = next(iter(diff["nodes"].values()))
    assert task["action"] == "review_mapping"
    assert diff["meta"]["total_tasks"] == 2
    assert diff["meta"]["truncated"] is True


def test_safe_diff_does_not_treat_missing_observations_as_drift():
    node_id = "00000000-0000-0000-0000-000000000001"
    intention = _dag(
        [
            Node(
                id=node_id,
                type=NodeType.COMPONENT,
                name="Mapped",
                domain="verification",
                attributes={"runtime": "python"},
            )
        ]
    )
    reality = _dag([_node(node_id, NodeType.COMPONENT, "Mapped")])

    diff = DiffingEngine(intention, reality).calculate_diff()

    assert diff["nodes"] == {}
    assert diff["meta"]["reconciliation"]["confirmed"] == 1


def test_safe_diff_reports_observed_contradictions_for_confirmed_identity():
    node_id = "00000000-0000-0000-0000-000000000001"
    intention = _dag(
        [
            Node(
                id=node_id,
                type=NodeType.COMPONENT,
                name="Mapped",
                domain="verification",
                attributes={"runtime": "python"},
            )
        ]
    )
    reality = _dag(
        [
            Node(
                id=node_id,
                type=NodeType.COMPONENT,
                name="Mapped",
                domain="legacy",
                attributes={"runtime": "javascript"},
            )
        ]
    )

    diff = DiffingEngine(intention, reality).calculate_diff()

    task = next(iter(diff["nodes"].values()))
    assert task["action"] == "update_confirmed"
    assert (
        "Domain drift: intention 'verification', reality 'legacy'"
        in task["description"]
    )
    assert (
        "Attribute 'runtime' drift: intention 'python', reality 'javascript'"
        in task["description"]
    )


def test_legacy_structural_diff_requires_explicit_policy():
    intent = _dag(
        [
            _node(
                "00000000-0000-0000-0000-000000000001",
                NodeType.COMPONENT,
                "Missing",
            )
        ]
    )
    reality = _dag(
        [
            _node(
                "00000000-0000-0000-0000-000000000101",
                NodeType.COMPONENT,
                "Extraneous",
            )
        ]
    )

    diff = DiffingEngine(
        intent,
        reality,
        policy=DiffPolicy.legacy_structural(),
    ).calculate_diff()

    assert "Create Component 'Missing'" in diff["nodes"]
    assert "Remove Component 'Extraneous'" in diff["nodes"]
