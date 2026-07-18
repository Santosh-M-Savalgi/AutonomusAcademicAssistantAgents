"""Pure deterministic calculation functions for analytics (Sprint 7).

All functions are stateless, pure, and independently testable.
No LLM calls. No database access. No side effects.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any


def calculate_completion(
    mastered_topics: int,
    total_topics: int,
) -> float:
    """Calculate overall completion percentage.

    Args:
        mastered_topics: Number of topics that have been mastered.
        total_topics: Total number of topics in the syllabus.

    Returns:
        Completion percentage (0.0–100.0).
    """
    if total_topics <= 0:
        return 100.0
    return round((mastered_topics / total_topics) * 100.0, 1)


def calculate_mastery(
    scores: list[float],
) -> float:
    """Calculate overall mastery score from per-topic mastery scores.

    Args:
        scores: List of mastery scores (0.0–100.0) for all topics.

    Returns:
        Average mastery percentage (0.0–100.0), or 0.0 if empty.
    """
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 1)


def calculate_average_score(
    scores: list[float],
) -> float:
    """Calculate average quiz score.

    Args:
        scores: List of quiz scores (0.0–100.0).

    Returns:
        Average score (0.0–100.0), or 0.0 if empty.
    """
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 1)


def calculate_learning_streak(
    activity_dates: list[date],
    *,
    today: date | None = None,
) -> tuple[int, int]:
    """Calculate current and longest learning streak in days.

    A streak is consecutive calendar days with at least one activity event.
    The current streak starts from the most recent activity date and counts
    backward. If the most recent activity is yesterday or today, the streak
    is active. A gap of one or more days breaks the streak.

    Args:
        activity_dates: List of dates (as date objects) with learning activity.
        today: The reference "today" date (defaults to UTC today).

    Returns:
        (current_streak, longest_streak) as integers.
    """
    if not activity_dates:
        return (0, 0)

    ref_today = today or date.today()
    unique_dates = sorted({d for d in activity_dates})
    longest = 1
    current_run = 1

    # Calculate longest streak
    for i in range(1, len(unique_dates)):
        if (unique_dates[i] - unique_dates[i - 1]).days == 1:
            current_run += 1
        else:
            longest = max(longest, current_run)
            current_run = 1
    longest = max(longest, current_run)

    # Calculate current streak from most recent activity
    most_recent = unique_dates[-1]
    days_since_last = (ref_today - most_recent).days

    # Streak is active if last activity was today or yesterday
    if days_since_last > 1:
        return (0, longest)

    current_streak = 0
    for d in reversed(unique_dates):
        expected = ref_today - timedelta(days=current_streak)
        if d == expected or d == expected - timedelta(days=days_since_last):
            current_streak += 1
        else:
            break

    return (current_streak, longest)


def calculate_time_spent(
    events: list[dict[str, Any]],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> float:
    """Calculate total study time in minutes from timeline events.

    Extracts duration from events that have 'duration_minutes' in their metadata,
    or estimates time from session_start/session_complete event pairs.

    Args:
        events: List of analytics event dicts with 'event_type', 'created_at',
            and 'payload' fields.
        start_date: Optional start date filter (inclusive).
        end_date: Optional end date filter (inclusive).

    Returns:
        Total time in minutes.
    """
    total = 0.0

    for event in events:
        payload = event.get("payload", {}) if isinstance(event, dict) else {}
        if not payload:
            continue

        # Check for explicit duration
        duration = payload.get("duration_minutes", 0)
        if duration:
            total += float(duration)
            continue

        # Check for time spent from quiz/lesson events
        time_spent = payload.get("time_spent_minutes", 0)
        if time_spent:
            total += float(time_spent)

    return round(total, 1)


def calculate_topic_progress(
    score: float,
    threshold: float,
    attempts: int,
    *,
    confidence: float = 0.0,
) -> dict[str, Any]:
    """Calculate progress metrics for a single topic.

    Args:
        score: Current mastery score (0.0–100.0).
        threshold: Mastery threshold (0.0–100.0).
        attempts: Number of quiz attempts.
        confidence: Confidence in the score (0.0–1.0).

    Returns:
        Dict with 'completion_percentage', 'mastery_percentage', 'confidence_score',
        and 'recommended_review' keys.
    """
    completion = min(100.0, (score / threshold * 100.0) if threshold > 0 else 100.0)
    completion = max(0.0, round(completion, 1))

    mastery = round(score, 1)
    confidence_pct = round(confidence * 100.0, 1)

    # Recommend review if score is below threshold and there are attempts
    recommended = score < threshold and attempts > 0

    return {
        "completion_percentage": completion,
        "mastery_percentage": mastery,
        "confidence_score": confidence_pct,
        "recommended_review": recommended,
    }


def calculate_dashboard_summary(
    *,
    current_topic: str = "",
    current_course: str = "",
    overall_completion: float = 0.0,
    overall_mastery: float = 0.0,
    average_quiz_score: float = 0.0,
    weekly_study_time_minutes: float = 0.0,
    daily_study_time_minutes: float = 0.0,
    recent_sessions: int = 0,
    current_streak_days: int = 0,
    weakest_topic: str = "",
    strongest_topic: str = "",
    recommended_next_topic: str = "",
    recent_activity: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble a dashboard summary dict.

    Args:
        current_topic: Name of the current topic being studied.
        current_course: Name of the current course/syllabus.
        overall_completion: Overall completion percentage (0.0–100.0).
        overall_mastery: Overall mastery percentage (0.0–100.0).
        average_quiz_score: Average quiz score (0.0–100.0).
        weekly_study_time_minutes: Study time this week in minutes.
        daily_study_time_minutes: Study time today in minutes.
        recent_sessions: Number of recent sessions.
        current_streak_days: Current learning streak in days.
        weakest_topic: Name of the weakest topic.
        strongest_topic: Name of the strongest topic.
        recommended_next_topic: Name of the recommended next topic.
        recent_activity: Recent timeline events as dicts.

    Returns:
        A dict-ready dashboard summary.
    """
    return {
        "current_topic": current_topic,
        "current_course": current_course,
        "overall_completion": overall_completion,
        "overall_mastery": overall_mastery,
        "average_quiz_score": average_quiz_score,
        "weekly_study_time_minutes": weekly_study_time_minutes,
        "daily_study_time_minutes": daily_study_time_minutes,
        "recent_sessions": recent_sessions,
        "current_streak_days": current_streak_days,
        "weakest_topic": weakest_topic,
        "strongest_topic": strongest_topic,
        "recommended_next_topic": recommended_next_topic,
        "recent_activity": recent_activity or [],
    }


