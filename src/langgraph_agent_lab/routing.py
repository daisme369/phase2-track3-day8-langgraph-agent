"""Routing functions for conditional edges."""

from __future__ import annotations

from .state import AgentState, Route


def route_after_classify(state: AgentState) -> str:
    """Map classified route to the next graph node.

    Unknown routes degrade gracefully to clarification.
    """
    route = str(state.get("route", "")).strip().lower() or Route.SIMPLE.value
    mapping = {
        Route.SIMPLE.value: "answer",
        Route.TOOL.value: "tool",
        Route.MISSING_INFO.value: "clarify",
        Route.RISKY.value: "risky_action",
        Route.ERROR.value: "retry",
        Route.DEAD_LETTER.value: "dead_letter",
    }
    return mapping.get(route, "clarify")


def route_after_retry(state: AgentState) -> str:
    """Decide whether to retry, fallback, or dead-letter.

    Bounded retry: tool while attempt < max_attempts, else dead-letter.
    """
    attempt = int(state.get("attempt", 0))
    max_attempts = max(int(state.get("max_attempts", 3)), 1)
    if attempt >= max_attempts:
        return "dead_letter"
    return "tool"


def route_after_evaluate(state: AgentState) -> str:
    """Decide whether tool result is satisfactory or needs retry.

    This is the 'done?' check that enables retry loops — a key LangGraph advantage over LCEL.
    Accepts both explicit retry and terminal error outcomes.
    """
    result = str(state.get("evaluation_result") or "").strip().lower()
    if result in {"needs_retry", "retry"}:
        return "retry"
    if result in {"error", "dead_letter"}:
        return "dead_letter"
    return "answer"


def route_after_approval(state: AgentState) -> str:
    """Continue only if approved.

    Supports approved, edited, rejected and timeout-escalated outcomes.
    """
    approval = state.get("approval") or {}
    status = str(approval.get("status", "")).strip().lower()
    if status in {"approved", "edited"}:
        return "tool"
    if status in {"rejected", "timeout"}:
        return "clarify"
    return "tool" if approval.get("approved") else "clarify"
