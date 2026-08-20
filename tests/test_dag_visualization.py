import json
from copy import deepcopy

import pytest

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Metadata, Node, NodeType
from aio_agentic_sdlc.dag_visualization import (
    DAGVisualizationEngine,
    render_dag_human,
    render_dag_mermaid,
)
from aio_agentic_sdlc.source_locations import SourceLocation
from aio_agentic_sdlc.workspace import INTENTION_DAG_FILE, REALITY_DAG_FILE


def _node(node_id: str, name: str) -> Node:
    return Node(id=node_id, type=NodeType.COMPONENT, name=name)


def _dag(nodes, edges=(), *, name="Test DAG") -> DAGManager:
    return DAGManager(Metadata(name=name, version="1.0"), list(nodes), list(edges))


def _engine(intention, reality, source_locations=None):
    return DAGVisualizationEngine(
        intention,
        reality,
        source_locations=source_locations,
    )


def test_reports_are_deterministic_across_input_order_guid_case_and_views():
    first = "aaaaaaaa-0000-0000-0000-000000000001"
    second = "BBBBBBBB-0000-0000-0000-000000000002"
    nodes = [_node(first, "First"), _node(second, "Second")]
    edges = [Edge(source=first, target=second, type=EdgeType.CALLS)]
    forward_engine = _engine(_dag(nodes, edges), _dag(nodes, edges))

    shuffled_nodes = [deepcopy(nodes[1]), deepcopy(nodes[0])]
    shuffled_nodes[0].id = second.lower()
    shuffled_nodes[1].id = first.upper()
    shuffled_edges = [
        Edge(source=first.upper(), target=second.lower(), type=EdgeType.CALLS)
    ]
    reverse_engine = _engine(
        _dag(shuffled_nodes, shuffled_edges),
        _dag(shuffled_nodes, shuffled_edges),
    )

    for view in ("intention", "reality", "comparison"):
        forward = forward_engine.build_report(view=view)
        reverse = reverse_engine.build_report(view=view)
        assert json.dumps(forward, sort_keys=True) == json.dumps(
            reverse, sort_keys=True
        )
        assert forward["view"] == view
    assert [
        item["canonical_id"]
        for item in forward_engine.build_report(view="intention")["records"]
    ] == [first, second.lower()]


def test_focus_uses_incoming_and_outgoing_edges_at_each_depth():
    ids = [f"00000000-0000-0000-0000-{number:012d}" for number in range(1, 5)]
    nodes = [_node(node_id, f"Node {index}") for index, node_id in enumerate(ids)]
    edges = [
        Edge(source=ids[0], target=ids[1], type=EdgeType.CALLS),
        Edge(source=ids[2], target=ids[1], type=EdgeType.READS),
        Edge(source=ids[2], target=ids[3], type=EdgeType.WRITES),
    ]
    engine = _engine(_dag(nodes, edges), _dag(nodes, edges))

    at_zero = engine.build_report(view="intention", focus_node_id=ids[1], depth=0)
    at_one = engine.build_report(view="intention", focus_node_id=ids[1], depth=1)
    at_two = engine.build_report(view="intention", focus_node_id=ids[1], depth=2)

    assert [record["canonical_id"] for record in at_zero["records"]] == [ids[1]]
    assert [record["canonical_id"] for record in at_one["records"]] == [
        ids[1],
        ids[0],
        ids[2],
    ]
    assert [record["canonical_id"] for record in at_two["records"]] == [
        ids[1],
        ids[0],
        ids[2],
        ids[3],
    ]
    with pytest.raises(ValueError, match="Unknown focus node"):
        engine.build_report(
            view="intention",
            focus_node_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )


