"""Pure deterministic diagnostic selection and prerequisite inference."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from packages.curriculum.graph import topological_order, unique_descendant_counts
from packages.domain.adaptation import (
    DiagnosticCandidate,
    DiagnosticConceptState,
    DiagnosticInferenceProvenance,
    DiagnosticState,
)
from packages.domain.graph import EdgeStatus, EdgeType, GraphDefinition, GraphEdge
from packages.domain.mastery import ConceptRoleSnapshot, EvidenceInput


def select_diagnostic_candidates(
    graph: GraphDefinition,
    concept_states: Mapping[UUID, DiagnosticConceptState],
    question_version_ids: Mapping[UUID, Sequence[UUID]],
    state: DiagnosticState,
) -> tuple[DiagnosticCandidate, ...]:
    """Select up to the remaining diagnostic budget deterministically."""

    if state.remaining_item_budget == 0:
        return ()
    concept_ids = {concept.id for concept in graph.concepts}
    descendants = unique_descendant_counts(graph, confirmed_only=True)
    ordered_nodes = topological_order(graph, confirmed_only=True)
    topological_rank = {
        node_id: index for index, node_id in enumerate(node_id for node_id in ordered_nodes)
    }
    candidates: list[tuple[float, int, UUID, int, tuple[UUID, ...], float]] = []
    excluded_concepts = set(state.selected_concept_ids) | set(
        state.diagnostic_assessed_concept_ids
    )
    attempted_questions = set(state.attempted_question_version_ids)
    for concept_id in sorted(concept_ids, key=lambda value: value.bytes):
        concept_state = concept_states.get(concept_id)
        if concept_state is None or concept_state.diagnostic_assessed:
            continue
        if concept_id in excluded_concepts:
            continue
        valid_questions = tuple(sorted(
            (question_id for question_id in question_version_ids.get(concept_id, ())
             if question_id not in attempted_questions),
            key=lambda value: value.bytes,
        ))
        if not valid_questions:
            continue
        descendant_count = descendants.get(concept_id, 0)
        score = (descendant_count + 1) * (1.0 - concept_state.confidence)
        candidates.append((
            -score,
            topological_rank.get(concept_id, len(topological_rank)),
            concept_id,
            descendant_count,
            valid_questions,
            concept_state.confidence,
        ))

    candidates.sort(key=lambda item: (item[0], item[1], item[2].bytes))
    remaining = state.remaining_item_budget
    selected: list[DiagnosticCandidate] = []
    for _, rank, concept_id, descendant_count, questions, confidence in candidates:
        if remaining <= 0:
            break
        selected_questions = tuple(questions[: min(2, remaining)])
        if not selected_questions:
            continue
        selected.append(DiagnosticCandidate(
            stable_concept_id=concept_id,
            score=(descendant_count + 1) * (1.0 - confidence),
            descendant_count=descendant_count,
            confidence=confidence,
            topological_rank=rank,
            question_version_ids=selected_questions,
        ))
        remaining -= len(selected_questions)
    return tuple(selected)


def confirmed_transitive_prerequisites(
    graph: GraphDefinition,
    target_concept_ids: Sequence[UUID],
) -> dict[UUID, tuple[UUID, ...]]:
    """Return each unique confirmed ancestor and the edges that prove it."""

    return confirmed_prerequisite_provenance(graph.edges, target_concept_ids)


def confirmed_prerequisite_provenance(
    edges: Sequence[GraphEdge],
    target_concept_ids: Sequence[UUID],
) -> dict[UUID, tuple[UUID, ...]]:
    """Share confirmed closure provenance with authoritative persisted snapshots."""

    reverse: dict[UUID, list[tuple[UUID, UUID]]] = defaultdict(list)
    for edge in edges:
        if edge.edge_type != EdgeType.PREREQUISITE_OF or edge.status != EdgeStatus.CONFIRMED:
            continue
        reverse[edge.target_node_id].append((edge.source_node_id, edge.edge_id))
    for values in reverse.values():
        values.sort(key=lambda item: (item[0].bytes, item[1].bytes))

    result: dict[UUID, set[UUID]] = defaultdict(set)
    for target in sorted(set(target_concept_ids), key=lambda value: value.bytes):
        pending = list(reverse.get(target, ()))
        visited: set[UUID] = set()
        while pending:
            prerequisite, edge_id = pending.pop(0)
            if prerequisite in visited:
                result[prerequisite].add(edge_id)
                continue
            visited.add(prerequisite)
            result[prerequisite].add(edge_id)
            pending.extend(reverse.get(prerequisite, ()))
    return {
        concept_id: tuple(sorted(edge_ids, key=lambda value: value.bytes))
        for concept_id, edge_ids in sorted(result.items(), key=lambda item: item[0].bytes)
    }


def diagnostic_inference_provenance(
    *,
    diagnostic_run_id: UUID,
    learner_id: UUID,
    source_attempt_id: UUID,
    source_question_version_id: UUID,
    source_evidence_id: UUID,
    source_graph_version_id: UUID,
    prerequisite_edge_ids: Mapping[UUID, Sequence[UUID]],
) -> tuple[DiagnosticInferenceProvenance, ...]:
    """Build one deduplicated provenance value per inferred prerequisite."""

    return tuple(
        DiagnosticInferenceProvenance(
            learner_id=learner_id,
            diagnostic_run_id=diagnostic_run_id,
            source_attempt_id=source_attempt_id,
            source_question_version_id=source_question_version_id,
            source_evidence_id=source_evidence_id,
            source_graph_version_id=source_graph_version_id,
            confirmed_edge_ids=tuple(sorted(set(edge_ids), key=lambda value: value.bytes)),
            target_prerequisite_concept_id=concept_id,
        )
        for concept_id, edge_ids in sorted(
            prerequisite_edge_ids.items(), key=lambda item: item[0].bytes,
        )
    )


def inferred_evidence_for_prerequisite(
    source_evidence: EvidenceInput,
    provenance: DiagnosticInferenceProvenance,
) -> EvidenceInput:
    """Create one deterministic positive inferred contribution request."""

    key = (
        "diagnostic-inferred:v1:"
        f"{provenance.source_attempt_id.hex}:"
        f"{provenance.target_prerequisite_concept_id.hex}"
    )
    source = EvidenceInput.model_validate(source_evidence.model_dump(
        include=set(EvidenceInput.model_fields),
    ))
    return source.model_copy(update={
        "evidence_id": uuid5(NAMESPACE_URL, key),
        "correct": 1.0,
        "kind": "INFERRED",
        "is_review": False,
        "concept_roles": (
            ConceptRoleSnapshot(
                stable_concept_id=provenance.target_prerequisite_concept_id,
                role="PREREQUISITE",
            ),
        ),
        "graph_version_id": provenance.source_graph_version_id,
        "idempotency_key": key,
        "diagnostic_provenance": provenance,
    })
