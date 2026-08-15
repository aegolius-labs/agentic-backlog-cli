import json
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from aio_agentic_sdlc.dag_cli import cli
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Metadata, Node, NodeType
from aio_agentic_sdlc.drift_triage import (
    DriftTriageEngine,
    TriageDecisionSet,
    render_drift_triage,
)
from aio_agentic_sdlc.intent_ir import (
    AcceptanceCriterion,
    Approval,
    ApprovalState,
    IntentIR,
    IntentRevision,
    Provenance,
    ProvenanceType,
)


def _intent_ir(state: ApprovalState) -> IntentIR:
    if state == ApprovalState.APPROVED:
        approval = Approval(
            state=state,
            approved_by="Felix",
            approved_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
            rationale="Accepted for implementation.",
        )
    else:
        approval = Approval(state=state)
    return IntentIR(
        provenance=[
            Provenance(
                source_type=ProvenanceType.HUMAN_STATEMENT,
                reference="chat:triage",
                statement="Deliver the reviewed capability.",
            )
        ],
        confidence=0.9,
        acceptance_criteria=[
            AcceptanceCriterion(
                id="AC-1",
                statement="The capability is observable.",
                required_evidence=["test:capability"],
            )
        ],
        revision_history=[
            IntentRevision(
                revision=1,
                recorded_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
                actor="sdlc_intake",
                generator_version="aio-agentic-sdlc/test",
                summary="Initial test intent.",
            )
        ],
        responsible_agent="sdlc_implementer",
        generator_version="aio-agentic-sdlc/test",
        approval=approval,
    )


def _node(
    node_id: str,
    name: str,
    *,
    state: ApprovalState,
    node_type: NodeType = NodeType.COMPONENT,
) -> Node:
    return Node(
        id=node_id,
        type=node_type,
        name=name,
        intent=_intent_ir(state),
    )


def _dag(nodes, edges=None) -> DAGManager:
    return DAGManager(Metadata(name="Triage", version="1.0"), nodes, edges or [])


def _decision_set(
    engine: DriftTriageEngine, decisions: list[dict]
) -> TriageDecisionSet:
    return TriageDecisionSet.model_validate(
        {
            "schema_version": 1,
            "plan_digest": engine.source_identity()["plan_digest"],
            "decisions": decisions,
        }
    )


def _decision(subject_key: str, classification: str) -> dict:
    return {
        "subject_key": subject_key,
        "classification": classification,
        "rationale": "Reviewed the implementation and parser evidence.",
        "evidence": ["source:src/example.py", "test:test_example.py"],
        "decided_by": "sdlc_cartographer",
        "decided_at": "2026-08-15T12:00:00-04:00",
    }


@pytest.mark.parametrize(
    ("edges", "error"),
    [
        (
            [
                Edge(
                    source="00000000-0000-0000-0000-000000000001",
                    target="00000000-0000-0000-0000-000000000099",
                    type=EdgeType.CONTAINS,
                )
            ],
            "target node .* does not exist",
        ),
        (
            [
                Edge(
                    source="00000000-0000-0000-0000-000000000001",
                    target="00000000-0000-0000-0000-000000000002",
                    type=EdgeType.DEPENDS_ON,
                ),
                Edge(
                    source="00000000-0000-0000-0000-000000000002",
                    target="00000000-0000-0000-0000-000000000001",
                    type=EdgeType.DEPENDS_ON,
                ),
            ],
            "Cycle detected",
        ),
    ],
)
def test_triage_rejects_invalid_dag_structure(edges, error):
    nodes = [
        _node(
            "00000000-0000-0000-0000-000000000001",
            "First",
            state=ApprovalState.APPROVED,
        ),
        _node(
            "00000000-0000-0000-0000-000000000002",
            "Second",
            state=ApprovalState.APPROVED,
        ),
    ]

    with pytest.raises(ValueError, match=error):
        DriftTriageEngine(_dag(nodes, edges), _dag([]))


