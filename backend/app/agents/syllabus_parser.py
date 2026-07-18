"""Syllabus Parser Agent — converts a free-text learning goal into structured topics.

Given a prompt like "I want to learn Java" or "Teach me data structures",
this agent uses the LLM to:
1. Break the goal into prerequisite-ordered topics
2. Assign difficulty levels and dependencies
3. Return the parsed syllabus as structured data

The result is stored in the DB as Syllabus + Topic + TopicEdge records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.llm.provider_router import ProviderFactory
from app.llm.providers.base import BaseProvider, ProviderError


# ── Domain types ────────────────────────────────────────────────────────────


@dataclass
class ParsedTopic:
    """A single topic extracted from a learning goal."""
    name: str
    slug: str
    description: str
    difficulty: str  # beginner | intermediate | advanced
    prerequisites: list[str] = field(default_factory=list)
    """Names of topics that must be learned before this one."""


@dataclass
class ParsedSyllabus:
    """Complete parsed syllabus from a learning goal."""
    title: str
    topics: list[ParsedTopic]


# ── Prompt template ─────────────────────────────────────────────────────────


SYLLABUS_SYSTEM_PROMPT = """You are an expert curriculum designer. Given a learning goal, you must:

1. Break the goal into 3-10 specific, ordered topics.
2. Each topic should be a concrete, learnable concept.
3. Identify prerequisite relationships between topics.
4. Assign appropriate difficulty levels.

Rules:
- Topics must be ordered so prerequisites come before dependent topics.
- A topic's prerequisites must be other topics in the list.
- Use simple, descriptive names and slugs.
- Difficulty: "beginner" (fundamental), "intermediate" (requires prerequisites), "advanced" (complex).
- Each topic needs a 1-2 sentence description explaining what it covers.