def test_comparison_has_all_classifications_relations_and_exact_source_evidence():
    ids = [f"00000000-0000-0000-0000-{number:012d}" for number in range(1, 5)]
    intention = _dag(
        [
            _node(ids[0], "Confirmed"),
            _node(ids[1], "Candidate"),
            _node(ids[2], "Ambiguous"),
            _node(ids[3], "Missing"),
        ],
        [Edge(source=ids[0], target=ids[1], type=EdgeType.CALLS)],
    )
    candidate_id = "00000000-0000-0000-0000-000000000012"
    reality = _dag(
        [
            _node(ids[0], "Confirmed"),
            _node(candidate_id, "Candidate"),
            _node("00000000-0000-0000-0000-000000000013", "Ambiguous"),
            _node("00000000-0000-0000-0000-000000000014", "Ambiguous"),
        ],
        [Edge(source=ids[0], target=candidate_id, type=EdgeType.CALLS)],
    )
    location = SourceLocation(
        path="src/candidate.py",
        symbol_kind="class",
        symbol_name="Candidate",
        definition_line=10,
        marker_line=9,
        source_sha256="a" * 64,
    )

    report = _engine(
        intention,
        reality,
        {candidate_id: [location]},
    ).build_report()

    classifications = {
        record["classification"]
        for record in report["records"]
        if record["subject_kind"] == "intent"
    }
    assert classifications == {"confirmed", "candidate", "ambiguous", "unmapped"}
    assert report["summary"]["classifications"] == {
        "confirmed": 1,
        "candidate": 1,
        "ambiguous": 1,
        "unmapped": 1,
    }
    assert report["intended_relationships"][0]["target_id"] == ids[1]
    assert report["observed_relationships"][0]["target_id"] == candidate_id
    candidate = next(
        record
        for record in report["records"]
        if record["classification"] == "candidate"
    )
    assert candidate["reality_candidates"][0]["source_evidence"]["locations"] == [
        location.as_dict()
    ]
    assert candidate["evidence_state"]["behavioral_verification"] == "unavailable"


def test_all_collections_are_bounded_while_totals_remain_complete():
    intent_id = "00000000-0000-0000-0000-000000000001"
    reality_ids = [f"00000000-0000-0000-0000-{number:012d}" for number in range(10, 14)]
    intention = _dag([_node(intent_id, "Duplicate")])
    reality_nodes = [_node(node_id, "Duplicate") for node_id in reality_ids]
    reality_edges = [
        Edge(
            source=reality_ids[index],
            target=reality_ids[index + 1],
            type=EdgeType.READS,
        )
        for index in range(3)
    ]
    locations = {
        node_id: [
            SourceLocation(
                path=f"src/{index}.py",
                symbol_kind="class",
                symbol_name="Duplicate",
                definition_line=index + 1,
                marker_line=index + 1,
                source_sha256=str(index) * 64,
            )
            for index in range(3)
        ]
        for node_id in reality_ids
    }

    report = _engine(
        intention,
        _dag(reality_nodes, reality_edges),
        locations,
    ).build_report(max_items=1, max_edges=1, max_candidates=1)

    assert report["limits"]["records"] == {
        "max_items": 1,
        "total_items": 5,
        "returned_items": 1,
        "truncated": True,
    }
    assert report["limits"]["observed_relationships"] == {
        "max_edges": 1,
        "total_edges": 3,
        "returned_edges": 1,
        "truncated": True,
    }
    record = report["records"][0]
    assert record["candidate_limit"]["total_candidates"] == 4
    assert len(record["reality_candidates"]) == 1
    source_limit = record["reality_candidates"][0]["source_evidence"]["limit"]
    assert source_limit["total_items"] == 3
    assert source_limit["returned_items"] == 1
    assert source_limit["truncated"] is True


