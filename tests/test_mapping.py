import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Metadata, Node, NodeType
from aio_agentic_sdlc.intent_ir import IntentIR
from aio_agentic_sdlc.mapping import (
    MappingApproval,
    MappingEngine,
    MappingError,
    render_mapping_review,
)
from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator
from aio_agentic_sdlc.workspace import INTENTION_DAG_FILE, workspace_migration_lock

INTENT_ID = "6506870b-b262-4f54-b6e9-43de4a873a55"


def _intent_ir(statement: str = "Archive accepted PRDs without losing provenance."):
    return IntentIR.model_validate(
        {
            "schema_version": 1,
            "provenance": [
                {
                    "source_type": "human_statement",
                    "reference": "conversation:test",
                    "statement": statement,
                }
            ],
            "assumptions": ["Accepted PRDs have stable source paths."],
            "ambiguities": [
                {
                    "question": "Should rejected PRDs be retained?",
                    "status": "open",
                }
            ],
            "confidence": 0.8,
            "acceptance_criteria": [
                {
                    "id": "AC-1",
                    "statement": statement,
                    "required_evidence": ["test:archive_preserves_provenance"],
                }
            ],
            "revision_history": [
                {
                    "revision": 1,
                    "recorded_at": "2026-08-13T10:00:00-04:00",
                    "actor": "Felix",
                    "generator_version": "test/v1",
                    "summary": "Captured the intended archiving responsibility.",
                }
            ],
            "responsible_agent": "sdlc_cartographer",
            "generator_version": "test/v1",
            "approval": {"state": "review_required"},
        }
    )


def _project(
    tmp_path: Path,
    sources: dict[str, bytes | str],
    *,
    name="PRD Archiver",
    description=None,
    intent=None,
):
    for relative_path, content in sources.items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    intention = DAGManager(
        Metadata(name="Mapping Test", version="1.0"),
        [
            Node(
                id=INTENT_ID,
                type=NodeType.COMPONENT,
                name=name,
                description=description,
                intent=intent,
            )
        ],
        [],
    )
    intention_path = tmp_path / INTENTION_DAG_FILE
    intention_path.parent.mkdir(parents=True, exist_ok=True)
    intention.save(str(intention_path))
    return MappingEngine(tmp_path, intention_path), intention_path


def _approval():
    return MappingApproval(
        approved_by="Felix",
        approved_at=datetime(2026, 8, 7, 21, 30, tzinfo=timezone.utc),
        rationale="Reviewed the unique structural candidate and its exact source.",
    )


def test_mapping_review_binds_fresh_candidate_to_exact_source_without_mutation(
    tmp_path,
):
    source = b"class PRDArchiver:\n    pass\n"
    engine, intention_path = _project(
        tmp_path,
        {"src/archiver.py": source},
    )
    before_intention = intention_path.read_bytes()

    review = engine.review(INTENT_ID)

    assert review["schema_version"] == 3
    assert review["operation"] == "candidate_mapping"
    assert review["selection_mode"] == "automatic_name_match"
    assert review["classification"] == "candidate"
    assert review["intent"]["id"] == INTENT_ID
    assert len(review["candidates"]) == 1
    candidate = review["candidates"][0]
    assert candidate["reality"]["name"] == "PRDArchiver"
    assert candidate["source"] == {
        "path": "src/archiver.py",
        "symbol_kind": "class",
        "symbol_name": "PRDArchiver",
        "definition_line": 1,
        "marker_line": 1,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "raw_source_sha256": hashlib.sha256(source).hexdigest(),
        "annotation_neutral_source_sha256": hashlib.sha256(source).hexdigest(),
    }
    assert review["approval"] == {
        "required": True,
        "supported": True,
        "blockers": [],
    }
    assert len(review["evidence_digest"]) == 64
    assert (tmp_path / "src/archiver.py").read_bytes() == source
    assert intention_path.read_bytes() == before_intention
    assert not (tmp_path / "reality-dag.yaml").exists()
    assert not (tmp_path / "backlog.json").exists()