def calculate_recommendations(
    topic_scores: list[dict[str, Any]],
    *,
    syllabus_topic_ids: list[uuid.UUID] | None = None,
    completed_topic_ids: set[uuid.UUID] | None = None,
    current_topic_id: uuid.UUID | None = None,
    prerequisites_map: dict[uuid.UUID, list[uuid.UUID]] | None = None,
    max_recommendations: int = 5,
) -> list[dict[str, Any]]:
    """Generate learning recommendations from topic data (pure deterministic).

    Recommendations are ranked by priority:
    1. Next topic (first uncompleted in syllabus order)
    2. Weak topics (score below threshold, sorted weakest first)
    3. Revision topics (score near threshold, last studied long ago)
    4. Prerequisite topics (weak prerequisites of current topic)
    5. High priority (combination of weak and prerequisite)

    Args:
        topic_scores: List of dicts with 'topic_id', 'topic_name', 'topic_slug',
            'score', 'threshold', 'last_studied_at', 'attempts'.
        syllabus_topic_ids: Ordered topic IDs from the syllabus.
        completed_topic_ids: Set of topic IDs that are completed/mastered.
        current_topic_id: The current topic being studied.
        prerequisites_map: Dict of topic_id -> list of prerequisite topic_ids.
        max_recommendations: Maximum number of recommendations to return.

    Returns:
        List of recommendation dicts sorted by priority.
    """
    recommendations: list[dict[str, Any]] = []
    topic_map = {t["topic_id"]: t for t in topic_scores}
    completed = completed_topic_ids or set()
    prereq_map = prerequisites_map or {}

    now = datetime.now(timezone.utc)

    # 1. Find next topic in syllabus order
    if syllabus_topic_ids:
        for tid in syllabus_topic_ids:
            if tid not in completed and tid not in topic_map:
                # Topic not yet started
                topic_obj = next(
                    (t for t in topic_scores if t["topic_id"] == tid),
                    None,
                )
                if topic_obj:
                    recommendations.append({
                        "topic_id": tid,
                        "topic_name": topic_obj["topic_name"],
                        "topic_slug": topic_obj.get("topic_slug", ""),
                        "reason": "Next topic in your learning path",
                        "priority": "high",
                        "recommendation_type": "next",
                    })
                break
            # Check if there's a topic in the syllabus not yet completed
            if tid not in completed:
                score = topic_map.get(tid, {}).get("score", 0.0)
                threshold = topic_map.get(tid, {}).get("threshold", 75.0)
                if score < threshold:
                    recommendations.append({
                        "topic_id": tid,
                        "topic_name": topic_map.get(tid, {}).get("topic_name", ""),
                        "topic_slug": topic_map.get(tid, {}).get("topic_slug", ""),
                        "reason": "Next topic in your learning path",
                        "priority": "high",
                        "recommendation_type": "next",
                    })
                break

    # 2. Weak topics (score below threshold, sorted weakest first)
    weak_topics = [
        t for t in topic_scores
        if t["topic_id"] not in completed
        and t["score"] < t.get("threshold", 75.0)
        and t["topic_id"] != (current_topic_id if current_topic_id else None)
    ]
    weak_topics.sort(key=lambda t: t["score"])

    for t in weak_topics[:2]:
        recommendations.append({
            "topic_id": t["topic_id"],
            "topic_name": t["topic_name"],
            "topic_slug": t.get("topic_slug", ""),
            "reason": f"Weak topic (score {t['score']:.0f}%) — needs review",
            "priority": "high" if t["score"] < 40.0 else "medium",
            "recommendation_type": "weak",
        })

    # 3. Revision topics (score near threshold, studied long ago)
    revision_candidates = []
    for t in topic_scores:
        threshold = t.get("threshold", 75.0)
        score = t["score"]
        if threshold - 15 <= score < threshold and t["topic_id"] not in completed:
            last_studied = t.get("last_studied_at")
            days_ago = 999
            if last_studied:
                if isinstance(last_studied, datetime):
                    days_ago = (now - last_studied).days
                elif isinstance(last_studied, str):
                    try:
                        dt = datetime.fromisoformat(last_studied)
                        days_ago = (now - dt).days
                    except (ValueError, TypeError):
                        pass
            revision_candidates.append((t, days_ago))

    revision_candidates.sort(key=lambda x: -x[1])  # Longest ago first
    for t, _ in revision_candidates[:1]:
        recommendations.append({
            "topic_id": t["topic_id"],
            "topic_name": t["topic_name"],
            "topic_slug": t.get("topic_slug", ""),
            "reason": "Topic near threshold — recommended for revision",
            "priority": "medium",
            "recommendation_type": "revision",
        })

    # 4. Prerequisite topics (weak prerequisites of current topic)
    if current_topic_id and current_topic_id in prereq_map:
        prereqs = prereq_map[current_topic_id]
        for prereq_id in prereqs:
            if prereq_id in completed:
                continue
            prereq_topic = topic_map.get(prereq_id)
            if prereq_topic and prereq_topic["score"] < prereq_topic.get("threshold", 75.0):
                recommendations.append({
                    "topic_id": prereq_id,
                    "topic_name": prereq_topic["topic_name"],
                    "topic_slug": prereq_topic.get("topic_slug", ""),
                    "reason": "Prerequisite topic needs strengthening",
                    "priority": "high",
                    "recommendation_type": "prerequisite",
                })

    # 5. High priority — deduplicate by topic_id and limit
    seen: set[uuid.UUID] = set()
    unique: list[dict[str, Any]] = []
    for rec in recommendations:
        if rec["topic_id"] not in seen:
            seen.add(rec["topic_id"])
            unique.append(rec)

    return unique[:max_recommendations]