def test_mermaid_uses_synthetic_ids_and_escapes_bounded_malicious_labels():
    node_id = "00000000-0000-0000-0000-000000000001"
    malicious = (
        'bad"]\nclick n0 "javascript:alert(1)"\n%%{init: {}}%%<script>' + "x" * 300
    )
    report = _engine(_dag([_node(node_id, malicious)]), _dag([])).build_report(
        view="intention"
    )

    rendered = render_dag_mermaid(report)

    assert 'n0000["' in rendered
    assert node_id not in rendered
    assert "<script>" not in rendered
    assert "%%{" not in rendered
    assert "\nclick " not in rendered
    assert "&lt;script&gt;" in rendered
    assert len(rendered) < 500
    assert "DAG visualization" in render_dag_human(report)


def test_invalid_dags_arguments_and_read_only_postcondition(tmp_path):
    node_id = "00000000-0000-0000-0000-000000000001"
    missing_id = "00000000-0000-0000-0000-000000000002"
    invalid = _dag(
        [_node(node_id, "Only")],
        [Edge(source=node_id, target=missing_id, type=EdgeType.CALLS)],
    )
    with pytest.raises(ValueError, match="does not exist"):
        _engine(invalid, _dag([]))

    intention_path = tmp_path / "intention.yaml"
    reality_path = tmp_path / "reality.yaml"
    _dag([_node(node_id, "Only")]).save(str(intention_path))
    _dag([]).save(str(reality_path))
    before = (intention_path.read_bytes(), reality_path.read_bytes())
    engine = _engine(
        DAGManager.load(str(intention_path)),
        DAGManager.load(str(reality_path)),
    )
    engine.build_report(view="comparison")
    assert (intention_path.read_bytes(), reality_path.read_bytes()) == before

    with pytest.raises(ValueError, match="Unsupported view"):
        engine.build_report(view="raw")
    with pytest.raises(ValueError, match="depth must be at least 0"):
        engine.build_report(depth=-1)
    with pytest.raises(ValueError, match="max_edges must be at least 1"):
        engine.build_report(max_edges=0)


def test_project_source_discovery_requires_an_exact_fresh_reality_match(
    tmp_path, monkeypatch
):
    node_id = "00000000-0000-0000-0000-000000000001"
    metadata = Metadata(name="Fresh", version="1.0")
    canonical = _dag([_node(node_id, "Fresh")], name="Fresh")
    intention_path = tmp_path / INTENTION_DAG_FILE
    reality_path = tmp_path / REALITY_DAG_FILE
    intention_path.parent.mkdir(parents=True)
    canonical.save(str(intention_path))
    canonical.save(str(reality_path))
    location = SourceLocation(
        path="src/fresh.py",
        symbol_kind="class",
        symbol_name="Fresh",
        definition_line=2,
        marker_line=1,
        source_sha256="f" * 64,
    )

    class MatchingGenerator:
        def __init__(self, root_dir, system_name):
            self.source_locations = {node_id: [location]}

        def generate(self):
            return DAGManager(metadata, [_node(node_id, "Fresh")], [])

    monkeypatch.setattr(
        "aio_agentic_sdlc.dag_visualization.RealityDAGGenerator",
        MatchingGenerator,
    )
    matching = DAGVisualizationEngine.from_project(tmp_path).build_report(
        view="reality"
    )

    assert matching["source_discovery"]["state"] == "available"
    assert matching["records"][0]["source_evidence"]["locations"] == [
        location.as_dict()
    ]

    class StaleGenerator(MatchingGenerator):
        def generate(self):
            return DAGManager(metadata, [], [])

    monkeypatch.setattr(
        "aio_agentic_sdlc.dag_visualization.RealityDAGGenerator",
        StaleGenerator,
    )
    stale = DAGVisualizationEngine.from_project(tmp_path).build_report(view="reality")

    assert stale["source_discovery"]["state"] == "unavailable"
    assert stale["records"][0]["source_evidence"]["state"] == "unavailable"
    assert stale["records"][0]["source_evidence"]["locations"] == []


