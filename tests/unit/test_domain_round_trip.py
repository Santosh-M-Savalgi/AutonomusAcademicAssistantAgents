"""JSON round-trip coverage for the Phase 0 domain contracts."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import BaseModel

from packages.domain import (
    AnswerEvidence,
    AnswerKey,
    BlockValidation,
    LearningEvent,
    LearningEventType,
    LessonBlock,
    PlannerAction,
    PlannerDecision,
    Question,
    ReasonCode,
    RubricItem,
    VersionStamp,
)

COURSE_ID = UUID("00000000-0000-0000-0000-000000000001")
STUDENT_ID = UUID("00000000-0000-0000-0000-000000000002")
CHUNK_ID = UUID("00000000-0000-0000-0000-000000000003")


@pytest.fixture
def versions() -> VersionStamp:
    return VersionStamp(
        model_id="mock-model",
        adapter_version="adapter_v1",
        prompt_version="prompt_v1",
        retrieval_version="retrieval_v1",
        mastery_policy_version="mastery_v1",
        planner_policy_version="planner_v1",
    )


def test_all_contracts_round_trip_json(versions: VersionStamp) -> None:
    validation = BlockValidation(citation_ok=True, length_ok=True, reading_level=True)
    answer_key = AnswerKey(kind="exact", value="42")
    rubric_item = RubricItem(criterion_id="criterion-1", description="Shows the method", points=1)
    models: list[BaseModel] = [
        PlannerDecision(
            action=PlannerAction.TEACH_CURRENT_TOPIC,
            target_id="topic-1",
            reason_codes=[ReasonCode.LOW_EVIDENCE],
            evidence_ids=[CHUNK_ID],
            confidence=0.8,
            policy_outcome="ALLOW",
            plan_version=1,
            planner_policy_version="planner_v1",
            explanation="Evidence is limited.",
        ),
        LessonBlock(
            block_type="EXPLANATION",
            concept_ids=["concept-1"],
            content_md="A short explanation.",
            difficulty="easy",
            source_chunk_ids=[CHUNK_ID],
            grounded=True,
            validation=validation,
            versions=versions,
        ),
        Question(
            question_id=CHUNK_ID,
            course_id=COURSE_ID,
            topic_id="topic-1",
            concept_ids=["concept-1"],
            prerequisite_concept_ids=[],
            learning_objective_ids=["objective-1"],
            question_type="NUMERIC",
            cognitive_skill="apply",
            difficulty=3,
            stem="What is six times seven?",
            options=None,
            answer_key=answer_key,
            rubric=[rubric_item],
            expected_misconception_ids=[],
            source_chunk_ids=[CHUNK_ID],
            lesson_block_ids=[CHUNK_ID],
            tag_confidence=0.95,
            fingerprint_embedding_id=CHUNK_ID,
            status="ACTIVE",
        ),
        AnswerEvidence(
            evidence_id=CHUNK_ID,
            student_id=STUDENT_ID,
            question_id=CHUNK_ID,
            attempt_id=CHUNK_ID,
            correct=1.0,
            grader_level="L0_RULE",
            grader_confidence=1.0,
            hints_used=0,
            latency_ms=12,
            kind="DIRECT",
            concept_credit={"concept-1": 1.0},
        ),
        LearningEvent(
            event_id=CHUNK_ID,
            type=LearningEventType.ANSWER_GRADED,
            student_id=STUDENT_ID,
            course_id=COURSE_ID,
            payload={"evidence_id": str(CHUNK_ID)},
            correlation_id=CHUNK_ID,
            created_at=datetime.now(UTC),
            versions=versions,
        ),
    ]

    for model in models:
        restored = type(model).model_validate_json(model.model_dump_json())
        assert restored == model