def test_mapping_review_is_a_human_decision_brief_not_an_id_table(tmp_path):
    source = (
        "class PRDArchiver(BaseArchiver):\n"
        '    """Archive accepted PRDs and preserve their source provenance."""\n\n'
        "    def archive(self, source_path: str) -> str:\n"
        '        """Return the archived path."""\n'
        "        return source_path\n\n"
        "    def _internal(self):\n"
        "        return None\n"
    )
    engine, _ = _project(
        tmp_path,
        {
            "src/archiver.py": source,
            "tests/test_archiver.py": (
                "from src.archiver import PRDArchiver\n\n"
                "def test_archive_preserves_provenance():\n"
                "    assert PRDArchiver().archive('accepted.md') == 'accepted.md'\n"
            ),
        },
        description="Archive accepted PRDs without losing provenance.",
        intent=_intent_ir(),
    )

    review = engine.review(INTENT_ID)
    brief = review["decision_brief"]

    assert brief["default_decision"] == "defer"
    assert brief["decision_scope"] == "source_identity_linkage"
    assert brief["intention"]["responsibility"] == (
        "Archive accepted PRDs without losing provenance."
    )
    assert brief["intention"]["acceptance_criteria"]["items"] == [
        {
            "id": "AC-1",
            "statement": "Archive accepted PRDs without losing provenance.",
            "required_evidence": ["test:archive_preserves_provenance"],
            "mapping_review_status": "not_verified",
        }
    ]
    implementation = brief["implementation"]
    assert implementation["location"] == "src/archiver.py:1"
    assert implementation["docstring"] == (
        "Archive accepted PRDs and preserve their source provenance."
    )
    assert implementation["bases"] == ["BaseArchiver"]
    assert [item["name"] for item in implementation["public_api"]["items"]] == [
        "archive"
    ]
    assert implementation["related_tests"]["items"][0]["test"] == (
        "test_archive_preserves_provenance"
    )
    assert brief["assessment"]["behaviorally_verified"] is False
    assert "human judgment" in brief["assessment"]["summary"].lower()

    rendered = render_mapping_review(review)
    assert "What is intended" in rendered
    assert "Archive accepted PRDs without losing provenance." in rendered
    assert "PRDArchiver" in rendered
    assert "archive(self, source_path: str)" in rendered
    assert "Related tests (references, not proof)" in rendered
    assert "Default: DEFER" in rendered
    assert rendered.index("Audit metadata") > rendered.index("Decision choices")
    decision_text = rendered.split("Audit metadata", maxsplit=1)[0]
    assert (
        re.search(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            decision_text,
        )
        is None
    )


def test_mapping_digest_binds_the_reviewed_intent_semantics(tmp_path):
    source = "class PRDArchiver:\n    pass\n"
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first, _ = _project(
        first_root,
        {"src/archiver.py": source},
        description="Archive accepted PRDs.",
        intent=_intent_ir("Archive accepted PRDs."),
    )
    second, _ = _project(
        second_root,
        {"src/archiver.py": source},
        description="Archive accepted PRDs and preserve provenance.",
        intent=_intent_ir("Archive accepted PRDs and preserve provenance."),
    )

    assert (
        first.review(INTENT_ID)["evidence_digest"]
        != second.review(INTENT_ID)["evidence_digest"]
    )


def test_mapping_review_bounds_related_test_evidence(tmp_path):
    tests = "from src.archiver import PRDArchiver\n\n" + "\n\n".join(
        f"def test_case_{index}():\n    assert PRDArchiver() is not None"
        for index in range(12)
    )
    engine, _ = _project(
        tmp_path,
        {
            "src/archiver.py": "class PRDArchiver:\n    pass\n",
            "tests/test_archiver.py": tests,
        },
        description="Archive accepted PRDs.",
        intent=_intent_ir("Archive accepted PRDs."),
    )

    related = engine.review(INTENT_ID)["decision_brief"]["implementation"][
        "related_tests"
    ]

    assert related["total"] == 12
    assert related["returned"] == 10
    assert related["truncated"] is True


