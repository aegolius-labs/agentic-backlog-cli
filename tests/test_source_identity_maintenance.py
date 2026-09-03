import hashlib
import json
import os
import shutil
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import pytest
from click.testing import CliRunner

from aio_agentic_sdlc import mapping as mapping_module
from aio_agentic_sdlc import mcp_server as mcp_server_module
from aio_agentic_sdlc.dag_cli import cli
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Metadata, Node, NodeType
from aio_agentic_sdlc.dag_store import mutate_dag_file
from aio_agentic_sdlc.mapping import (
    MappingApproval,
    MappingEngine,
    MappingError,
    render_mapping_review,
    render_receipt_refresh_review,
)
from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator
from aio_agentic_sdlc.workspace import INTENTION_DAG_FILE

INTENT_ID = "15019926-c6be-5c98-b558-954c7657e5c6"
ORIGINAL_REALITY_ID = "12345678-1234-5678-9234-567812345678"


def _approval(rationale: str = "Reviewed exact source identity evidence."):
    return MappingApproval(
        approved_by="Felix",
        approved_at=datetime(2026, 8, 21, 21, 30, tzinfo=timezone.utc),
        rationale=rationale,
    )


def _project(
    tmp_path: Path,
    source: bytes,
    *,
    intent_name: str = "MCP SDK v2 Integration",
    node_type: NodeType = NodeType.COMPONENT,
    description: str = "Maintain the reviewed source identity boundary.",
):
    source_path = tmp_path / "src" / "runtime.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source)
    intention_path = tmp_path / INTENTION_DAG_FILE
    intention_path.parent.mkdir(parents=True)
    DAGManager(
        Metadata(name="Source identity maintenance", version="1.0"),
        [
            Node(
                id=INTENT_ID,
                type=node_type,
                name=intent_name,
                description=description,
            )
        ],
        [],
    ).save(str(intention_path))
    return MappingEngine(tmp_path, intention_path), source_path, intention_path


def _reality_id(tmp_path: Path, symbol_name: str) -> str:
    generator = RealityDAGGenerator(str(tmp_path), "Source identity maintenance")
    reality = generator.generate()
    return next(node.id for node in reality.nodes.values() if node.name == symbol_name)


def _schema_one_receipt(neutral_source: bytes, **overrides):
    receipt = {
        "schema_version": 1,
        "intent_id": INTENT_ID,
        "candidate_reality_id": ORIGINAL_REALITY_ID,
        "source_path": "src/runtime.py",
        "symbol_kind": "class",
        "symbol_name": "RuntimeBoundary",
        "source_sha256": hashlib.sha256(neutral_source).hexdigest(),
        "evidence_digest": "a" * 64,
        "approved_by": "Felix",
        "approved_at": "2026-08-13T19:29:14-04:00",
        "rationale": "Approved the original exact identity.",
    }
    receipt.update(overrides)
    return receipt