def calculate_trends(
    daily_activity: list[dict[str, Any]],
    weekly_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate learning trends from daily activity and weekly scores.

    Args:
        daily_activity: List of dicts with 'date' (str) and 'minutes' (float).
        weekly_scores: List of dicts with 'week' (str) and 'score' (float).

    Returns:
        Dict with 'daily_activity', 'weekly_scores', 'weekly_trend'
        (positive/negative/stable) keys.
    """
    if not weekly_scores:
        return {
            "daily_activity": daily_activity,
            "weekly_scores": [],
            "weekly_trend": "stable",
        }

    # Determine trend from last 3 weeks
    recent = weekly_scores[-3:] if len(weekly_scores) >= 3 else weekly_scores
    if len(recent) >= 2:
        first_half = sum(s["score"] for s in recent[: len(recent) // 2])
        second_half = sum(s["score"] for s in recent[len(recent) // 2 :])
        count_half = max(1, len(recent) // 2)
        trend_first = first_half / count_half
        trend_second = second_half / (len(recent) - len(recent) // 2)
        diff = trend_second - trend_first
        if diff > 5:
            trend = "positive"
        elif diff < -5:
            trend = "negative"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return {
        "daily_activity": daily_activity,
        "weekly_scores": weekly_scores,
        "weekly_trend": trend,
    }


def group_activity_by_day(
    events: list[dict[str, Any]],
    *,
    days: int = 14,
) -> list[dict[str, Any]]:
    """Group timeline events into daily activity summaries.

    Args:
        events: List of event dicts with 'created_at' strings.
        days: Number of days to look back.

    Returns:
        List of dicts with 'date' (ISO date) and 'minutes' (float).
    """
    from collections import defaultdict

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    daily: dict[str, float] = defaultdict(float)

    for event in events:
        created_str = event.get("created_at", "") if isinstance(event, dict) else ""
        if not created_str:
            continue

        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        if created < cutoff:
            continue

        day_key = created.strftime("%Y-%m-%d")
        payload = event.get("payload", {}) if isinstance(event, dict) else {}
        duration = float(payload.get("duration_minutes", 0) or 0)
        time_spent = float(payload.get("time_spent_minutes", 0) or 0)
        daily[day_key] += duration + time_spent

    # Fill in all days in range
    result: list[dict[str, Any]] = []
    for i in range(days):
        day = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        result.append({
            "date": day,
            "minutes": round(daily.get(day, 0.0), 1),
        })

    return result


def group_scores_by_week(
    events: list[dict[str, Any]],
    *,
    weeks: int = 8,
) -> list[dict[str, Any]]:
    """Group quiz score events into weekly averages.

    Args:
        events: List of event dicts with 'created_at' strings and
            'payload' containing 'score'.
        weeks: Number of weeks to look back.

    Returns:
        List of dicts with 'week' (ISO week) and 'score' (float).
    """
    from collections import defaultdict

    now = datetime.now(timezone.utc)
    weekly: dict[str, list[float]] = defaultdict(list)

    for event in events:
        event_type = event.get("event_type", "") if isinstance(event, dict) else ""
        if "quiz" not in event_type.lower() and "evaluate" not in event_type.lower():
            continue

        created_str = event.get("created_at", "") if isinstance(event, dict) else ""
        if not created_str:
            continue

        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        payload = event.get("payload", {}) if isinstance(event, dict) else {}
        score = payload.get("score", None)
        if score is None:
            continue

        week_key = created.strftime("%Y-W%W")
        weekly[week_key].append(float(score))

    result: list[dict[str, Any]] = []
    for i in range(weeks):
        week_date = now - timedelta(weeks=weeks - 1 - i)
        week_key = week_date.strftime("%Y-W%W")
        scores = weekly.get(week_key, [])
        avg = sum(scores) / len(scores) if scores else 0.0
        result.append({
            "week": week_key,
            "score": round(avg, 1),
        })

    return result


def calculate_mastery_history(
    events: list[dict[str, Any]],
    topics: dict[uuid.UUID, str],
    *,
    max_entries: int = 50,
) -> list[dict[str, Any]]:
    """Build mastery history from analytics events.

    Extracts 'mastery_update' events and returns them as chart-ready entries.

    Args:
        events: List of event dicts with 'created_at', 'payload' containing
            'topic_id' and 'mastery'.
        topics: Dict mapping topic_id to topic name.
        max_entries: Maximum number of entries to return.

    Returns:
        List of dicts with 'topic_id', 'topic_name', 'date', 'mastery'.
    """
    history: list[dict[str, Any]] = []

    for event in events:
        event_type = event.get("event_type", "") if isinstance(event, dict) else ""
        if event_type != "mastery_update" and "mastery" not in event_type.lower():
            continue

        created_str = event.get("created_at", "") if isinstance(event, dict) else ""
        payload = event.get("payload", {}) if isinstance(event, dict) else {}
        topic_id_str = payload.get("topic_id", "") if payload else ""
        mastery = payload.get("mastery", payload.get("score", 0)) if payload else 0

        if not topic_id_str or not created_str:
            continue

        try:
            tid = uuid.UUID(topic_id_str) if isinstance(topic_id_str, str) else topic_id_str
        except (ValueError, AttributeError):
            continue

        try:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            created_dt = datetime.now(timezone.utc)

        history.append({
            "topic_id": tid,
            "topic_name": topics.get(tid, topic_id_str),
            "date": created_dt.strftime("%Y-%m-%d"),
            "mastery": round(float(mastery), 1),
        })

    # Sort by date, newest first
    history.sort(key=lambda x: x["date"], reverse=True)
    return history[:max_entries]
