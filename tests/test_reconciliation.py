import copy

import pytest

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Metadata, Node, NodeType
from aio_agentic_sdlc.diffing_engine import DiffingEngine, DiffPolicy
from aio_agentic_sdlc.reconciliation import ReconciliationEngine


def _dag(nodes, edges=None):
    return DAGManager(Metadata(name="Test", version="1.0"), nodes, edges or [])


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


def test_duplicate_intent_names_without_reality_do_not_invent_shared_candidates():
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

    report = ReconciliationEngine(intention, _dag([])).analyze(max_items=10)

    assert report["summary"]["unmapped"] == 2
    assert all(item["classification"] == "unmapped" for item in report["items"])
    assert all(item["reality_candidates"] == [] for item in report["items"])
    assert all(item["evidence"] == [] for item in report["items"])


def test_reconciliation_preserves_unicode_identity_and_rejects_empty_keys():
    japanese_intent_id = "00000000-0000-0000-0000-000000000001"
    punctuation_intent_id = "00000000-0000-0000-0000-000000000002"
    intention = _dag(
        [
            _node(japanese_intent_id, NodeType.COMPONENT, "東京"),
            _node(punctuation_intent_id, NodeType.COMPONENT, "---"),
        ]
    )
    reality = _dag(
        [
            _node(
                "00000000-0000-0000-0000-000000000101",
                NodeType.COMPONENT,
                "北京",
            ),
            _node(
                "00000000-0000-0000-0000-000000000102",
                NodeType.COMPONENT,
                "...",
            ),
        ]
    )

    report = ReconciliationEngine(intention, reality).analyze(max_items=10)

    by_intent = {
        item["intent"]["id"]: item
        for item in report["items"]
        if item["subject_kind"] == "intent"
    }
    assert by_intent[japanese_intent_id]["classification"] == "unmapped"
    assert by_intent[punctuation_intent_id]["classification"] == "unmapped"
    assert all(not item["reality_candidates"] for item in by_intent.values())
    assert report["summary"]["candidate"] == 0
    assert report["summary"]["ambiguous"] == 0


def test_reconciliation_bounds_nested_ambiguous_evidence_with_complete_totals():
    intent_id = "00000000-0000-0000-0000-000000000001"
    intention = _dag([_node(intent_id, NodeType.COMPONENT, "Worker")])
    reality = _dag(
        [
            _node(
                f"00000000-0000-0000-0000-{index:012d}",
                NodeType.COMPONENT,
                "Worker",
            )
            for index in range(100, 200)
        ]
    )

    report = ReconciliationEngine(intention, reality).analyze(
        max_items=1,
        max_candidates=3,
    )

    item = report["items"][0]
    assert item["classification"] == "ambiguous"
    assert len(item["reality_candidates"]) == 3
    assert item["candidate_limit"] == {
        "max_candidates": 3,
        "total_candidates": 100,
        "returned_candidates": 3,
        "truncated": True,
    }

    diff = DiffingEngine(
        intention,
        reality,
        policy=DiffPolicy.safe(max_tasks=1, max_candidates=2),
    ).calculate_diff()
    task = next(iter(diff["nodes"].values()))
    assert len(task["evidence"]["candidate_reality_ids"]) == 2
    assert task["evidence"]["candidate_limit"]["total_candidates"] == 100
    assert task["evidence"]["candidate_limit"]["truncated"] is True


def test_reconciliation_confirms_mixed_case_text_forms_of_the_same_guid():
    intent_id = "ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB"
    reality_id = intent_id.lower()
    intention = _dag([_node(intent_id, NodeType.COMPONENT, "Intent name")])
    reality = _dag([_node(reality_id, NodeType.COMPONENT, "Reality name")])

    report = ReconciliationEngine(intention, reality).analyze(max_items=10)

    assert report["summary"]["confirmed"] == 1
    assert report["summary"]["candidate"] == 0
    item = report["items"][0]
    assert item["classification"] == "confirmed"
    assert item["intent"]["id"] == intent_id
    assert item["reality_candidates"][0]["id"] == reality_id
    assert item["evidence"] == [
        {
            "kind": "canonical_guid",
            "value": reality_id,
            "intent_source_id": intent_id,
            "reality_source_id": reality_id,
        }
    ]