def test_triage_rejects_invalid_reality_dag_structure():
    invalid_reality = _dag(
        [],
        [
            Edge(
                source="00000000-0000-0000-0000-000000000090",
                target="00000000-0000-0000-0000-000000000091",
                type=EdgeType.CONTAINS,
            )
        ],
    )

    with pytest.raises(ValueError, match="source node .* does not exist"):
        DriftTriageEngine(_dag([]), invalid_reality)


def test_triage_withholds_unapproved_intent_from_implementation():
    intent_id = "00000000-0000-0000-0000-000000000001"
    engine = DriftTriageEngine(
        _dag(
            [
                _node(
                    intent_id, "Pending capability", state=ApprovalState.REVIEW_REQUIRED
                )
            ]
        ),
        _dag([]),
    )

    report = engine.analyze()

    assert report["summary"] == {
        "plan_tasks": 1,
        "missing_implementation": 0,
        "obsolete_or_unapproved_intent": 1,
        "framework_tooling_drift": 0,
        "identity_review_required": 0,
        "needs_classification": 0,
        "actionable_implementation": 0,
    }
    item = report["items"][0]
    assert item["subject"] == {
        "kind": "intent",
        "type": "component",
        "name": "Pending capability",
        "name_truncated": False,
    }
    assert item["classification"] == "obsolete_or_unapproved_intent"
    assert item["decision_source"] == "approval_gate"
    assert item["implementation_authorized"] is False
    assert item["evidence"]["approval_state"] == "review_required"

    decisions = _decision_set(
        engine,
        [_decision(f"intent:{intent_id}", "missing_implementation")],
    )
    with pytest.raises(ValueError, match="unknown or inapplicable"):
        engine.analyze(decisions=decisions)


def test_approved_unmapped_intent_requires_digest_bound_decision():
    intent_id = "00000000-0000-0000-0000-000000000002"
    engine = DriftTriageEngine(
        _dag([_node(intent_id, "Missing capability", state=ApprovalState.APPROVED)]),
        _dag([]),
    )

    pending = engine.analyze()
    assert pending["items"][0]["classification"] == "needs_classification"
    assert pending["items"][0]["implementation_authorized"] is False

    decisions = _decision_set(
        engine,
        [_decision(f"intent:{intent_id}", "missing_implementation")],
    )
    report = engine.analyze(decisions=decisions)

    assert report["summary"]["missing_implementation"] == 1
    assert report["summary"]["actionable_implementation"] == 1
    item = report["items"][0]
    assert item["classification"] == "missing_implementation"
    assert item["decision_source"] == "explicit"
    assert item["implementation_authorized"] is True
    assert item["evidence"]["acceptance_criteria"]["items"] == [
        {
            "id": "AC-1",
            "id_truncated": False,
            "statement": "The capability is observable.",
            "statement_truncated": False,
            "required_evidence": {
                "items": [{"value": "test:capability", "value_truncated": False}],
                "total_items": 1,
                "returned_items": 1,
                "truncated": False,
            },
        }
    ]


def test_triage_rejects_stale_duplicate_and_unused_decisions():
    intent_id = "00000000-0000-0000-0000-000000000003"
    engine = DriftTriageEngine(
        _dag([_node(intent_id, "Missing", state=ApprovalState.APPROVED)]),
        _dag([]),
    )
    decision = _decision(f"intent:{intent_id}", "missing_implementation")

    with pytest.raises(ValidationError, match="duplicate subject_key"):
        _decision_set(engine, [decision, decision])

    stale = _decision_set(engine, [decision]).model_copy(
        update={"plan_digest": "0" * 64}
    )
    with pytest.raises(ValueError, match="stale triage decisions"):
        engine.analyze(decisions=stale)

    unknown = _decision_set(
        engine,
        [
            _decision(
                "intent:00000000-0000-0000-0000-000000000099", "missing_implementation"
            )
        ],
    )
    with pytest.raises(ValueError, match="unknown or inapplicable"):
        engine.analyze(decisions=unknown)


