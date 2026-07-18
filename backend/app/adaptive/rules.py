"""Adaptive Rules Engine — configurable, deterministic decision rules.

Provides a rule-based system for making adaptive learning decisions.
Rules are configurable rather than hardcoded, with sensible defaults.

Reference: Sprint 8 Part 6.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable

from app.adaptive.models import (
    DecisionType,
    Explanation,
    MasteryEvaluation,
    MasteryState,
)
from app.services.knowledge_graph_service import KnowledgeGraph


# ── Rule Definition ─────────────────────────────────────────────────────────


@dataclass
class AdaptiveRule:
    """A single adaptive decision rule.

    Rules are evaluated in priority order (lowest = highest priority).
    The first matching rule produces the decision.
    """

    name: str
    """Human-readable rule name for explanation and debugging."""

    priority: int
    """Lower number = higher priority. Evaluated in ascending order."""

    condition: Callable[[RuleContext], bool]
    """Predicate: returns True if this rule should fire."""

    action: DecisionType
    """The decision to emit when this rule fires."""

    description: str = ""
    """Human-readable description of what this rule does."""


@dataclass
class RuleContext:
    """Context passed to rule condition functions for evaluation."""

    evaluation: MasteryEvaluation
    """Current mastery evaluation for the topic."""

    prerequisite_mastery: dict[uuid.UUID, MasteryEvaluation]
    """Mastery states of all direct prerequisites."""

    graph: KnowledgeGraph | None = None
    """Optional knowledge graph for prerequisite traversal."""

    repeated_failures_global: int = 0
    """Total repeated failures across all topics."""

    max_prerequisite_depth: int = 3
    """Maximum depth for prerequisite traversal."""


# ── Default Rule Set ───────────────────────────────────────────────────────


def _default_rules() -> list[AdaptiveRule]:
    """Return the default adaptive rule set.

    Rules are evaluated in priority order. The first matching rule wins.
    """

    def _is_not_started(ctx: RuleContext) -> bool:
        return ctx.evaluation.mastery_state == MasteryState.NOT_STARTED

    def _is_learning(ctx: RuleContext) -> bool:
        return ctx.evaluation.mastery_state == MasteryState.LEARNING

    def _is_practicing_below_threshold(ctx: RuleContext) -> bool:
        return (
            ctx.evaluation.mastery_state == MasteryState.PRACTICING
            and ctx.evaluation.score < 0.5
            and ctx.evaluation.repeated_failures < 3
        )

    def _is_practicing_repeated_failures(ctx: RuleContext) -> bool:
        return (
            ctx.evaluation.mastery_state == MasteryState.PRACTICING
            and ctx.evaluation.repeated_failures >= 3
        )

    def _is_practicing_approaching(ctx: RuleContext) -> bool:
        return (
            ctx.evaluation.mastery_state == MasteryState.PRACTICING
            and 0.5 <= ctx.evaluation.score < ctx.evaluation.factors.get("threshold", 0.75)
        )

    def _is_mastered(ctx: RuleContext) -> bool:
        return ctx.evaluation.mastery_state == MasteryState.MASTERED

    def _is_review_required(ctx: RuleContext) -> bool:
        return ctx.evaluation.mastery_state == MasteryState.REVIEW_REQUIRED

    def _is_regressed(ctx: RuleContext) -> bool:
        return ctx.evaluation.mastery_state == MasteryState.REGRESSED

    def _prerequisites_weak(ctx: RuleContext) -> bool:
        """Check if any prerequisite is below mastery threshold."""
        for pid, meval in ctx.prerequisite_mastery.items():
            if meval.mastery_state in (
                MasteryState.NOT_STARTED,
                MasteryState.LEARNING,
                MasteryState.PRACTICING,
            ):
                return True
        return False

    def _all_complete(ctx: RuleContext) -> bool:
        return ctx.evaluation.mastery_state == MasteryState.MASTERED

    return [
        # Priority 0: Not started → learn
        AdaptiveRule(
            name="not_started_to_learning",
            priority=0,
            condition=_is_not_started,
            action=DecisionType.ADVANCE,
            description="Topic not yet started — advance to first lesson.",
        ),
        # Priority 1: Learning → advance to practice
        AdaptiveRule(
            name="learning_to_practice",
            priority=1,
            condition=_is_learning,
            action=DecisionType.PRACTICE,
            description="Topic in learning phase — move to practice/quiz.",
        ),
        # Priority 2: Repeated failures → diagnose prerequisite
        AdaptiveRule(
            name="repeated_failures_diagnose",
            priority=2,
            condition=_is_practicing_repeated_failures,
            action=DecisionType.REMEDIATE,
            description="Repeated failures detected — diagnose prerequisite gaps.",
        ),
        # Priority 3: Prerequisites weak → revisit prerequisite
        AdaptiveRule(
            name="prerequisite_weak_revisit",
            priority=3,
            condition=_prerequisites_weak,
            action=DecisionType.PREREQUISITE,
            description="Prerequisites are weak — revisit prerequisite topic first.",
        ),
        # Priority 4: Practicing but below 0.5 → reteach
        AdaptiveRule(
            name="practicing_below_reteach",
            priority=4,
            condition=_is_practicing_below_threshold,
            action=DecisionType.RETEACH,
            description="Score below 50% — re-teach the current topic.",
        ),
        # Priority 5: Practicing approaching threshold → practice more
        AdaptiveRule(
            name="practicing_approaching_practice",
            priority=5,
            condition=_is_practicing_approaching,
            action=DecisionType.QUIZ_RETRY,
            description="Approaching mastery — additional quiz practice recommended.",
        ),
        # Priority 6: Mastered → advance
        AdaptiveRule(
            name="mastered_advance",
            priority=6,
            condition=_is_mastered,
            action=DecisionType.ADVANCE,
            description="Topic mastered — advance to next topic.",
        ),
        # Priority 7: Review required → review
        AdaptiveRule(
            name="review_required_review",
            priority=7,
            condition=_is_review_required,
            action=DecisionType.REVIEW,
            description="Review required — schedule a review session.",
        ),
        # Priority 8: Regressed → remediate
        AdaptiveRule(
            name="regressed_remediate",
            priority=8,
            condition=_is_regressed,
            action=DecisionType.REMEDIATE,
            description="Topic regressed — generate remediation plan.",
        ),
        # Priority 99: Fallback — hold
        AdaptiveRule(
            name="default_hold",
            priority=99,
            condition=lambda ctx: True,
            action=DecisionType.HOLD,
            description="Fallback — hold position, no action available.",
        ),
    ]


# ── Rule Engine ────────────────────────────────────────────────────────────


class AdaptiveRuleEngine:
    """Configurable adaptive rule engine.

    Evaluates rules in priority order against a RuleContext. The first
    matching rule produces the decision.

    Rules are configurable: call ``set_rules()`` to override defaults.

    Usage::

        engine = AdaptiveRuleEngine()
        decision, explanation = engine.evaluate(context)
    """

    def __init__(self, rules: list[AdaptiveRule] | None = None) -> None:
        """Initialize the rule engine.

        Args:
            rules: Optional custom rule set. If None, uses defaults.
        """
        self._rules: list[AdaptiveRule] = sorted(
            rules if rules is not None else _default_rules(),
            key=lambda r: r.priority,
        )

    @property
    def rules(self) -> list[AdaptiveRule]:
        """Return the current rule set (read-only copy)."""
        return list(self._rules)

    def get_rule_names(self) -> list[str]:
        """Return list of active rule names."""
        return [r.name for r in self._rules]

    def set_rules(self, rules: list[AdaptiveRule]) -> None:
        """Replace the entire rule set.

        Rules are re-sorted by priority after replacement.

        Args:
            rules: The new rule set.
        """
        self._rules = sorted(rules, key=lambda r: r.priority)

    def add_rule(self, rule: AdaptiveRule) -> None:
        """Add a single rule and re-sort.

        Args:
            rule: The rule to add.
        """
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name.

        Args:
            name: The name of the rule to remove.

        Returns:
            True if a rule was removed, False otherwise.
        """
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    def evaluate(self, context: RuleContext) -> tuple[DecisionType, Explanation]:
        """Evaluate the rule set against a context.

        Rules are evaluated in priority order. The first matching rule
        produces the decision.

        Args:
            context: The RuleContext to evaluate against.

        Returns:
            A tuple of (DecisionType, Explanation).
        """
        triggered_rules: list[str] = []

        for rule in self._rules:
            try:
                matched = rule.condition(context)
            except Exception:
                matched = False

            if matched:
                triggered_rules.append(rule.name)
                explanation = Explanation(
                    decision=rule.action.value,
                    reason=rule.description,
                    evidence=[
                        f"Rule '{rule.name}' (priority {rule.priority}) matched.",
                        f"Mastery state: {context.evaluation.mastery_state.value}",
                        f"Score: {context.evaluation.score:.2f}",
                        f"Confidence: {context.evaluation.confidence:.2f}",
                        f"Repeated failures: {context.evaluation.repeated_failures}",
                    ],
                    metrics_used={
                        "score": context.evaluation.score,
                        "confidence": context.evaluation.confidence,
                        "attempt_count": float(context.evaluation.attempt_count),
                        "repeated_failures": float(context.evaluation.repeated_failures),
                    },
                    confidence=context.evaluation.confidence,
                    rules_triggered=triggered_rules,
                    prerequisites_examined=[
                        f"{meval.topic_name} ({meval.mastery_state.value})"
                        for meval in context.prerequisite_mastery.values()
                    ],
                )
                return rule.action, explanation

        # Fallback (shouldn't reach here due to default_hold rule)
        return DecisionType.HOLD, Explanation(
            decision="hold",
            reason="No rules matched — defaulting to hold.",
            confidence=0.0,
        )
