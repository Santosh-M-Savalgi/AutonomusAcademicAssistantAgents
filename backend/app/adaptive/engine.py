"""Mastery Evaluation Engine — deterministic multi-factor scoring.

Evaluates topic mastery using configurable weighted scoring across
multiple factors: quiz scores, attempt count, time decay, historical
performance, repeated failures, confidence, concept mastery, trend,
and recent activity.

No LLM calls. Pure deterministic computation.

Reference: Sprint 8 Part 3.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import exp

from app.adaptive.models import (
    Explanation,
    MasteryEvaluation,
    MasteryState,
)
from app.db.models import ConceptMastery, QuizAttempt


# ── Weight Configuration ───────────────────────────────────────────────────


@dataclass
class MasteryWeights:
    """Configurable weights for mastery evaluation factors.

    All weights should sum to approximately 1.0.
    """

    quiz_score: float = 0.35
    """Weight for the most recent quiz score."""

    historical_performance: float = 0.20
    """Weight for average historical quiz performance."""

    attempt_count: float = 0.10
    """Weight for the number of attempts (more = higher confidence)."""

    time_decay: float = 0.10
    """Weight for recency — recent study boosts score."""

    confidence_score: float = 0.10
    """Weight for the system's confidence in the evaluation."""

    trend_direction: float = 0.10
    """Weight for whether scores are improving or declining."""

    repeated_failures: float = 0.05
    """Penalty weight for consecutive failures."""

    recent_activity: float = 0.0
    """Bonus for recent activity (folded into time_decay)."""

    def __post_init__(self) -> None:
        """Validate weights sum is reasonable."""
        total = (
            self.quiz_score
            + self.historical_performance
            + self.attempt_count
            + self.time_decay
            + self.confidence_score
            + self.trend_direction
            + self.repeated_failures
            + self.recent_activity
        )
        if abs(total - 1.0) > 0.05:
            # Not a hard error — weights can exceed 1.0 or be below
            pass


# ── Default Weights ────────────────────────────────────────────────────────


DEFAULT_WEIGHTS = MasteryWeights()


# ── Mastery Evaluation Engine ──────────────────────────────────────────────


