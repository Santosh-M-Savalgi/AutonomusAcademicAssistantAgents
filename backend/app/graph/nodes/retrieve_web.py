"""Graph node: web retrieval via Tavily.

Distinct from ``retrieve_local`` (ChromaDB). Both feed into the same
context assembly the tutor node consumes, but they run and fail
independently.

If Tavily errors, times out, or returns nothing, this node returns
the state unchanged — lesson generation proceeds with local results.
Tavily failure never blocks /lessons/lesson.

Also fetches 2 YouTube results via ``site:youtube.com`` scoped search.
URLs and titles come directly from Tavily — no LLM paraphrasing.
"""

from __future__ import annotations

import logging
import os

from app.graph.state import AAAState

logger = logging.getLogger(__name__)


def _log_state(node: str, event: str, state: AAAState) -> None:
    """Log key state fields for tracing state flow through the graph."""
    logger.info(
        "STATE %s/%s: learning_goal=%r syllabus_id=%r topics=%d phase=%r error=%r",
        node, event,
        state.get("learning_goal", "")[:80],
        state.get("syllabus_id", "")[:36],
        len(state.get("topics", [])),
        state.get("phase"),
        state.get("error"),
    )

# ── Tavily client (lazy import to avoid load-time errors) ──────────────────

_tavily_client = None


def _get_tavily():
    global _tavily_client
    if _tavily_client is not None:
        return _tavily_client
    try:
        from tavily import TavilyClient

        key = os.environ.get("TAVILY_API_KEY", "")
        if not key:
            logger.warning("TAVILY_API_KEY not set — web retrieval disabled")
            return None
        _tavily_client = TavilyClient(api_key=key)
    except ImportError:
        logger.warning("tavily-python not installed — web retrieval disabled")
        return None
    except Exception as exc:
        logger.warning("Failed to init Tavily: %s", exc)
        return None
    return _tavily_client


# ── Domain filtering for source quality ────────────────────────────────────

# Domains to include (preferred educational/official sources).
# Tavily's ``include_domains`` param takes a list of domains.
# When set, only results from these domains are returned.
_INCLUDE_DOMAINS = [
    "wikipedia.org",
    "docs.python.org",
    "developer.mozilla.org",
    "realpython.com",
    "geeksforgeeks.org",
    "w3schools.com",
    "tutorialspoint.com",
    "freecodecamp.org",
    "kaggle.com",
    "towardsdatascience.com",
    "medium.com",
    "stackoverflow.com",
    "github.com",
    "pytorch.org",
    "tensorflow.org",
    "numpy.org",
    "pandas.pydata.org",
    "scikit-learn.org",
    "learn.microsoft.com",
    "docs.oracle.com",
    "cpython.org",
    "python.org",
    "java.com",
    "oracle.com",
]

# Domains to exclude (forums, user-generated noise).
_EXCLUDE_DOMAINS = [
    "reddit.com",
    "quora.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.com",
    "youtube.com",  # YouTube handled separately
]


async def retrieve_web_node(state: AAAState) -> AAAState:
    """Search the web via Tavily for the current topic.

    Stores results in ``state["retrieval_web"]`` as a dict:
        {
            "web_results": [{"title": ..., "url": ..., "content": ...}],
            "youtube_results": [{"title": ..., "url": ..., "video_id": ...}],
        }

    On failure, sets ``state["retrieval_web"] = None`` and returns
    unchanged — lesson generation proceeds with local results only.
    """
    _log_state("retrieve_web", "enter", state)

    topic_name = state.get("current_topic_name", "")
    topic_description = state.get("current_topic_description", "")

    if not topic_name:
        state["retrieval_web"] = None
        _log_state("retrieve_web", "exit(no_topic)", state)
        return state

    tavily = _get_tavily()
    if tavily is None:
        state["retrieval_web"] = None
        logger.info("Web retrieval skipped: Tavily not available")
        _log_state("retrieve_web", "exit(tavily_unavailable)", state)
        return state

    query = f"{topic_name} {topic_description}".strip()

    # ── Step 1: General web search ─────────────────────────────────────
    web_results: list[dict] = []
    try:
        response = tavily.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_domains=_INCLUDE_DOMAINS,
            exclude_domains=_EXCLUDE_DOMAINS,
        )
        if response and response.get("results"):
            for r in response["results"]:
                web_results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                })
            logger.info(
                "Tavily web: %d results for '%s'",
                len(web_results),
                topic_name,
            )
    except Exception as exc:
        logger.warning("Tavily web search failed for '%s': %s", topic_name, exc)

    # ── Step 2: YouTube search ─────────────────────────────────────────
    youtube_results: list[dict] = []
    try:
        yt_response = tavily.search(
            query=f"site:youtube.com {topic_name} tutorial",
            search_depth="basic",
            max_results=2,
            include_domains=["youtube.com"],
        )
        if yt_response and yt_response.get("results"):
            for r in yt_response["results"]:
                url = r.get("url", "")
                # Extract video ID from URL
                video_id = ""
                if "watch?v=" in url:
                    video_id = url.split("watch?v=")[-1].split("&")[0]
                elif "youtu.be/" in url:
                    video_id = url.split("youtu.be/")[-1].split("?")[0]

                youtube_results.append({
                    "title": r.get("title", ""),
                    "url": url,
                    "video_id": video_id,
                })
            logger.info(
                "Tavily YouTube: %d results for '%s'",
                len(youtube_results),
                topic_name,
            )
    except Exception as exc:
        logger.warning("Tavily YouTube search failed for '%s': %s", topic_name, exc)

    # ── Store results ──────────────────────────────────────────────────
    state["retrieval_web"] = {
        "web_results": web_results,
        "youtube_results": youtube_results,
    }

    _log_state("retrieve_web", "exit", state)
    return state
