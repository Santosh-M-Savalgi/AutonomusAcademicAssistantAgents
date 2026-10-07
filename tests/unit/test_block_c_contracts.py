"""Pure Block C deterministic adapters and identifier-only observability."""

from uuid import uuid4

from packages.domain import (
    DiagnosticReservation,
    DiagnosticRunState,
    RuntimeObservation,
    SourceIdentity,
    SourceKind,
    deterministic_diagnostic_result,
)
from tests.unit.test_runtime_contracts import AT


def reservation() -> DiagnosticReservation:
    return DiagnosticReservation(
        reservation_id=uuid4(), diagnostic_run_id=uuid4(), graph_version_id=uuid4(),
        execution_id=uuid4(), question_version_id=uuid4(), target_concept_id=uuid4(),
        item_budget=12, slot=1, state="RESERVED", version=1,
        reserved_at=AT,
    )


def test_diagnostic_adapter_is_replayable_and_contains_no_content() -> None:
    value = reservation()
    first = deterministic_diagnostic_result(value, correct=1.0)
    second = deterministic_diagnostic_result(value, correct=1.0)
    assert first == second
    assert b"answer" not in first.result_bytes
    assert first.reservation_id == value.reservation_id


def test_identifier_only_observation_has_no_learner_content_fields() -> None:
    observation = RuntimeObservation(
        operation="diagnostic.complete", outcome="ASSESSED", learner_id=uuid4(),
        source_id=uuid4(), execution_id=uuid4(),
    )
    identifiers = observation.identifiers()
    assert identifiers["operation"] == "diagnostic.complete"
    assert "answer" not in identifiers
    assert "content" not in identifiers


def test_source_identity_remains_separate_from_diagnostic_state() -> None:
    source = SourceIdentity(kind=SourceKind.EVENT, source_id=uuid4())
    assert source.kind == SourceKind.EVENT
    assert DiagnosticRunState.OPEN.value == "OPEN"