def test_triage_routes_relationships_by_approval_and_observability():
    first_id = "00000000-0000-0000-0000-000000000011"
    second_id = "00000000-0000-0000-0000-000000000012"
    third_id = "00000000-0000-0000-0000-000000000013"
    intention = _dag(
        [
            _node(first_id, "Approved caller", state=ApprovalState.APPROVED),
            _node(second_id, "Approved target", state=ApprovalState.APPROVED),
            _node(third_id, "Pending target", state=ApprovalState.REVIEW_REQUIRED),
        ],
        [
            Edge(source=first_id, target=second_id, type=EdgeType.CALLS),
            Edge(source=first_id, target=third_id, type=EdgeType.CONTAINS),
        ],
    )
    reality = _dag(
        [
            Node(id=first_id, type=NodeType.COMPONENT, name="Approved caller"),
            Node(id=second_id, type=NodeType.COMPONENT, name="Approved target"),
            Node(id=third_id, type=NodeType.COMPONENT, name="Pending target"),
        ]
    )

    report = DriftTriageEngine(intention, reality).analyze()
    relationships = {
        item["subject"]["relation"]: item
        for item in report["items"]
        if item["subject"]["kind"] == "relationship"
    }

    assert relationships["calls"]["classification"] == "framework_tooling_drift"
    assert relationships["calls"]["decision_source"] == "observation_contract"
    assert (
        relationships["contains"]["classification"] == "obsolete_or_unapproved_intent"
    )
    assert relationships["contains"]["decision_source"] == "approval_gate"
    assert report["summary"]["actionable_implementation"] == 0


def test_triage_is_deterministic_bounded_and_human_readable():
    nodes = [
        _node(
            f"00000000-0000-0000-0000-00000000002{index}",
            f"Pending {index}",
            state=ApprovalState.REVIEW_REQUIRED,
        )
        for index in range(3)
    ]
    engine = DriftTriageEngine(_dag(nodes), _dag([]))

    first = engine.analyze(max_items=1)
    second = engine.analyze(max_items=1)

    assert first == second
    assert first["limit"] == {
        "max_items": 1,
        "total_items": 3,
        "returned_items": 1,
        "truncated": True,
    }
    brief = render_drift_triage(first)
    assert "1 of 3 triage items shown" in brief
    assert "Pending 0" in brief
    assert "Audit" in brief
    assert brief.index("Pending 0") < brief.index(
        "00000000-0000-0000-0000-000000000020"
    )


def test_triage_source_identity_is_canonical_across_order_and_guid_case():
    first_id = "abcdefab-cdef-abcd-efab-cdefabcdef01"
    second_id = "abcdefab-cdef-abcd-efab-cdefabcdef02"
    first_node = _node(first_id, "First", state=ApprovalState.APPROVED)
    second_node = _node(second_id, "Second", state=ApprovalState.APPROVED)
    first = _dag(
        [first_node, second_node],
        [Edge(source=first_id, target=second_id, type=EdgeType.CONTAINS)],
    )
    second = _dag(
        [
            second_node.model_copy(update={"id": second_id.upper()}),
            first_node.model_copy(update={"id": first_id.upper()}),
        ],
        [
            Edge(
                source=first_id.upper(),
                target=second_id.upper(),
                type=EdgeType.CONTAINS,
            )
        ],
    )

    first_source = DriftTriageEngine(first, _dag([])).source_identity()
    second_source = DriftTriageEngine(second, _dag([])).source_identity()

    assert first_source == second_source