def test_reconciliation_rejects_duplicate_text_forms_of_one_canonical_guid():
    lower_id = "abcdefab-cdef-abcd-efab-cdefabcdefab"
    upper_id = lower_id.upper()
    intention = _dag(
        [
            _node(lower_id, NodeType.COMPONENT, "First"),
            _node(upper_id, NodeType.COMPONENT, "Duplicate"),
        ]
    )

    with pytest.raises(ValueError, match="duplicate canonical GUID"):
        ReconciliationEngine(intention, _dag([])).analyze(max_items=10)


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
        "Review mapping for Component 'Diffing Engine' "
        "[00000000-0000-0000-0000-000000000001]"
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
        "max_candidates": 20,
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


def test_safe_diff_task_keys_cannot_drop_intents_with_shared_id_prefixes():
    first_id = "12345678-0000-0000-0000-000000000001"
    second_id = "12345678-0000-0000-0000-000000000002"
    intention = _dag(
        [
            _node(first_id, NodeType.COMPONENT, "Same name"),
            _node(second_id, NodeType.COMPONENT, "Same name"),
        ]
    )

    diff = DiffingEngine(intention, _dag([])).calculate_diff()

    assert len(diff["nodes"]) == 2
    assert diff["meta"]["total_tasks"] == 2
    assert diff["meta"]["returned_tasks"] == len(diff["nodes"])
    assert diff["meta"]["truncated"] is False
    assert all(node_id in "\n".join(diff["nodes"]) for node_id in (first_id, second_id))


def test_safe_diff_canonicalizes_equivalent_mixed_case_edges():
    first_intent_id = "ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEF01"
    second_intent_id = "ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEF02"
    first_reality_id = first_intent_id.lower()
    second_reality_id = second_intent_id.lower()
    intention = _dag(
        [
            _node(first_intent_id, NodeType.COMPONENT, "First"),
            _node(second_intent_id, NodeType.COMPONENT, "Second"),
        ],
        [Edge(source=first_intent_id, target=second_intent_id, type=EdgeType.CALLS)],
    )
    reality = _dag(
        [
            _node(first_reality_id, NodeType.COMPONENT, "First observed"),
            _node(second_reality_id, NodeType.COMPONENT, "Second observed"),
        ],
        [Edge(source=first_reality_id, target=second_reality_id, type=EdgeType.CALLS)],
    )

    diff = DiffingEngine(intention, reality).calculate_diff()

    assert diff["nodes"] == {}
    assert diff["meta"]["reconciliation"]["confirmed"] == 2


def test_safe_diff_deduplicates_identical_logical_edges():
    first_id = "00000000-0000-0000-0000-000000000001"
    second_id = "00000000-0000-0000-0000-000000000002"
    nodes = [
        _node(first_id, NodeType.COMPONENT, "First"),
        _node(second_id, NodeType.COMPONENT, "Second"),
    ]
    duplicate_edge = Edge(source=first_id, target=second_id, type=EdgeType.CALLS)
    intention = _dag(nodes, [duplicate_edge, duplicate_edge.model_copy()])
    reality = _dag(nodes)

    diff = DiffingEngine(intention, reality).calculate_diff()

    assert len(diff["nodes"]) == 1
    assert diff["meta"]["total_tasks"] == 1
    assert diff["meta"]["returned_tasks"] == 1


def test_safe_diff_bounds_edges_in_canonical_order_not_input_order():
    node_ids = [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
    ]
    nodes = [
        _node(node_id, NodeType.COMPONENT, f"Node {index}")
        for index, node_id in enumerate(node_ids)
    ]
    first_edge = Edge(source=node_ids[0], target=node_ids[1], type=EdgeType.CALLS)
    second_edge = Edge(source=node_ids[0], target=node_ids[2], type=EdgeType.CALLS)
    reality = _dag(nodes)

    first = DiffingEngine(
        _dag(nodes, [first_edge, second_edge]),
        reality,
        policy=DiffPolicy.safe(max_tasks=1),
    ).calculate_diff()
    second = DiffingEngine(
        _dag(nodes, [second_edge, first_edge]),
        reality,
        policy=DiffPolicy.safe(max_tasks=1),
    ).calculate_diff()

    assert first == second
    assert first["meta"]["total_tasks"] == 2
    assert first["meta"]["truncated"] is True


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


def test_safe_diff_does_not_treat_unspecified_intent_domain_as_drift():
    node_id = "00000000-0000-0000-0000-000000000001"
    intention = _dag([_node(node_id, NodeType.COMPONENT, "Mapped")])
    reality = _dag(
        [
            Node(
                id=node_id,
                type=NodeType.COMPONENT,
                name="Mapped",
                domain="observed",
            )
        ]
    )

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
