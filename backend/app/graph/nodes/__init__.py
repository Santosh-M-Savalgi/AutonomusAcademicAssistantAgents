"""Graph node modules for AAA v2.

Nodes:
    parse: SyllabusParser agent → structured topic list
    retrieve: RetrievalService + ContextBuilder → retrieval context
    teach: TutorService → lesson cards
    quiz: QuizService → multiple-choice quiz
    evaluate: EvaluationService + AdaptiveRouter → score + routing decision
"""

from app.graph.nodes.evaluate import evaluate_quiz_node
from app.graph.nodes.parse import parse_syllabus_node
from app.graph.nodes.quiz import generate_quiz_node
from app.graph.nodes.retrieve import retrieve_context_node
from app.graph.nodes.retrieve_web import retrieve_web_node
from app.graph.nodes.teach import generate_lesson_node

__all__ = [
    "parse_syllabus_node",
    "retrieve_context_node",
    "retrieve_web_node",
    "generate_lesson_node",
    "generate_quiz_node",
    "evaluate_quiz_node",
]