def test_human_renderer_puts_names_and_sources_before_final_audit_ids():
    service_id = "00000000-0000-0000-0000-000000000001"
    worker_id = "00000000-0000-0000-0000-000000000002"
    edge = Edge(source=service_id, target=worker_id, type=EdgeType.CALLS)
    location = SourceLocation(
        path="src/service.py",
        symbol_kind="class",
        symbol_name="Service",
        definition_line=10,
        marker_line=9,
        source_sha256="a" * 64,
    )
    report = _engine(
        _dag([_node(service_id, "Service"), _node(worker_id, "Worker")], [edge]),
        _dag([_node(service_id, "Service"), _node(worker_id, "Worker")], [edge]),
        {service_id: [location]},
    ).build_report()

    rendered = render_dag_human(report)
    evidence, audit = rendered.split("\nAudit IDs\n", maxsplit=1)

    assert "Intent: Service [component] — confirmed" in evidence
    assert (
        "Reality: Service [component] — confirmed — source src/service.py:10"
        in evidence
    )
    assert "Intended: Service --calls--> Worker" in evidence
    assert "Observed: Service --calls--> Worker" in evidence
    assert service_id not in evidence
    assert worker_id not in evidence
    assert service_id in audit
    assert worker_id in audit


def test_reality_only_focus_seeds_all_contested_intention_candidates_at_depth_zero():
    intent_ids = [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    focus_id = "00000000-0000-0000-0000-000000000010"
    report = _engine(
        _dag([_node(intent_id, "Shared") for intent_id in intent_ids]),
        _dag([_node(focus_id, "Shared")]),
    ).build_report(
        view="comparison",
        focus_node_id=focus_id,
        depth=0,
    )

    intent_records = [
        record for record in report["records"] if record["subject_kind"] == "intent"
    ]
    assert [record["canonical_id"] for record in intent_records] == intent_ids
    assert {record["classification"] for record in intent_records} == {"ambiguous"}
    assert all(
        [candidate["id"] for candidate in record["reality_candidates"]] == [focus_id]
        for record in intent_records
    )


def test_visualization_canonicalizes_mixed_case_edge_endpoints_before_validation():
    source_id = "aaaaaaaa-0000-0000-0000-000000000001"
    target_id = "bbbbbbbb-0000-0000-0000-000000000002"
    manager = _dag(
        [_node(source_id, "Source"), _node(target_id, "Target")],
        [
            Edge(
                source=source_id.upper(),
                target=target_id.upper(),
                type=EdgeType.CALLS,
            )
        ],
    )

    report = _engine(manager, _dag([])).build_report(view="intention")

    assert report["intended_relationships"] == [
        {"source_id": source_id, "target_id": target_id, "type": "calls"}
    ]


def test_source_location_strings_are_bounded_with_field_truncation_metadata():
    node_id = "00000000-0000-0000-0000-000000000001"
    locations = [
        SourceLocation(
            path="p" * 400,
            symbol_kind="k" * 400,
            symbol_name="n" * 400,
            definition_line=1,
            marker_line=1,
            source_sha256="s" * 400,
        ),
        SourceLocation(
            path="second.py",
            symbol_kind="class",
            symbol_name="Second",
            definition_line=2,
            marker_line=2,
            source_sha256="a" * 64,
        ),
    ]
    report = _engine(
        _dag([]),
        _dag([_node(node_id, "Reality")]),
        {node_id: locations},
    ).build_report(view="reality", max_candidates=1)

    evidence = report["records"][0]["source_evidence"]
    bounded = evidence["locations"][0]
    assert all(
        len(bounded[field]) <= 200
        for field in ("path", "symbol_kind", "symbol_name", "source_sha256")
    )
    assert evidence["location_truncation"] == [
        {
            "path": True,
            "symbol_kind": True,
            "symbol_name": True,
            "source_sha256": True,
        }
    ]
    assert evidence["limit"]["total_items"] == 2
    assert evidence["limit"]["returned_items"] == 1
    assert evidence["limit"]["truncated"] is True
