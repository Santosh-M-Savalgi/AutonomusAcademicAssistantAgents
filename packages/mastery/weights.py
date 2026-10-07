"""Pure v1 weighting functions."""

from packages.domain.mastery import EvidenceInput, WeightSnapshot


def correct_difficulty_weight(difficulty: int) -> float:
    if difficulty in (1, 2):
        return 0.7
    if difficulty == 3:
        return 1.0
    if difficulty in (4, 5):
        return 1.3
    raise ValueError("Difficulty must be between 1 and 5")


def incorrect_difficulty_weight(difficulty: int) -> float:
    if difficulty in (1, 2):
        return 1.3
    if difficulty == 3:
        return 1.0
    if difficulty in (4, 5):
        return 0.7
    raise ValueError("Difficulty must be between 1 and 5")


def type_weight(evidence: EvidenceInput) -> float:
    if evidence.grader_level == "L2_LLM_RUBRIC":
        return evidence.grader_confidence
    if evidence.question_type == "MCQ":
        if evidence.n_options is None or evidence.n_options < 2:
            raise ValueError("MCQ evidence requires at least two options")
        return 0.6 * (1.0 - 1.0 / evidence.n_options)
    if evidence.question_type == "TRUE_FALSE":
        return 0.4
    if evidence.question_type == "NUMERIC":
        return 1.0
    if evidence.question_type == "SHORT_TEXT":
        return 0.9
    if evidence.question_type == "CODE":
        return 1.2
    raise ValueError(f"Unsupported question type: {evidence.question_type}")


def correct_hint_factor(hints_used: int) -> float:
    if hints_used == 0:
        return 1.0
    if hints_used == 1:
        return 0.5
    if hints_used >= 2:
        return 0.25
    raise ValueError("Hints used cannot be negative")


def calculate_weight_snapshot(evidence: EvidenceInput) -> WeightSnapshot:
    """Calculate and freeze both approved partial-credit weight components."""

    tag_confidence = min(1.0, max(0.5, evidence.tag_confidence))
    correct_difficulty = correct_difficulty_weight(evidence.difficulty)
    incorrect_difficulty = incorrect_difficulty_weight(evidence.difficulty)
    question_type = type_weight(evidence)
    hint = correct_hint_factor(evidence.hints_used)
    return WeightSnapshot(
        correct_difficulty_weight=correct_difficulty,
        incorrect_difficulty_weight=incorrect_difficulty,
        type_weight=question_type,
        correct_hint_factor=hint,
        tag_confidence=tag_confidence,
        w_correct=correct_difficulty * question_type * hint * tag_confidence,
        w_incorrect=incorrect_difficulty * question_type * tag_confidence,
    )