def test_mapping_approval_atomically_marks_and_confirms_exact_python_symbol(tmp_path):
    source = b"class PRDArchiver:\n    pass\n"
    engine, intention_path = _project(
        tmp_path,
        {"src/archiver.py": source},
    )
    before_intention = intention_path.read_bytes()
    review = engine.review(INTENT_ID)
    candidate_id = review["candidates"][0]["reality"]["id"]

    result = engine.approve(
        INTENT_ID,
        candidate_id,
        review["evidence_digest"],
        _approval(),
    )

    mapped = (tmp_path / "src/archiver.py").read_text(encoding="utf-8")
    lines = mapped.splitlines()
    assert lines[1] == f"# aio-sdlc-node: {INTENT_ID}"
    assert lines[2:] == source.decode("utf-8").splitlines()
    audit = json.loads(lines[0].removeprefix("# aio-sdlc-mapping-approval: "))
    assert audit == result["receipt"]
    assert audit["schema_version"] == 1
    assert audit["intent_id"] == INTENT_ID
    assert audit["candidate_reality_id"] == candidate_id
    assert audit["approved_by"] == "Felix"
    assert audit["evidence_digest"] == review["evidence_digest"]
    assert audit["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert result["postcondition"]["classification"] == "confirmed"
    assert intention_path.read_bytes() == before_intention
    assert not (tmp_path / "reality-dag.yaml").exists()
    assert not (tmp_path / "backlog.json").exists()

    generated = RealityDAGGenerator(str(tmp_path), "Mapping Test").generate()
    assert INTENT_ID in generated.nodes
    assert generated.nodes[INTENT_ID].name == "PRDArchiver"


def test_mapping_approval_waits_for_workspace_migration_lock(tmp_path):
    engine, _ = _project(
        tmp_path,
        {"src/archiver.py": "class PRDArchiver:\n    pass\n"},
    )
    review = engine.review(INTENT_ID)
    started = threading.Event()
    finished = threading.Event()
    failures = []

    def approve_in_thread():
        started.set()
        try:
            engine.approve(
                INTENT_ID,
                review["candidates"][0]["reality"]["id"],
                review["evidence_digest"],
                _approval(),
            )
        except Exception as exc:  # noqa: BLE001 - captured for cross-thread assertion
            failures.append(exc)
        finally:
            finished.set()

    with workspace_migration_lock(tmp_path):
        worker = threading.Thread(target=approve_in_thread)
        worker.start()
        assert started.wait(timeout=1)
        assert not finished.wait(timeout=0.1)

    worker.join(timeout=3)
    assert not worker.is_alive()
    assert failures == []
    assert f"# aio-sdlc-node: {INTENT_ID}" in (tmp_path / "src/archiver.py").read_text(
        encoding="utf-8"
    )


def test_mapping_marker_precedes_decorators_and_preserves_crlf(tmp_path):
    source = b"@registered\r\nclass PRDArchiver:\r\n    pass\r\n"
    engine, _ = _project(tmp_path, {"src/archiver.py": source})
    review = engine.review(INTENT_ID)

    engine.approve(
        INTENT_ID,
        review["candidates"][0]["reality"]["id"],
        review["evidence_digest"],
        _approval(),
    )

    mapped = (tmp_path / "src/archiver.py").read_bytes()
    assert b"\r\n" in mapped
    assert b"\n" not in mapped.replace(b"\r\n", b"")
    assert mapped.endswith(source)
    assert mapped.index(b"# aio-sdlc-node") < mapped.index(b"@registered")


def test_mapping_approval_rejects_stale_evidence_without_rewriting_source(tmp_path):
    engine, _ = _project(
        tmp_path,
        {"src/archiver.py": "class PRDArchiver:\n    pass\n"},
    )
    review = engine.review(INTENT_ID)
    source_path = tmp_path / "src/archiver.py"
    source_path.write_text(
        "class PRDArchiver:\n    pass\n# concurrent edit\n",
        encoding="utf-8",
    )
    concurrent_bytes = source_path.read_bytes()

    with pytest.raises(MappingError, match="stale mapping evidence"):
        engine.approve(
            INTENT_ID,
            review["candidates"][0]["reality"]["id"],
            review["evidence_digest"],
            _approval(),
        )

    assert source_path.read_bytes() == concurrent_bytes


@pytest.mark.parametrize(
    ("intent_name", "sources", "classification"),
    [
        (
            "Worker",
            {
                "src/one.py": "class Worker:\n    pass\n",
                "src/two.py": "class Worker:\n    pass\n",
            },
            "ambiguous",
        ),
        ("Missing", {"src/one.py": "class Worker:\n    pass\n"}, "unmapped"),
    ],
)
def test_mapping_approval_rejects_non_candidates_without_mutation(
    tmp_path,
    intent_name,
    sources,
    classification,
):
    engine, _ = _project(tmp_path, sources, name=intent_name)
    before = {path: (tmp_path / path).read_bytes() for path in sources}
    review = engine.review(INTENT_ID)
    assert review["classification"] == classification
    assert review["approval"]["supported"] is False

    with pytest.raises(MappingError, match="unique candidate"):
        engine.approve(INTENT_ID, "0" * 36, "0" * 64, _approval())

    assert all(
        (tmp_path / path).read_bytes() == content for path, content in before.items()
    )


def test_mapping_approval_rejects_candidate_or_digest_mismatch(tmp_path):
    engine, _ = _project(
        tmp_path,
        {"src/archiver.py": "class PRDArchiver:\n    pass\n"},
    )
    review = engine.review(INTENT_ID)
    source_path = tmp_path / "src/archiver.py"
    before = source_path.read_bytes()

    with pytest.raises(MappingError, match="candidate Reality GUID"):
        engine.approve(INTENT_ID, "0" * 36, review["evidence_digest"], _approval())
    with pytest.raises(MappingError, match="stale mapping evidence"):
        engine.approve(
            INTENT_ID,
            review["candidates"][0]["reality"]["id"],
            "0" * 64,
            _approval(),
        )

    assert source_path.read_bytes() == before


def test_mapping_approval_rolls_back_original_bytes_when_verification_fails(
    tmp_path, monkeypatch
):
    source = b"class PRDArchiver:\n    pass\n"
    engine, _ = _project(tmp_path, {"src/archiver.py": source})
    review = engine.review(INTENT_ID)

    def fail_verification(*args, **kwargs):
        raise MappingError("injected post-write verification failure")

    monkeypatch.setattr(engine, "_verify_mapping", fail_verification)

    with pytest.raises(MappingError, match="verification failure"):
        engine.approve(
            INTENT_ID,
            review["candidates"][0]["reality"]["id"],
            review["evidence_digest"],
            _approval(),
        )

    assert (tmp_path / "src/archiver.py").read_bytes() == source


def test_mapping_review_rejects_source_symlink_that_escapes_project(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("class PRDArchiver:\n    pass\n", encoding="utf-8")
    source = tmp_path / "src" / "archiver.py"
    source.parent.mkdir(parents=True)
    try:
        os.symlink(outside, source)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    engine, _ = _project(tmp_path, {})

    with pytest.raises(MappingError, match="escapes project root"):
        engine.review(INTENT_ID)

    assert outside.read_text(encoding="utf-8") == "class PRDArchiver:\n    pass\n"


def test_mapping_approval_rejects_hidden_duplicate_canonical_marker(tmp_path):
    engine, _ = _project(
        tmp_path,
        {
            "src/archiver.py": "class PRDArchiver:\n    pass\n",
            "src/hidden.py": (
                f"def unrelated():\n    # aio-sdlc-node: {INTENT_ID}\n    pass\n"
            ),
        },
    )
    review = engine.review(INTENT_ID)
    source_path = tmp_path / "src/archiver.py"
    before = source_path.read_bytes()

    with pytest.raises(MappingError, match="already appears in source"):
        engine.approve(
            INTENT_ID,
            review["candidates"][0]["reality"]["id"],
            review["evidence_digest"],
            _approval(),
        )

    assert source_path.read_bytes() == before


def test_mapping_review_blocks_one_candidate_with_multiple_source_definitions(tmp_path):
    engine, _ = _project(
        tmp_path,
        {
            "src/archiver.py": (
                "class PRDArchiver:\n    pass\n\nclass PRDArchiver:\n    pass\n"
            )
        },
    )

    review = engine.review(INTENT_ID)

    assert review["classification"] == "candidate"
    assert review["candidates"][0]["source_location_count"] == 2
    assert review["approval"]["supported"] is False
    assert review["evidence_digest"] is None


def test_mapping_approval_requires_nonempty_audit_fields_and_timezone():
    with pytest.raises(ValueError, match="at least 1 character"):
        MappingApproval(
            approved_by="",
            approved_at=datetime(2026, 8, 7, 21, 30, tzinfo=timezone.utc),
            rationale="Reviewed evidence.",
        )
    with pytest.raises(ValueError, match="at least 1 character"):
        MappingApproval(
            approved_by="Felix",
            approved_at=datetime(2026, 8, 7, 21, 30, tzinfo=timezone.utc),
            rationale="",
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        MappingApproval(
            approved_by="Felix",
            approved_at=datetime(2026, 8, 7, 21, 30),
            rationale="Reviewed evidence.",
        )