class AdaptiveEngine:
    """Deterministic mastery evaluation engine.

    Computes multi-factor mastery scores from raw quiz attempt data
    and ConceptMastery rows. Classifies each topic into a MasteryState
    using deterministic state-transition rules.

    Usage::

        engine = AdaptiveEngine()
        evaluation = engine.evaluate(
            topic_id=topic_id,
            topic_name="Python Basics",
            mastery_row=cm_row,
            quiz_attempts=[...],
            threshold=0.75,
        )
    """

    # ── Constants ──────────────────────────────────────────────────────────

    # Time decay half-life in hours (7 days)
    TIME_DECAY_HALF_LIFE: float = 168.0

    # Threshold for "recent" activity (7 days in hours)
    RECENT_THRESHOLD_HOURS: float = 168.0

    # Maximum repeated failures before escalation
    MAX_REPEATED_FAILURES: int = 3

    # Score threshold for determining consecutive failures
    FAILURE_THRESHOLD: float = 0.50

    # Minimum attempts for high-confidence evaluation
    MIN_ATTEMPTS_FOR_CONFIDENCE: int = 3

    def __init__(self, weights: MasteryWeights | None = None) -> None:
        """Initialize the evaluation engine.

        Args:
            weights: Optional custom factor weights. Uses DEFAULT_WEIGHTS if None.
        """
        self._weights = weights if weights is not None else DEFAULT_WEIGHTS

    # ── Public API ─────────────────────────────────────────────────────────

    def evaluate(
        self,
        topic_id: uuid.UUID,
        topic_name: str,
        mastery_row: ConceptMastery | None = None,
        quiz_attempts: list[QuizAttempt] | None = None,
        threshold: float = 0.75,
        now: datetime | None = None,
    ) -> MasteryEvaluation:
        """Evaluate mastery for a single topic.

        Args:
            topic_id: The topic UUID.
            topic_name: Human-readable topic name.
            mastery_row: Optional ConceptMastery row from the database.
            quiz_attempts: Optional list of QuizAttempt rows for this topic.
            threshold: Mastery threshold for this topic.
            now: Reference time (defaults to UTC now).

        Returns:
            A ``MasteryEvaluation`` with the computed score, state, and factors.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        quiz_attempts = quiz_attempts or []
        quiz_scores = [a.score for a in quiz_attempts]

        # Factor 1: Quiz score (most recent)
        latest_score = quiz_scores[-1] if quiz_scores else 0.0
        factor_quiz = latest_score

        # Factor 2: Historical performance (average of all scores)
        avg_score = sum(quiz_scores) / len(quiz_scores) if quiz_scores else 0.0
        factor_historical = avg_score

        # Factor 3: Attempt count (normalized, 0–1)
        attempt_count = mastery_row.attempts_count if mastery_row else len(quiz_attempts)
        factor_attempts = min(attempt_count / self.MIN_ATTEMPTS_FOR_CONFIDENCE, 1.0)

        # Factor 4: Time decay
        time_since = self._compute_time_since(mastery_row, quiz_attempts, now)
        factor_time = self._time_decay_factor(time_since)

        # Factor 5: Confidence
        factor_confidence = self._compute_confidence(
            mastery_row, quiz_attempts, attempt_count
        )

        # Factor 6: Trend direction
        trend, trend_dir = self._compute_trend(quiz_scores)
        factor_trend = self._normalize_trend(trend, trend_dir)

        # Factor 7: Repeated failures
        repeated_failures = self._count_repeated_failures(quiz_scores)
        factor_failures = self._failure_penalty(repeated_failures)

        # Factor 8: Recent activity
        is_recent = time_since <= self.RECENT_THRESHOLD_HOURS

        # Aggregate score
        aggregate_score = self._aggregate(
            quiz=factor_quiz,
            historical=factor_historical,
            attempts=factor_attempts,
            time=factor_time,
            confidence=factor_confidence,
            trend=factor_trend,
            failures=factor_failures,
        )

        # Clamp
        aggregate_score = max(0.0, min(1.0, aggregate_score))

        # Determine mastery state
        mastery_state = self._classify_state(
            score=aggregate_score,
            threshold=threshold,
            attempt_count=attempt_count,
            repeated_failures=repeated_failures,
            time_since_hours=time_since,
        )

        return MasteryEvaluation(
            topic_id=topic_id,
            topic_name=topic_name,
            mastery_state=mastery_state,
            score=round(aggregate_score, 4),
            confidence=round(factor_confidence, 4),
            quiz_scores=quiz_scores,
            attempt_count=attempt_count,
            time_since_last_study_hours=round(time_since, 1),
            historical_trend=round(trend, 4),
            repeated_failures=repeated_failures,
            trend_direction=trend_dir,
            recent_activity=is_recent,
            factors={
                "quiz_score": round(factor_quiz, 4),
                "historical_performance": round(factor_historical, 4),
                "attempt_count": round(factor_attempts, 4),
                "time_decay": round(factor_time, 4),
                "confidence": round(factor_confidence, 4),
                "trend_direction": round(factor_trend, 4),
                "repeated_failures": round(factor_failures, 4),
                "threshold": threshold,
            },
        )

    def evaluate_prerequisites(
        self,
        topic_id: uuid.UUID,
        topic_name: str,
        prerequisite_ids: set[uuid.UUID],
        mastery_map: dict[uuid.UUID, ConceptMastery],
        quiz_attempts_map: dict[uuid.UUID, list[QuizAttempt]],
        topic_names: dict[uuid.UUID, str],
        thresholds: dict[uuid.UUID, float] | None = None,
    ) -> dict[uuid.UUID, MasteryEvaluation]:
        """Evaluate mastery for all prerequisites of a topic.

        Args:
            topic_id: The topic whose prerequisites to evaluate.
            topic_name: Name of the parent topic (for logging).
            prerequisite_ids: Set of prerequisite topic IDs.
            mastery_map: ConceptMastery rows keyed by topic_id.
            quiz_attempts_map: Quiz attempts keyed by topic_id.
            topic_names: Topic names keyed by topic_id.
            thresholds: Optional per-topic thresholds keyed by topic_id.

        Returns:
            Dict of topic_id → MasteryEvaluation.
        """
        results: dict[uuid.UUID, MasteryEvaluation] = {}
        for pid in prerequisite_ids:
            name = topic_names.get(pid, f"topic-{pid}")
            threshold = (thresholds or {}).get(pid, 0.75)
            results[pid] = self.evaluate(
                topic_id=pid,
                topic_name=name,
                mastery_row=mastery_map.get(pid),
                quiz_attempts=quiz_attempts_map.get(pid, []),
                threshold=threshold,
            )
        return results

    # ── Factor Computations ────────────────────────────────────────────────

    def _compute_time_since(
        self,
        mastery_row: ConceptMastery | None,
        quiz_attempts: list[QuizAttempt],
        now: datetime,
    ) -> float:
        """Compute hours since last study activity."""
        last_time: datetime | None = None
        if mastery_row and mastery_row.last_practiced_at:
            last_time = mastery_row.last_practiced_at
        if quiz_attempts:
            for a in reversed(quiz_attempts):
                if a.submitted_at:
                    candidate = a.submitted_at.replace(tzinfo=timezone.utc)
                    if last_time is None or candidate > last_time:
                        last_time = candidate
        if last_time is None:
            return float("inf")  # never studied
        delta = now.replace(tzinfo=timezone.utc) - last_time.replace(tzinfo=timezone.utc)
        return delta.total_seconds() / 3600.0

    def _time_decay_factor(self, hours_since: float) -> float:
        """Compute time decay factor using exponential decay.

        0 hours = 1.0 (recent), HALF_LIFE hours = 0.5, etc.
        """
        if hours_since == float("inf"):
            return 0.0
        return exp(-hours_since * 0.693147 / self.TIME_DECAY_HALF_LIFE)

    def _compute_confidence(
        self,
        mastery_row: ConceptMastery | None,
        quiz_attempts: list[QuizAttempt],
        attempt_count: int,
    ) -> float:
        """Compute confidence in the evaluation.

        Confidence grows with attempts and is higher when scores are consistent.
        """
        if attempt_count == 0:
            return 0.0

        # Base confidence from stored value or attempt-based logistic
        if mastery_row and mastery_row.confidence > 0:
            base = mastery_row.confidence
        else:
            base = min(0.95 * (1.0 - 1.0 / (1.0 + attempt_count * 0.5)), 0.95)

        # Variance penalty: high variance reduces confidence
        scores = [a.score for a in quiz_attempts[-5:]]
        if len(scores) >= 2:
            mean = sum(scores) / len(scores)
            variance = sum((s - mean) ** 2 for s in scores) / len(scores)
            variance_penalty = min(variance * 2.0, 0.3)
            base = max(0.0, base - variance_penalty)

        return round(base, 4)

    def _compute_trend(self, scores: list[float]) -> tuple[float, str]:
        """Compute trend direction from quiz scores.

        Returns:
            (trend_value, trend_direction) where trend_value is:
            positive = improving, negative = declining, 0 = stable.
        """
        if len(scores) < 2:
            return 0.0, "stable"

        # Simple linear trend over last N scores
        recent = scores[-5:]
        if len(recent) < 2:
            return 0.0, "stable"

        n = len(recent)
        x_mean = (n - 1) / 2.0
        y_mean = sum(recent) / n

        num = sum((i - x_mean) * (recent[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))

        if den == 0:
            return 0.0, "stable"

        slope = num / den

        if slope > 0.05:
            direction = "improving"
        elif slope < -0.05:
            direction = "declining"
        else:
            direction = "stable"

        return slope, direction

    def _normalize_trend(self, trend: float, direction: str) -> float:
        """Normalize trend to 0–1 range where 1 = strongly improving."""
        if direction == "improving":
            return min(0.5 + trend * 5.0, 1.0)
        elif direction == "declining":
            return max(0.5 + trend * 5.0, 0.0)
        else:
            return 0.5

    def _count_repeated_failures(self, scores: list[float]) -> int:
        """Count consecutive sub-threshold quiz attempts (most recent first)."""
        count = 0
        for s in reversed(scores):
            if s < self.FAILURE_THRESHOLD:
                count += 1
            else:
                break
        return count

    def _failure_penalty(self, repeated_failures: int) -> float:
        """Compute penalty factor from repeated failures.

        0 failures = 1.0 (no penalty), 3+ = 0.0 (maximum penalty).
        """
        if repeated_failures == 0:
            return 1.0
        return max(0.0, 1.0 - (repeated_failures / self.MAX_REPEATED_FAILURES))

    # ── Aggregation ────────────────────────────────────────────────────────

    def _aggregate(
        self,
        quiz: float,
        historical: float,
        attempts: float,
        time: float,
        confidence: float,
        trend: float,
        failures: float,
    ) -> float:
        """Aggregate factor scores using configured weights.

        The failure factor is applied as a multiplicative penalty, not an
        additive weight, so repeated failures can significantly reduce the
        aggregate even if other factors are strong.
        """
        w = self._weights
        base = (
            w.quiz_score * quiz
            + w.historical_performance * historical
            + w.attempt_count * attempts
            + w.time_decay * time
            + w.confidence_score * confidence
            + w.trend_direction * trend
        )
        # Apply failure penalty multiplicatively
        base *= failures
        return base

    # ── State Classification ───────────────────────────────────────────────

    def _classify_state(
        self,
        score: float,
        threshold: float,
        attempt_count: int,
        repeated_failures: int,
        time_since_hours: float,
    ) -> MasteryState:
        """Classify a topic into a MasteryState using deterministic rules.

        State transitions:
        - No attempts → NOT_STARTED
        - Attempts but no quiz submitted → LEARNING
        - Attempts with quiz, score < threshold → PRACTICING
        - Score >= threshold → MASTERED
        - Previously mastered, score dropped → REVIEW_REQUIRED
        - Repeated failures on dependent topics → REGRESSED
        """
        if attempt_count == 0:
            return MasteryState.NOT_STARTED

        if score >= threshold:
            # Check for regression risk: declining trend with recent failures
            if repeated_failures >= 2:
                return MasteryState.REVIEW_REQUIRED
            return MasteryState.MASTERED

        # Below threshold
        if repeated_failures >= self.MAX_REPEATED_FAILURES:
            return MasteryState.REGRESSED

        if time_since_hours > self.RECENT_THRESHOLD_HOURS * 2:
            # Stale — hasn't studied in 14+ days
            return MasteryState.REVIEW_REQUIRED

        return MasteryState.PRACTICING

    def determine_state(
        self,
        score: float,
        threshold: float = 0.75,
        attempt_count: int = 0,
        repeated_failures: int = 0,
        time_since_hours: float = 0.0,
    ) -> MasteryState:
        """Public shortcut: determine mastery state from raw inputs.

        Args:
            score: Aggregate mastery score (0.0–1.0).
            threshold: Mastery threshold.
            attempt_count: Number of quiz attempts.
            repeated_failures: Consecutive sub-threshold attempts.
            time_since_hours: Hours since last study.

        Returns:
            The computed MasteryState.
        """
        return self._classify_state(
            score=score,
            threshold=threshold,
            attempt_count=attempt_count,
            repeated_failures=repeated_failures,
            time_since_hours=time_since_hours,
        )
