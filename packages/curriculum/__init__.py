"""Pure curriculum algorithms and versioned graph templates."""

from packages.curriculum.diagnostics import (
    confirmed_transitive_prerequisites,
    diagnostic_inference_provenance,
    inferred_evidence_for_prerequisite,
    select_diagnostic_candidates,
)
from packages.curriculum.graph import (
    GraphCycleError,
    GraphSelfLoopError,
    GraphValidationError,
    confirmed_prerequisite_edges,
    descendants,
    graph_from_confirmed_revision,
    infer_leaf_topic_concept,
    proposed_prerequisite_edges,
    rejected_prerequisite_edges,
    topological_depth,
    topological_order,
    unique_descendant_counts,
    validate_dag,
)
from packages.curriculum.templates import (
    algebra_foundations_template,
    programming_foundations_template,
    seed_template,
)

__all__ = [
    "GraphCycleError",
    "GraphSelfLoopError",
    "GraphValidationError",
    "algebra_foundations_template",
    "confirmed_prerequisite_edges",
    "confirmed_transitive_prerequisites",
    "descendants",
    "diagnostic_inference_provenance",
    "inferred_evidence_for_prerequisite",
    "graph_from_confirmed_revision",
    "infer_leaf_topic_concept",
    "programming_foundations_template",
    "proposed_prerequisite_edges",
    "rejected_prerequisite_edges",
    "seed_template",
    "select_diagnostic_candidates",
    "topological_depth",
    "topological_order",
    "unique_descendant_counts",
    "validate_dag",
]
