"""AAA v2 Analytics Package — learning metrics, progress tracking, dashboards.

This package is independent from business logic. It provides:

- **models.py**: Domain types for analytics data (no SQLAlchemy models).
- **schemas.py**: Pydantic schemas for API request/response serialization.
- **service.py**: Orchestration layer that coordinates calculations and queries.
- **calculations.py**: Pure deterministic calculation functions.
- **repository.py**: Analytics-specific persistence queries (aggregations).

Architecture reference: Section 19 (Analytics & Dashboard Read Models), Sprint 7.
"""

from __future__ import annotations

__all__: list[str] = []