def _confirmed_source(*, receipt=None, newline="\n") -> tuple[bytes, bytes]:
    neutral = f"class RuntimeBoundary:{newline}    pass{newline}".encode()
    receipt = receipt or _schema_one_receipt(neutral)
    receipt_json = json.dumps(
        receipt,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    annotated = (
        f"# aio-sdlc-mapping-approval: {receipt_json}{newline}"
        f"# aio-sdlc-node: {INTENT_ID}{newline}"
    ).encode() + neutral
    return neutral, annotated


def test_explicit_observed_guid_review_binds_differently_named_symbol(tmp_path):
    source = b"class RuntimeBoundary:\n    pass\n"
    engine, source_path, intention_path = _project(tmp_path, source)
    observed_id = _reality_id(tmp_path, "RuntimeBoundary")
    before = (source_path.read_bytes(), intention_path.read_bytes())

    first = engine.review(INTENT_ID, candidate_reality_id=observed_id)
    second = engine.review(INTENT_ID, candidate_reality_id=observed_id)

    assert first == second
    assert first["schema_version"] == 3
    assert first["operation"] == "candidate_mapping"
    assert first["selection_mode"] == "explicit_observed_guid"
    assert first["approval"] == {
        "required": True,
        "supported": True,
        "blockers": [],
    }
    assert first["candidates"][0]["reality"]["id"] == observed_id
    assert first["candidates"][0]["source"]["symbol_name"] == "RuntimeBoundary"
    assert len(first["evidence_digest"]) == 64
    assert (source_path.read_bytes(), intention_path.read_bytes()) == before


def test_mapping_review_bounds_hostile_single_field_in_json_human_cli_and_mcp(
    tmp_path,
):
    private_tail = "-PRIVATE-END"
    hostile = "PRIVATE-START-" + ("x" * 200_000) + private_tail
    engine, _, _ = _project(
        tmp_path,
        b"class RuntimeBoundary:\n    pass\n",
        description=hostile,
    )
    observed_id = _reality_id(tmp_path, "RuntimeBoundary")

    report = engine.review(INTENT_ID, candidate_reality_id=observed_id)
    json_text = json.dumps(report)
    human_text = render_mapping_review(report)
    cli_result = CliRunner().invoke(
        cli,
        [
            "mapping",
            "review",
            "--project-path",
            str(tmp_path),
            "--intent-id",
            INTENT_ID,
            "--candidate-reality-id",
            observed_id,
        ],
    )
    mcp_text = mcp_server_module.review_mapping(
        intent_id=INTENT_ID,
        candidate_reality_id=observed_id,
        project_path=str(tmp_path),
    )

    bounds = report["decision_brief"]["intention"]["_display_bounds"]
    assert bounds["responsibility"] == {
        "truncated": True,
        "original_chars": len(hostile),
        "returned_chars": len(report["decision_brief"]["intention"]["responsibility"]),
        "limit_chars": report["display_limits"]["max_string_chars"],
    }
    assert cli_result.exit_code == 0
    for output in (json_text, human_text, cli_result.output, mcp_text):
        assert len(output.encode("utf-8")) < 64 * 1024
        assert private_tail not in output


def test_explicit_observed_guid_approval_replays_selection_and_marks_exact_symbol(
    tmp_path,
):
    source = b"class RuntimeBoundary:\n    pass\n"
    engine, source_path, _ = _project(tmp_path, source)
    observed_id = _reality_id(tmp_path, "RuntimeBoundary")
    review = engine.review(INTENT_ID, candidate_reality_id=observed_id)

    result = engine.approve(
        INTENT_ID,
        observed_id,
        review["evidence_digest"],
        _approval(),
        selection_mode="explicit_observed_guid",
    )

    content = source_path.read_text(encoding="utf-8")
    assert result["postcondition"]["classification"] == "confirmed"
    assert content.count(f"# aio-sdlc-node: {INTENT_ID}") == 1
    assert content.count("# aio-sdlc-mapping-approval:") == 1


def test_confirmed_receipt_review_is_deterministic_and_read_only(tmp_path):
    neutral, annotated = _confirmed_source()
    engine, source_path, intention_path = _project(tmp_path, annotated)
    before = (source_path.read_bytes(), intention_path.read_bytes())

    first = engine.review_receipt_refresh(INTENT_ID)
    second = engine.review_receipt_refresh(INTENT_ID)

    assert first == second
    assert first["schema_version"] == 3
    assert first["operation"] == "receipt_refresh"
    assert first["selection_mode"] == "confirmed_marker"
    assert first["classification"] == "confirmed"
    assert (
        first["source"]["annotation_neutral_sha256"]
        == hashlib.sha256(neutral).hexdigest()
    )
    assert first["prior_receipt"]["data"]["schema_version"] == 1
    assert len(first["prior_receipt"]["sha256"]) == 64
    assert len(first["evidence_digest"]) == 64
    assert (source_path.read_bytes(), intention_path.read_bytes()) == before

    rendered = render_receipt_refresh_review(first)
    assert "What is preserved" in rendered
    assert "What this does not establish" in rendered
    assert "Default: DEFER" in rendered
    assert rendered.index("Audit metadata") < rendered.index(INTENT_ID)


def test_receipt_refresh_preserves_marker_and_replaces_only_receipt(tmp_path):
    neutral, annotated = _confirmed_source(newline="\r\n")
    engine, source_path, _ = _project(tmp_path, annotated)
    source_path.write_bytes(source_path.read_bytes() + b"# unrelated change\r\n")
    reviewed_bytes = source_path.read_bytes()
    marker_line = next(
        line
        for line in reviewed_bytes.splitlines(keepends=True)
        if b"aio-sdlc-node:" in line
    )
    review = engine.review_receipt_refresh(INTENT_ID)

    result = engine.refresh_receipt(
        INTENT_ID,
        review["evidence_digest"],
        _approval("Approved fresh whole-file receipt evidence."),
    )

    refreshed = source_path.read_bytes()
    assert result["receipt"]["schema_version"] == 2
    assert result["postcondition"]["classification"] == "confirmed"
    assert refreshed.count(marker_line) == 1
    assert refreshed.count(b"aio-sdlc-mapping-approval:") == 1
    assert b"# unrelated change\r\n" in refreshed
    assert b"\r\n" in refreshed
    expected_source_sha256 = hashlib.sha256(
        neutral + b"# unrelated change\r\n"
    ).hexdigest()
    assert expected_source_sha256 == result["receipt"]["source_sha256"]


def test_candidate_and_receipt_refresh_preserve_read_only_crlf_source(tmp_path):
    original = b"class RuntimeBoundary:\r\n    pass\r\n"
    engine, source_path, _ = _project(tmp_path, original)
    observed_id = _reality_id(tmp_path, "RuntimeBoundary")
    os.chmod(source_path, stat.S_IREAD)
    read_only_mode = stat.S_IMODE(os.stat(source_path).st_mode)
    try:
        candidate_review = engine.review(
            INTENT_ID,
            candidate_reality_id=observed_id,
        )
        candidate = engine.approve(
            INTENT_ID,
            observed_id,
            candidate_review["evidence_digest"],
            _approval(),
            selection_mode="explicit_observed_guid",
        )
        assert candidate["postcondition"]["classification"] == "confirmed"
        assert stat.S_IMODE(os.stat(source_path).st_mode) == read_only_mode

        refresh_review = engine.review_receipt_refresh(INTENT_ID)
        refreshed = engine.refresh_receipt(
            INTENT_ID,
            refresh_review["evidence_digest"],
            _approval("Approved current read-only CRLF receipt evidence."),
        )
        content = source_path.read_bytes()
        assert refreshed["postcondition"]["classification"] == "confirmed"
        assert stat.S_IMODE(os.stat(source_path).st_mode) == read_only_mode
        assert b"\r\n" in content
        assert b"\n" not in content.replace(b"\r\n", b"")
    finally:
        os.chmod(source_path, stat.S_IWRITE)


def test_repeated_receipt_refresh_preserves_one_flat_identity_approval(tmp_path):
    _, annotated = _confirmed_source()
    original_receipt = _schema_one_receipt(b"class RuntimeBoundary:\n    pass\n")
    engine, source_path, _ = _project(tmp_path, annotated)

    first_review = engine.review_receipt_refresh(INTENT_ID)
    first = engine.refresh_receipt(
        INTENT_ID,
        first_review["evidence_digest"],
        _approval("First maintenance approval."),
    )
    second_review = engine.review_receipt_refresh(INTENT_ID)
    second = engine.refresh_receipt(
        INTENT_ID,
        second_review["evidence_digest"],
        _approval("Second maintenance approval."),
    )

    assert first["receipt"]["identity_approval"] == original_receipt
    assert second["receipt"]["identity_approval"] == original_receipt
    assert "identity_approval" not in second["receipt"]["identity_approval"]
    assert (
        second["receipt"]["maintenance_approval"]["supersedes_receipt_sha256"]
        == second_review["prior_receipt"]["sha256"]
    )
    assert source_path.read_bytes().count(b"aio-sdlc-mapping-approval:") == 1


def test_receipt_refresh_rejects_stale_digest_without_mutation(tmp_path):
    _, annotated = _confirmed_source()
    engine, source_path, _ = _project(tmp_path, annotated)
    review = engine.review_receipt_refresh(INTENT_ID)
    source_path.write_bytes(source_path.read_bytes() + b"# changed after review\n")
    before = source_path.read_bytes()

    with pytest.raises(MappingError, match="stale receipt evidence digest"):
        engine.refresh_receipt(INTENT_ID, review["evidence_digest"], _approval())

    assert source_path.read_bytes() == before


@pytest.mark.parametrize(
    "receipt_mutation",
    [
        lambda receipt: {**receipt, "unknown": "field"},
        lambda receipt: {**receipt, "intent_id": ORIGINAL_REALITY_ID},
        lambda receipt: {**receipt, "symbol_name": "DifferentBoundary"},
        lambda receipt: {**receipt, "approved_at": "2026-08-21T12:00:00"},
    ],
)
def test_receipt_review_rejects_unknown_or_mismatched_receipt_shape(
    tmp_path, receipt_mutation
):
    neutral = b"class RuntimeBoundary:\n    pass\n"
    receipt = receipt_mutation(_schema_one_receipt(neutral))
    _, annotated = _confirmed_source(receipt=receipt)
    engine, source_path, _ = _project(tmp_path, annotated)
    before = source_path.read_bytes()

    with pytest.raises(MappingError):
        engine.review_receipt_refresh(INTENT_ID)

    assert source_path.read_bytes() == before


def test_receipt_review_rejects_duplicate_json_keys_and_duplicate_receipts(tmp_path):
    neutral, annotated = _confirmed_source()
    duplicate_key = annotated.replace(
        b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1
    )
    engine, source_path, _ = _project(tmp_path, duplicate_key)
    with pytest.raises(MappingError, match="duplicate"):
        engine.review_receipt_refresh(INTENT_ID)


def test_receipt_review_ignores_non_comment_prefix_literal_but_rejects_malformed_comment(
    tmp_path,
):
    _, annotated = _confirmed_source()
    literal = b'UNRELATED = "aio-sdlc-mapping-approval: not a receipt"\n'
    engine, source_path, _ = _project(tmp_path, annotated + literal)

    report = engine.review_receipt_refresh(INTENT_ID)
    assert report["operation"] == "receipt_refresh"

    triple_literal = (
        annotated
        + b'TEXT = """\n# aio-sdlc-mapping-approval: also not a receipt\n"""\n'
    )
    source_path.write_bytes(triple_literal)
    report = engine.review_receipt_refresh(INTENT_ID)
    assert report["operation"] == "receipt_refresh"

    malformed = annotated.replace(
        annotated.splitlines(keepends=True)[0],
        b"# aio-sdlc-mapping-approval: not-json\n",
        1,
    )
    source_path.write_bytes(malformed)
    with pytest.raises(MappingError, match="malformed"):
        engine.review_receipt_refresh(INTENT_ID)

    duplicate_receipt = annotated.splitlines(keepends=True)[0] + annotated
    source_path.write_bytes(duplicate_receipt)
    with pytest.raises(MappingError, match="duplicate"):
        engine.review_receipt_refresh(INTENT_ID)


def test_receipt_review_rejects_oversized_receipt_without_mutation(tmp_path):
    neutral = b"class RuntimeBoundary:\n    pass\n"
    receipt = _schema_one_receipt(neutral, rationale="x" * (17 * 1024))
    _, annotated = _confirmed_source(receipt=receipt)
    engine, source_path, _ = _project(tmp_path, annotated)
    before = source_path.read_bytes()

    with pytest.raises(MappingError, match="size limit"):
        engine.review_receipt_refresh(INTENT_ID)

    assert source_path.read_bytes() == before


def test_receipt_review_rejects_lone_surrogate_as_bounded_mapping_error(tmp_path):
    neutral = b"class RuntimeBoundary:\n    pass\n"
    receipt_json = json.dumps(
        _schema_one_receipt(neutral, rationale="\ud800"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    annotated = (
        b"# aio-sdlc-mapping-approval: "
        + receipt_json
        + b"\n"
        + f"# aio-sdlc-node: {INTENT_ID}\n".encode()
        + neutral
    )
    engine, source_path, _ = _project(tmp_path, annotated)
    before = source_path.read_bytes()

    with pytest.raises(MappingError, match="Unicode scalar"):
        engine.review_receipt_refresh(INTENT_ID)

    assert source_path.read_bytes() == before


@pytest.mark.parametrize("operation", ["candidate", "receipt"])
def test_mapping_approval_rejects_oversized_audit_text_before_write(
    tmp_path,
    operation,
):
    if operation == "candidate":
        engine, source_path, _ = _project(
            tmp_path,
            b"class RuntimeBoundary:\n    pass\n",
        )
        observed_id = _reality_id(tmp_path, "RuntimeBoundary")
        review = engine.review(INTENT_ID, candidate_reality_id=observed_id)

        invoke = partial(
            engine.approve,
            INTENT_ID,
            observed_id,
            review["evidence_digest"],
            selection_mode="explicit_observed_guid",
        )
    else:
        _, annotated = _confirmed_source()
        engine, source_path, _ = _project(tmp_path, annotated)
        review = engine.review_receipt_refresh(INTENT_ID)

        invoke = partial(
            engine.refresh_receipt,
            INTENT_ID,
            review["evidence_digest"],
        )

    before = source_path.read_bytes()

    with pytest.raises((MappingError, ValueError), match="at most"):
        invoke(_approval("x" * (17 * 1024)))

    assert source_path.read_bytes() == before


def test_receipt_review_rejects_symlinked_source_without_external_read_or_write(
    tmp_path,
):
    _, annotated = _confirmed_source()
    external = tmp_path.parent / f"{tmp_path.name}-external.py"
    external.write_bytes(annotated)
    source = tmp_path / "src" / "runtime.py"
    source.parent.mkdir(parents=True)
    try:
        os.symlink(external, source)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    intention_path = tmp_path / INTENTION_DAG_FILE
    intention_path.parent.mkdir(parents=True)
    DAGManager(
        Metadata(name="Source identity maintenance", version="1.0"),
        [
            Node(
                id=INTENT_ID,
                type=NodeType.COMPONENT,
                name="MCP SDK v2 Integration",
            )
        ],
        [],
    ).save(str(intention_path))
    engine = MappingEngine(tmp_path, intention_path)
    before = external.read_bytes()

    with pytest.raises(MappingError):
        engine.review_receipt_refresh(INTENT_ID)

    assert external.read_bytes() == before


def test_receipt_review_rejects_hardlinked_source_without_mutation(tmp_path):
    _, annotated = _confirmed_source()
    engine, source_path, _ = _project(tmp_path, annotated)
    alias = tmp_path / "source-alias.py"
    try:
        os.link(source_path, alias)
    except OSError as error:
        pytest.skip(f"hardlinks unavailable: {error}")
    before = source_path.read_bytes()

    with pytest.raises(MappingError, match="hardlink"):
        engine.review_receipt_refresh(INTENT_ID)

    assert source_path.read_bytes() == before
    assert alias.read_bytes() == before


def test_receipt_refresh_rolls_back_exact_bytes_when_postcondition_fails(
    tmp_path, monkeypatch
):
    _, annotated = _confirmed_source()
    engine, source_path, _ = _project(tmp_path, annotated)
    review = engine.review_receipt_refresh(INTENT_ID)
    before = source_path.read_bytes()

    def fail_verification(*_args, **_kwargs):
        raise MappingError("injected receipt verification failure")

    monkeypatch.setattr(engine, "_verify_receipt_refresh", fail_verification)
    with pytest.raises(MappingError, match="injected receipt verification failure"):
        engine.refresh_receipt(INTENT_ID, review["evidence_digest"], _approval())

    assert source_path.read_bytes() == before


def test_receipt_refresh_rejects_source_leaf_swap_before_transition(
    tmp_path, monkeypatch
):
    _, annotated = _confirmed_source()
    engine, source_path, _ = _project(tmp_path, annotated)
    review = engine.review_receipt_refresh(INTENT_ID)
    external = tmp_path / "external.py"
    external.write_bytes(b"EXTERNAL-DO-NOT-TOUCH\n")
    before = source_path.read_bytes()
    real_require = engine._require_snapshot_identity
    swapped = False

    def swapping_require(snapshot):
        nonlocal swapped
        if not swapped:
            swapped = True
            source_path.unlink()
            os.symlink(external, source_path)
        real_require(snapshot)

    monkeypatch.setattr(engine, "_require_snapshot_identity", swapping_require)
    with pytest.raises(MappingError, match="identity changed"):
        engine.refresh_receipt(INTENT_ID, review["evidence_digest"], _approval())

    assert swapped is True
    assert source_path.is_symlink() is True
    assert source_path.read_bytes() != before
    assert external.read_bytes() == b"EXTERNAL-DO-NOT-TOUCH\n"


@pytest.mark.parametrize("operation", ["candidate", "receipt"])
def test_mapping_transition_quarantines_leaf_swapped_after_identity_check(
    tmp_path,
    monkeypatch,
    operation,
):
    if operation == "candidate":
        original = b"class RuntimeBoundary:\n    pass\n"
        engine, source_path, _ = _project(tmp_path, original)
        observed_id = _reality_id(tmp_path, "RuntimeBoundary")
        review = engine.review(INTENT_ID, candidate_reality_id=observed_id)

        invoke = partial(
            engine.approve,
            INTENT_ID,
            observed_id,
            review["evidence_digest"],
            _approval(),
            selection_mode="explicit_observed_guid",
        )
    else:
        _, original = _confirmed_source()
        engine, source_path, _ = _project(tmp_path, original)
        review = engine.review_receipt_refresh(INTENT_ID)

        invoke = partial(
            engine.refresh_receipt,
            INTENT_ID,
            review["evidence_digest"],
            _approval(),
        )

    attacker = b"ATTACKER-UNIQUE-DATA\n"
    real_require = engine._require_snapshot_identity
    swapped = False

    def swap_after_check(snapshot):
        nonlocal swapped
        real_require(snapshot)
        if not swapped:
            swapped = True
            source_path.unlink()
            source_path.write_bytes(attacker)

    monkeypatch.setattr(engine, "_require_snapshot_identity", swap_after_check)
    with pytest.raises(MappingError, match="quarantined"):
        invoke()

    assert swapped is True
    assert source_path.read_bytes() == original
    quarantines = list(
        source_path.parent.glob(f".{source_path.name}.*.source-conflict")
    )
    assert len(quarantines) == 1
    assert quarantines[0].read_bytes() == attacker


@pytest.mark.parametrize("operation", ["candidate", "receipt"])
@pytest.mark.parametrize("attack", ["hardlink", "symlink"])
def test_mapping_transition_rejects_swapped_or_hardlinked_temporary_before_commit(
    tmp_path,
    monkeypatch,
    operation,
    attack,
):
    if operation == "candidate":
        original = b"class RuntimeBoundary:\n    pass\n"
        engine, source_path, _ = _project(tmp_path, original)
        observed_id = _reality_id(tmp_path, "RuntimeBoundary")
        review = engine.review(INTENT_ID, candidate_reality_id=observed_id)

        invoke = partial(
            engine.approve,
            INTENT_ID,
            observed_id,
            review["evidence_digest"],
            _approval(),
            selection_mode="explicit_observed_guid",
        )
    else:
        _, original = _confirmed_source()
        engine, source_path, _ = _project(tmp_path, original)
        review = engine.review_receipt_refresh(INTENT_ID)

        invoke = partial(
            engine.refresh_receipt,
            INTENT_ID,
            review["evidence_digest"],
            _approval(),
        )

    external = tmp_path / "external.py"
    external.write_bytes(b"EXTERNAL-UNCHANGED\n")
    alias = tmp_path / "attacker-hardlink.py"
    real_write = engine._write_source_temp

    def adversarial_write(target, content, *, mode):
        temporary = real_write(target, content, mode=mode)
        if attack == "hardlink":
            os.link(temporary, alias)
        else:
            temporary.unlink()
            os.symlink(external, temporary)
        return temporary

    monkeypatch.setattr(engine, "_write_source_temp", adversarial_write)
    with pytest.raises(MappingError, match="temporary"):
        invoke()

    assert source_path.is_symlink() is False
    assert source_path.read_bytes() == original
    assert external.read_bytes() == b"EXTERNAL-UNCHANGED\n"
    if attack == "hardlink":
        assert alias.is_file()


def test_mapping_final_temporary_check_swap_cannot_partially_commit(
    tmp_path,
    monkeypatch,
):
    original = b"class RuntimeBoundary:\n    pass\n"
    engine, source_path, _ = _project(tmp_path, original)
    observed_id = _reality_id(tmp_path, "RuntimeBoundary")
    review = engine.review(INTENT_ID, candidate_reality_id=observed_id)
    attacker = b"ATTACKER-TEMPORARY-DATA\n"
    real_require = engine._require_temporary_identity
    checks = 0
    swapped = False

    def swap_after_final_check(temporary, identity):
        nonlocal checks, swapped
        real_require(temporary, identity)
        checks += 1
        if checks == 2:
            temporary.unlink()
            temporary.write_bytes(attacker)
            swapped = True

    monkeypatch.setattr(
        engine,
        "_require_temporary_identity",
        swap_after_final_check,
    )
    with pytest.raises(MappingError, match="temporary identity changed"):
        engine.approve(
            INTENT_ID,
            observed_id,
            review["evidence_digest"],
            _approval(),
            selection_mode="explicit_observed_guid",
        )

    assert checks == 2
    assert source_path.read_bytes() == original
    if swapped:
        assert any(
            path.is_file() and path.read_bytes() == attacker
            for path in source_path.parent.iterdir()
        )


def test_mapping_ignores_mixed_case_runtime_cache_and_marker_string_literals(
    tmp_path,
):
    engine, source_path, _ = _project(
        tmp_path,
        b"class RuntimeBoundary:\n    pass\n",
    )
    cache = tmp_path / ".UV-CACHE"
    cache.mkdir()
    cached = cache / "cached.py"
    cached.write_bytes(b"class CachedDependency:\n    pass\n")
    try:
        os.link(cached, cache / "cached-alias.py")
    except OSError as error:
        pytest.skip(f"hardlinks unavailable: {error}")
    hidden = tmp_path / "src" / "literal.py"
    hidden.write_text(
        f'TEXT = """\n# aio-sdlc-node: {INTENT_ID}\n"""\n',
        encoding="utf-8",
    )
    observed_id = _reality_id(tmp_path, "RuntimeBoundary")

    review = engine.review(INTENT_ID, candidate_reality_id=observed_id)
    result = engine.approve(
        INTENT_ID,
        observed_id,
        review["evidence_digest"],
        _approval(),
        selection_mode="explicit_observed_guid",
    )

    assert result["postcondition"]["classification"] == "confirmed"
    assert source_path.read_bytes().count(b"aio-sdlc-node:") == 1


@pytest.mark.parametrize("operation", ["candidate", "receipt"])
def test_mapping_no_overwrite_install_preserves_newly_occupied_source_and_original(
    tmp_path,
    monkeypatch,
    operation,
):
    if operation == "candidate":
        original = b"class RuntimeBoundary:\n    pass\n"
        engine, source_path, _ = _project(tmp_path, original)
        observed_id = _reality_id(tmp_path, "RuntimeBoundary")
        review = engine.review(INTENT_ID, candidate_reality_id=observed_id)

        invoke = partial(
            engine.approve,
            INTENT_ID,
            observed_id,
            review["evidence_digest"],
            _approval(),
            selection_mode="explicit_observed_guid",
        )
    else:
        _, original = _confirmed_source()
        engine, source_path, _ = _project(tmp_path, original)
        review = engine.review_receipt_refresh(INTENT_ID)

        invoke = partial(
            engine.refresh_receipt,
            INTENT_ID,
            review["evidence_digest"],
            _approval(),
        )

    attacker = b"NEWLY-OCCUPIED-SOURCE\n"
    real_link = mapping_module.os.link
    occupied = False

    def occupy_before_install(source, destination, **kwargs):
        nonlocal occupied
        if Path(destination) == source_path and not occupied:
            occupied = True
            source_path.write_bytes(attacker)
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(mapping_module.os, "link", occupy_before_install)
    with pytest.raises(MappingError, match="occupied"):
        invoke()

    assert occupied is True
    assert source_path.read_bytes() == attacker
    quarantines = list(
        source_path.parent.glob(f".{source_path.name}.*.source-conflict")
    )
    assert len(quarantines) == 1
    assert quarantines[0].read_bytes() == original


@pytest.mark.parametrize("operation", ["candidate", "receipt"])
def test_mapping_private_backup_destination_is_never_overwritten(
    tmp_path,
    monkeypatch,
    operation,
):
    if operation == "candidate":
        original = b"class RuntimeBoundary:\n    pass\n"
        engine, source_path, _ = _project(tmp_path, original)
        observed_id = _reality_id(tmp_path, "RuntimeBoundary")
        review = engine.review(INTENT_ID, candidate_reality_id=observed_id)

        invoke = partial(
            engine.approve,
            INTENT_ID,
            observed_id,
            review["evidence_digest"],
            _approval(),
            selection_mode="explicit_observed_guid",
        )
    else:
        _, original = _confirmed_source()
        engine, source_path, _ = _project(tmp_path, original)
        review = engine.review_receipt_refresh(INTENT_ID)

        invoke = partial(
            engine.refresh_receipt,
            INTENT_ID,
            review["evidence_digest"],
            _approval(),
        )

    attacker = b"ATTACKER-BACKUP-DESTINATION\n"
    real_reserved = engine._unique_reserved_leaf
    occupied_paths = []

    def occupy_backup(target, *, suffix):
        reserved = real_reserved(target, suffix=suffix)
        if suffix == ".source-backup":
            reserved.write_bytes(attacker)
            occupied_paths.append(reserved)
        return reserved

    monkeypatch.setattr(engine, "_unique_reserved_leaf", occupy_backup)
    with pytest.raises(MappingError, match="destination became occupied"):
        invoke()

    assert source_path.read_bytes() == original
    assert len(occupied_paths) == 1
    assert occupied_paths[0].read_bytes() == attacker


def test_mapping_quarantine_destination_race_preserves_every_leaf(
    tmp_path,
    monkeypatch,
):
    original = b"class RuntimeBoundary:\n    pass\n"
    engine, source_path, _ = _project(tmp_path, original)
    observed_id = _reality_id(tmp_path, "RuntimeBoundary")
    review = engine.review(INTENT_ID, candidate_reality_id=observed_id)
    swapped_source = b"ATTACKER-SWAPPED-SOURCE\n"
    occupied_quarantine = b"ATTACKER-QUARANTINE-DESTINATION\n"
    real_require = engine._require_snapshot_identity
    real_reserved = engine._unique_reserved_leaf

    def swap_after_check(snapshot):
        real_require(snapshot)
        source_path.unlink()
        source_path.write_bytes(swapped_source)

    def occupy_quarantine(target, *, suffix):
        reserved = real_reserved(target, suffix=suffix)
        if suffix == ".source-conflict":
            reserved.write_bytes(occupied_quarantine)
        return reserved

    monkeypatch.setattr(engine, "_require_snapshot_identity", swap_after_check)
    monkeypatch.setattr(engine, "_unique_reserved_leaf", occupy_quarantine)
    with pytest.raises(MappingError):
        engine.approve(
            INTENT_ID,
            observed_id,
            review["evidence_digest"],
            _approval(),
            selection_mode="explicit_observed_guid",
        )

    assert source_path.read_bytes() == original
    surviving = [
        path.read_bytes() for path in source_path.parent.iterdir() if path.is_file()
    ]
    assert swapped_source in surviving
    assert occupied_quarantine in surviving


@pytest.mark.parametrize("operation", ["candidate", "receipt"])
def test_mapping_postverify_backup_swap_rolls_back_without_partial_commit(
    tmp_path,
    monkeypatch,
    operation,
):
    if operation == "candidate":
        original = b"class RuntimeBoundary:\n    pass\n"
        engine, source_path, _ = _project(tmp_path, original)
        observed_id = _reality_id(tmp_path, "RuntimeBoundary")
        review = engine.review(INTENT_ID, candidate_reality_id=observed_id)

        invoke = partial(
            engine.approve,
            INTENT_ID,
            observed_id,
            review["evidence_digest"],
            _approval(),
            selection_mode="explicit_observed_guid",
        )

        verify_name = "_verify_candidate_receipt"
    else:
        _, original = _confirmed_source()
        engine, source_path, _ = _project(tmp_path, original)
        review = engine.review_receipt_refresh(INTENT_ID)

        invoke = partial(
            engine.refresh_receipt,
            INTENT_ID,
            review["evidence_digest"],
            _approval(),
        )

        verify_name = "_verify_receipt_refresh"
    attacker = b"ATTACKER-CHANGED-BACKUP\n"
    real_verify = getattr(engine, verify_name)

    def verify_then_swap(*args, **kwargs):
        result = real_verify(*args, **kwargs)
        backups = list(source_path.parent.glob(f".{source_path.name}.*.source-backup"))
        assert len(backups) == 1
        backups[0].write_bytes(attacker)
        return result

    monkeypatch.setattr(engine, verify_name, verify_then_swap)
    with pytest.raises(MappingError, match="backup identity changed"):
        invoke()

    assert source_path.read_bytes() == original
    assert any(
        path.is_file() and path.read_bytes() == attacker
        for path in source_path.parent.iterdir()
    )


@pytest.mark.parametrize("operation", ["candidate", "receipt"])
def test_mapping_final_source_swap_after_backup_delete_restores_snapshot(
    tmp_path,
    monkeypatch,
    operation,
):
    if operation == "candidate":
        original = b"class RuntimeBoundary:\n    pass\n"
        engine, source_path, _ = _project(tmp_path, original)
        observed_id = _reality_id(tmp_path, "RuntimeBoundary")
        review = engine.review(INTENT_ID, candidate_reality_id=observed_id)
        invoke = partial(
            engine.approve,
            INTENT_ID,
            observed_id,
            review["evidence_digest"],
            _approval(),
            selection_mode="explicit_observed_guid",
        )
    else:
        _, original = _confirmed_source()
        engine, source_path, _ = _project(tmp_path, original)
        review = engine.review_receipt_refresh(INTENT_ID)
        invoke = partial(
            engine.refresh_receipt,
            INTENT_ID,
            review["evidence_digest"],
            _approval(),
        )
    attacker = b"ATTACKER-FINAL-SOURCE\n"
    real_unlink = mapping_module.os.unlink
    backup_unlinks = 0

    def swap_after_backup_delete(path, *args, **kwargs):
        nonlocal backup_unlinks
        result = real_unlink(path, *args, **kwargs)
        if str(path).endswith(".source-backup"):
            backup_unlinks += 1
            if backup_unlinks == 2:
                source_path.unlink()
                source_path.write_bytes(attacker)
        return result

    monkeypatch.setattr(mapping_module.os, "unlink", swap_after_backup_delete)
    with pytest.raises(MappingError, match="post-write source identity changed"):
        invoke()

    assert backup_unlinks == 2
    assert source_path.read_bytes() == original
    assert any(
        path.is_file() and path.read_bytes() == attacker
        for path in source_path.parent.iterdir()
    )


def test_concurrent_receipt_refresh_has_one_winner_and_no_corruption(tmp_path):
    _, annotated = _confirmed_source()
    engine, source_path, _ = _project(tmp_path, annotated)
    review = engine.review_receipt_refresh(INTENT_ID)

    def refresh():
        try:
            return engine.refresh_receipt(
                INTENT_ID,
                review["evidence_digest"],
                _approval(),
            )
        except MappingError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: refresh(), range(2)))

    assert sum(isinstance(result, dict) for result in results) == 1
    assert (
        sum(
            isinstance(result, MappingError)
            and "stale receipt evidence digest" in str(result)
            for result in results
        )
        == 1
    )
    content = source_path.read_bytes()
    assert content.count(b"aio-sdlc-node:") == 1
    assert content.count(b"aio-sdlc-mapping-approval:") == 1
    compile(content, str(source_path), "exec")


@pytest.mark.parametrize("operation", ["candidate", "receipt"])
def test_mapping_transition_holds_intention_lock_through_source_commit(
    tmp_path,
    monkeypatch,
    operation,
):
    if operation == "candidate":
        engine, source_path, intention_path = _project(
            tmp_path,
            b"class RuntimeBoundary:\n    pass\n",
        )
        observed_id = _reality_id(tmp_path, "RuntimeBoundary")
        review = engine.review(INTENT_ID, candidate_reality_id=observed_id)

        invoke = partial(
            engine.approve,
            INTENT_ID,
            observed_id,
            review["evidence_digest"],
            _approval(),
            selection_mode="explicit_observed_guid",
        )
    else:
        _, annotated = _confirmed_source()
        engine, source_path, intention_path = _project(tmp_path, annotated)
        review = engine.review_receipt_refresh(INTENT_ID)

        invoke = partial(
            engine.refresh_receipt,
            INTENT_ID,
            review["evidence_digest"],
            _approval(),
        )

    original_transition = engine._transition_source
    writer_started = threading.Event()
    writer_finished = threading.Event()
    writer_errors = []
    writer = None

    def change_intent():
        writer_started.set()
        try:
            mutate_dag_file(
                intention_path,
                lambda manager: setattr(
                    manager.nodes[INTENT_ID],
                    "description",
                    "CONCURRENTLY CHANGED SEMANTICS",
                ),
            )
        except Exception as error:  # noqa: BLE001 - asserted across thread boundary
            writer_errors.append(error)
        finally:
            writer_finished.set()

    def transition_while_writer_waits(snapshot, updated, verify):
        nonlocal writer
        writer = threading.Thread(target=change_intent)
        writer.start()
        assert writer_started.wait(timeout=2)
        assert not writer_finished.wait(timeout=0.2)
        return original_transition(snapshot, updated, verify)

    monkeypatch.setattr(engine, "_transition_source", transition_while_writer_waits)
    result = invoke()
    assert writer is not None
    writer.join(timeout=3)

    assert not writer.is_alive()
    assert writer_errors == []
    assert writer_finished.is_set()
    assert result["postcondition"]["classification"] == "confirmed"
    assert b"aio-sdlc-node:" in source_path.read_bytes()
    assert (
        DAGManager.load(str(intention_path)).nodes[INTENT_ID].description
        == "CONCURRENTLY CHANGED SEMANTICS"
    )


def test_explicit_review_cli_and_mcp_json_match_python(tmp_path):
    source = b"class RuntimeBoundary:\n    pass\n"
    engine, _, _ = _project(tmp_path, source)
    observed_id = _reality_id(tmp_path, "RuntimeBoundary")
    expected = engine.review(INTENT_ID, candidate_reality_id=observed_id)

    cli_result = CliRunner().invoke(
        cli,
        [
            "mapping",
            "review",
            "--project-path",
            str(tmp_path),
            "--intent-id",
            INTENT_ID,
            "--candidate-reality-id",
            observed_id,
            "--format",
            "json",
        ],
    )
    mcp_result = mcp_server_module.review_mapping(
        intent_id=INTENT_ID,
        candidate_reality_id=observed_id,
        project_path=str(tmp_path),
    )

    assert cli_result.exit_code == 0
    assert json.loads(cli_result.output) == expected
    assert json.loads(mcp_result) == expected


def test_receipt_review_cli_and_mcp_json_match_python(tmp_path):
    _, annotated = _confirmed_source()
    engine, _, _ = _project(tmp_path, annotated)
    expected = engine.review_receipt_refresh(INTENT_ID)

    cli_result = CliRunner().invoke(
        cli,
        [
            "mapping",
            "receipt",
            "review",
            "--project-path",
            str(tmp_path),
            "--intent-id",
            INTENT_ID,
            "--format",
            "json",
        ],
    )
    mcp_result = mcp_server_module.review_mapping_receipt(
        intent_id=INTENT_ID,
        project_path=str(tmp_path),
    )

    assert cli_result.exit_code == 0
    assert json.loads(cli_result.output) == expected
    assert json.loads(mcp_result) == expected


def test_receipt_refresh_cli_and_mcp_json_match_python(tmp_path):
    _, annotated = _confirmed_source()
    base = tmp_path / "base"
    _project(base, annotated)
    python_project = tmp_path / "python"
    cli_project = tmp_path / "cli"
    mcp_project = tmp_path / "mcp"
    for project in (python_project, cli_project, mcp_project):
        shutil.copytree(base, project)

    python_engine = MappingEngine(
        python_project,
        python_project / INTENTION_DAG_FILE,
    )
    review = python_engine.review_receipt_refresh(INTENT_ID)
    expected = python_engine.refresh_receipt(
        INTENT_ID,
        review["evidence_digest"],
        _approval(),
    )
    cli_result = CliRunner().invoke(
        cli,
        [
            "mapping",
            "receipt",
            "refresh",
            "--project-path",
            str(cli_project),
            "--intent-id",
            INTENT_ID,
            "--evidence-digest",
            review["evidence_digest"],
            "--approved-by",
            "Felix",
            "--approved-at",
            "2026-08-21T21:30:00+00:00",
            "--rationale",
            "Reviewed exact source identity evidence.",
        ],
    )
    mcp_result = mcp_server_module.refresh_mapping_receipt(
        intent_id=INTENT_ID,
        evidence_digest=review["evidence_digest"],
        approved_by="Felix",
        approved_at="2026-08-21T21:30:00+00:00",
        rationale="Reviewed exact source identity evidence.",
        project_path=str(mcp_project),
    )

    assert cli_result.exit_code == 0
    assert json.loads(cli_result.output) == expected
    assert json.loads(mcp_result) == expected