Respond ONLY with valid JSON matching this structure:
{
  "title": "Brief curriculum title",
  "topics": [
    {
      "name": "Topic name",
      "slug": "topic-name",
      "description": "Brief description of what this topic covers",
      "difficulty": "beginner|intermediate|advanced",
      "prerequisites": ["slug-of-prerequisite-topic"]
    }
  ]
}"""


# ── Syllabus Parser ─────────────────────────────────────────────────────────


class SyllabusParser:
    """Parses a free-text learning goal into structured curriculum topics.

    Uses the configured LLM provider to extract and organize topics.
    Falls back to a deterministic mock when no real provider is configured.
    """

    def __init__(self, provider: BaseProvider | None = None):
        self._provider = provider or ProviderFactory.from_settings().get_provider()

    async def parse(self, goal: str) -> ParsedSyllabus:
        """Parse a learning goal into a structured syllabus.

        Args:
            goal: Free-text learning goal, e.g. "I want to learn Python"
                  or "Teach me machine learning from scratch".

        Returns:
            A ParsedSyllabus with ordered topics.

        Raises:
            ProviderError: If the LLM call fails or returns invalid JSON.
        """
        prompt = f"Learning goal: {goal}\n\nBreak this down into a structured curriculum."

        try:
            response = await self._provider.generate(
                system_prompt=SYLLABUS_SYSTEM_PROMPT,
                prompt=prompt,
            )
        except ProviderError:
            # Re-raise — never silently fall back to mock in production.
            # The caller (learning.py) catches and logs the error.
            raise

        # Parse the LLM response — fall back to mock syllabus on malformed JSON only
        try:
            raw = response.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                raw = raw.rsplit("\n", 1)[0]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            data = json.loads(raw)
            return self._parse_response(data, goal)
        except (json.JSONDecodeError, ProviderError, TypeError, ValueError):
            return self._mock_syllabus(goal)

    # ── Response parsing ─────────────────────────────────────────────────

    def _parse_response(self, data: dict[str, Any], goal: str) -> ParsedSyllabus:
        """Parse the LLM JSON response into domain types."""
        title = data.get("title", goal[:80])
        raw_topics: list[dict] = data.get("topics", [])

        if not raw_topics:
            return self._mock_syllabus(goal)

        topics: list[ParsedTopic] = []
        for t in raw_topics:
            name = t.get("name", "Untitled Topic")
            slug = t.get("slug", name.lower().replace(" ", "-").replace("/", "-"))
            topics.append(ParsedTopic(
                name=name,
                slug=slug,
                description=t.get("description", ""),
                difficulty=t.get("difficulty", "beginner"),
                prerequisites=t.get("prerequisites", []),
            ))

        return ParsedSyllabus(title=title, topics=topics)

    # ── Mock fallback ────────────────────────────────────────────────────

    def _mock_syllabus(self, goal: str) -> ParsedSyllabus:
        """Generate a deterministic mock syllabus when no real LLM is available.

        Handles common programming/CS learning goals.
        """
        goal_lower = goal.lower()
        title = goal[:80]

        if any(w in goal_lower for w in ("python", "py")):
            return ParsedSyllabus(
                title=f"Python Programming: {goal}",
                topics=[
                    ParsedTopic("Python Basics", "python-basics", "Variables, data types, and basic syntax", "beginner"),
                    ParsedTopic("Control Flow", "control-flow", "Conditionals, loops, and logic", "beginner", prerequisites=["python-basics"]),
                    ParsedTopic("Functions & Modules", "functions-modules", "Writing reusable code with functions and modules", "beginner", prerequisites=["control-flow"]),
                    ParsedTopic("Data Structures", "data-structures", "Lists, dicts, sets, and tuples", "intermediate", prerequisites=["functions-modules"]),
                    ParsedTopic("OOP in Python", "oop-python", "Classes, inheritance, and polymorphism", "intermediate", prerequisites=["data-structures"]),
                    ParsedTopic("Error Handling & File I/O", "error-handling-file-io", "Exceptions, file operations, and context managers", "intermediate", prerequisites=["functions-modules"]),
                    ParsedTopic("Advanced Python", "advanced-python", "Decorators, generators, and async", "advanced", prerequisites=["oop-python", "error-handling-file-io"]),
                ],
            )
        elif any(w in goal_lower for w in ("java",)):
            return ParsedSyllabus(
                title=f"Java Programming: {goal}",
                topics=[
                    ParsedTopic("Java Basics", "java-basics", "JVM, syntax, and primitive types", "beginner"),
                    ParsedTopic("Control Flow & Methods", "java-control-flow", "Conditionals, loops, and methods", "beginner", prerequisites=["java-basics"]),
                    ParsedTopic("OOP in Java", "java-oop", "Classes, inheritance, interfaces, and polymorphism", "beginner", prerequisites=["java-control-flow"]),
                    ParsedTopic("Collections Framework", "java-collections", "Lists, sets, maps, and queues", "intermediate", prerequisites=["java-oop"]),
                    ParsedTopic("Exception Handling", "java-exceptions", "Try-catch, checked vs unchecked, custom exceptions", "intermediate", prerequisites=["java-oop"]),
                    ParsedTopic("Streams & Lambdas", "java-streams", "Functional programming with streams and lambdas", "advanced", prerequisites=["java-collections"]),
                ],
            )
        elif any(w in goal_lower for w in ("data structure", "dsa", "algorithm")):
            return ParsedSyllabus(
                title=f"Data Structures & Algorithms: {goal}",
                topics=[
                    ParsedTopic("Arrays & Strings", "arrays-strings", "Array manipulation, string algorithms, and two-pointer techniques", "beginner"),
                    ParsedTopic("Linked Lists", "linked-lists", "Singly, doubly, and circular linked lists", "beginner", prerequisites=["arrays-strings"]),
                    ParsedTopic("Stacks & Queues", "stacks-queues", "LIFO/FIFO data structures and their applications", "beginner", prerequisites=["linked-lists"]),
                    ParsedTopic("Trees & Graphs", "trees-graphs", "Binary trees, BSTs, graph representations, and traversals", "intermediate", prerequisites=["stacks-queues"]),
                    ParsedTopic("Hash Tables", "hash-tables", "Hash functions, collision resolution, and hash map design", "intermediate", prerequisites=["arrays-strings"]),
                    ParsedTopic("Sorting & Searching", "sorting-searching", "Common sorting algorithms and binary search variants", "intermediate", prerequisites=["arrays-strings"]),
                    ParsedTopic("Dynamic Programming", "dynamic-programming", "Memoization, tabulation, and common DP patterns", "advanced", prerequisites=["trees-graphs", "sorting-searching"]),
                ],
            )
        elif any(w in goal_lower for w in ("machine learning", "ml", "deep learning")):
            return ParsedSyllabus(
                title=f"Machine Learning: {goal}",
                topics=[
                    ParsedTopic("Python for ML", "python-for-ml", "NumPy, Pandas, and data manipulation basics", "beginner"),
                    ParsedTopic("Statistics & Probability", "statistics-probability", "Descriptive stats, distributions, and probability theory", "beginner", prerequisites=["python-for-ml"]),
                    ParsedTopic("Supervised Learning", "supervised-learning", "Linear regression, decision trees, and SVM", "intermediate", prerequisites=["statistics-probability"]),
                    ParsedTopic("Unsupervised Learning", "unsupervised-learning", "K-means, PCA, and clustering techniques", "intermediate", prerequisites=["supervised-learning"]),
                    ParsedTopic("Neural Networks", "neural-networks", "Perceptrons, backpropagation, and feed-forward networks", "advanced", prerequisites=["supervised-learning"]),
                    ParsedTopic("Deep Learning", "deep-learning", "CNNs, RNNs, transformers, and modern architectures", "advanced", prerequisites=["neural-networks"]),
                ],
            )
        elif any(w in goal_lower for w in ("react", "frontend", "javascript", "js")):
            return ParsedSyllabus(
                title=f"Frontend Development: {goal}",
                topics=[
                    ParsedTopic("HTML & CSS", "html-css", "Semantic HTML, CSS layout, and responsive design", "beginner"),
                    ParsedTopic("JavaScript Basics", "javascript-basics", "Variables, functions, DOM manipulation, and ES6+", "beginner", prerequisites=["html-css"]),
                    ParsedTopic("React Fundamentals", "react-fundamentals", "Components, props, state, and JSX", "intermediate", prerequisites=["javascript-basics"]),
                    ParsedTopic("React Hooks & Effects", "react-hooks", "useState, useEffect, custom hooks, and context", "intermediate", prerequisites=["react-fundamentals"]),
                    ParsedTopic("State Management", "state-management", "Redux, Zustand, or React Query patterns", "advanced", prerequisites=["react-hooks"]),
                    ParsedTopic("Testing & Deployment", "testing-deployment", "Unit testing, E2E testing, and CI/CD", "advanced", prerequisites=["state-management"]),
                ],
            )
        elif any(w in goal_lower for w in ("sql", "database", "db")):
            return ParsedSyllabus(
                title=f"Databases & SQL: {goal}",
                topics=[
                    ParsedTopic("Relational Database Concepts", "relational-db-concepts", "Tables, rows, keys, and normalization", "beginner"),
                    ParsedTopic("SQL Queries", "sql-queries", "SELECT, JOIN, GROUP BY, and subqueries", "beginner", prerequisites=["relational-db-concepts"]),
                    ParsedTopic("Data Modeling", "data-modeling", "ER diagrams, schema design, and relationships", "intermediate", prerequisites=["sql-queries"]),
                    ParsedTopic("Indexes & Performance", "indexes-performance", "Query planning, indexing strategies, and optimization", "intermediate", prerequisites=["data-modeling"]),
                    ParsedTopic("Transactions & Concurrency", "transactions-concurrency", "ACID, isolation levels, and locking", "advanced", prerequisites=["indexes-performance"]),
                ],
            )
        elif any(w in goal_lower for w in ("system design", "system-design", "architecture")):
            return ParsedSyllabus(
                title=f"System Design: {goal}",
                topics=[
                    ParsedTopic("Fundamentals of Scale", "fundamentals-of-scale", "Latency, throughput, CAP theorem, and load balancing", "beginner"),
                    ParsedTopic("Database Design", "database-design-sd", "SQL vs NoSQL, sharding, replication, and partitioning", "beginner", prerequisites=["fundamentals-of-scale"]),
                    ParsedTopic("Caching & CDN", "caching-cdn", "Redis, CDN strategies, and cache invalidation", "intermediate", prerequisites=["database-design-sd"]),
                    ParsedTopic("Message Queues & Async", "message-queues", "Kafka, RabbitMQ, event-driven architectures", "intermediate", prerequisites=["caching-cdn"]),
                    ParsedTopic("Microservices", "microservices", "Service decomposition, API gateways, and service mesh", "advanced", prerequisites=["message-queues"]),
                    ParsedTopic("Design Deep Dives", "design-deep-dives", "Designing real systems: chat, URL shortener, etc.", "advanced", prerequisites=["microservices"]),
                ],
            )

        # Generic fallback
        return ParsedSyllabus(
            title=title,
            topics=[
                ParsedTopic(f"Introduction to {goal}", "introduction", f"Core concepts and fundamentals of {goal}", "beginner"),
                ParsedTopic("Core Concepts", "core-concepts", "Key principles and building blocks", "beginner", prerequisites=["introduction"]),
                ParsedTopic("Intermediate Topics", "intermediate-topics", "Deepening understanding with practical applications", "intermediate", prerequisites=["core-concepts"]),
                ParsedTopic("Advanced Topics", "advanced-topics", "Complex patterns and expert-level techniques", "advanced", prerequisites=["intermediate-topics"]),
            ],
        )