def test_triage_bounds_nested_acceptance_evidence_and_reports_truncation():
    intent_id = "00000000-0000-0000-0000-000000000025"
    criteria = [
        AcceptanceCriterion(
            id=f"AC-{index}-" + ("i" * 600),
            statement="s" * 600,
            required_evidence=[f"evidence-{item}-" + ("e" * 600) for item in range(12)],
        )
        for index in range(12)
    ]
    intent = _intent_ir(ApprovalState.APPROVED).model_copy(
        update={"acceptance_criteria": criteria}
    )
    node = Node(
        id=intent_id,
        type=NodeType.COMPONENT,
        name="Bounded capability",
        intent=intent,
    )

    report = DriftTriageEngine(_dag([node]), _dag([])).analyze()

    bounded = report["items"][0]["evidence"]["acceptance_criteria"]
    assert bounded["total_items"] == 12
    assert bounded["returned_items"] == 10
    assert bounded["truncated"] is True
    first = bounded["items"][0]
    assert len(first["id"]) == 500
    assert first["id_truncated"] is True
    assert len(first["statement"]) == 500
    assert first["statement_truncated"] is True
    required = first["required_evidence"]
    assert required["total_items"] == 12
    assert required["returned_items"] == 10
    assert required["truncated"] is True
    assert len(required["items"][0]["value"]) == 500
    assert required["items"][0]["value_truncated"] is True


def test_cli_triage_writes_reproducible_report_without_mutating_dags(tmp_path):
    intent_id = "00000000-0000-0000-0000-000000000031"
    intention_path = tmp_path / "intention.yaml"
    reality_path = tmp_path / "reality.yaml"
    decisions_path = tmp_path / "decisions.json"
    report_path = tmp_path / "triage.json"
    intention = _dag(
        [_node(intent_id, "Missing capability", state=ApprovalState.APPROVED)]
    )
    reality = _dag([])
    intention.save(str(intention_path))
    reality.save(str(reality_path))
    engine = DriftTriageEngine(intention, reality)
    decisions_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "plan_digest": engine.source_identity()["plan_digest"],
                "decisions": [
                    _decision(f"intent:{intent_id}", "missing_implementation")
                ],
            }
        ),
        encoding="utf-8",
    )
    before_intention = intention_path.read_bytes()
    before_reality = reality_path.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "triage",
            "--intention",
            str(intention_path),
            "--reality",
            str(reality_path),
            "--decisions",
            str(decisions_path),
            "--format",
            "json",
            "--output",
            str(report_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (
        json.loads(report_path.read_text(encoding="utf-8"))["summary"][
            "actionable_implementation"
        ]
        == 1
    )
    assert intention_path.read_bytes() == before_intention
    assert reality_path.read_bytes() == before_reality

    before_decisions = decisions_path.read_bytes()
    rejected = CliRunner().invoke(
        cli,
        [
            "triage",
            "--intention",
            str(intention_path),
            "--reality",
            str(reality_path),
            "--decisions",
            str(decisions_path),
            "--output",
            str(decisions_path),
        ],
    )
    assert rejected.exit_code == 1
    assert "protected framework state" in rejected.output
    assert decisions_path.read_bytes() == before_decisions


@pytest.mark.parametrize("protected", ["intention", "reality"])
def test_cli_triage_refuses_protected_report_output(tmp_path, protected):
    intent_id = "00000000-0000-0000-0000-000000000041"
    intention_path = tmp_path / "intention.yaml"
    reality_path = tmp_path / "reality.yaml"
    _dag([_node(intent_id, "Pending", state=ApprovalState.REVIEW_REQUIRED)]).save(
        str(intention_path)
    )
    _dag([]).save(str(reality_path))
    output = intention_path if protected == "intention" else reality_path
    before_intention = intention_path.read_bytes()
    before_reality = reality_path.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "triage",
            "--intention",
            str(intention_path),
            "--reality",
            str(reality_path),
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert "protected framework state" in result.output
    assert intention_path.read_bytes() == before_intention
    assert reality_path.read_bytes() == before_reality
