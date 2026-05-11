"""Node skeletons for the LangGraph workflow.

Each function should be small, testable, and return a partial state update. Avoid mutating the
input state in place.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .state import AgentState, ApprovalDecision, Route, make_event

RISKY_KEYWORDS = {"refund", "delete", "send", "cancel", "remove", "revoke"}
TOOL_KEYWORDS = {"status", "order", "lookup", "check", "track", "find", "search"}
ERROR_KEYWORDS = {"timeout", "fail", "failure", "error", "crash", "unavailable"}
MISSING_INFO_PRONOUNS = {"it", "this", "that", "there", "thing"}

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_REGEX = re.compile(r"\b(?:\+?\d[\d\- ]{7,}\d)\b")
ORDER_ID_REGEX = re.compile(r"\b\d{5,}\b")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _load_tool_result(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "error", "message": "malformed_tool_result", "raw": raw}
    if isinstance(data, dict):
        return data
    return {"status": "error", "message": "unexpected_tool_result_type", "raw": raw}


def _decision_from_mode(mode: str, proposed_action: str | None) -> ApprovalDecision:
    normalized_mode = mode.strip().lower()
    if normalized_mode == "reject":
        return ApprovalDecision(
            status="rejected",
            approved=False,
            reviewer="mock-reviewer",
            comment="mock rejection: need stronger evidence",
        )
    if normalized_mode == "edit":
        return ApprovalDecision(
            status="edited",
            approved=True,
            reviewer="mock-reviewer",
            comment="mock edit applied before execution",
            edited_action=(proposed_action or "execute action") + " (edited by reviewer)",
        )
    if normalized_mode == "timeout":
        return ApprovalDecision(
            status="timeout",
            approved=False,
            reviewer="on-call-escalation",
            comment="approval timeout, escalated to on-call",
            escalated=True,
        )
    return ApprovalDecision(
        status="approved",
        approved=True,
        reviewer="mock-reviewer",
        comment="mock approval for lab",
    )


def intake_node(state: AgentState) -> dict:
    """Normalize raw query into state fields.

    Uses deterministic mock extraction to stay offline-friendly.
    """
    raw_query = str(state.get("query", ""))
    query = " ".join(raw_query.strip().split())
    has_email = bool(EMAIL_REGEX.search(query))
    has_phone = bool(PHONE_REGEX.search(query))
    order_ids = ORDER_ID_REGEX.findall(query)
    redacted_query = EMAIL_REGEX.sub("[REDACTED_EMAIL]", query)
    redacted_query = PHONE_REGEX.sub("[REDACTED_PHONE]", redacted_query)
    metadata: dict[str, Any] = {
        "word_count": len(_tokenize(query)),
        "has_email": has_email,
        "has_phone": has_phone,
        "contains_pii": has_email or has_phone,
        "order_ids": order_ids,
    }
    intake_message = f"intake:{redacted_query[:60]}"
    return {
        "query": redacted_query,
        "query_metadata": metadata,
        "messages": [intake_message],
        "events": [
            make_event(
                "intake",
                "completed",
                "query normalized and metadata extracted",
                contains_pii=metadata["contains_pii"],
            )
        ],
    }


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route.

    Mock policy (offline): deterministic keyword + context scoring with explicit priority.
    """
    query = str(state.get("query", "")).lower()
    tokens = _tokenize(query)
    token_set = set(tokens)
    metadata = state.get("query_metadata") or {}
    score = {
        Route.RISKY: len(token_set.intersection(RISKY_KEYWORDS)),
        Route.TOOL: len(token_set.intersection(TOOL_KEYWORDS)),
        Route.ERROR: len(token_set.intersection(ERROR_KEYWORDS)),
        Route.MISSING_INFO: int(
            len(tokens) < 5 and bool(token_set.intersection(MISSING_INFO_PRONOUNS))
        ),
    }
    route = Route.SIMPLE
    risk_level = "low"
    if score[Route.RISKY] > 0:
        route = Route.RISKY
        risk_level = "high"
    elif score[Route.TOOL] > 0:
        route = Route.TOOL
        risk_level = "medium" if metadata.get("contains_pii") else "low"
    elif score[Route.MISSING_INFO] > 0:
        route = Route.MISSING_INFO
    elif score[Route.ERROR] > 0:
        route = Route.ERROR
        risk_level = "medium"
    return {
        "route": route.value,
        "risk_level": risk_level,
        "events": [
            make_event(
                "classify",
                "completed",
                f"route={route.value}",
                scores={key.value: value for key, value in score.items()},
            )
        ],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating.

    Builds a specific question from query metadata and route context.
    """
    metadata = state.get("query_metadata") or {}
    query = str(state.get("query", "")).lower()
    if "order" in query or "status" in query:
        question = "Bạn vui lòng cung cấp mã đơn hàng để mình tra cứu chính xác trạng thái."
    elif metadata.get("contains_pii"):
        question = (
            "Mình đã ẩn thông tin nhạy cảm. Bạn mô tả lại yêu cầu mà "
            "không gửi email/số điện thoại nhé?"
        )
    else:
        question = (
            "Bạn có thể bổ sung ngữ cảnh còn thiếu "
            "(đối tượng, thời gian, kết quả mong muốn) không?"
        )
    return {
        "pending_question": question,
        "final_answer": question,
        "events": [
            make_event("clarify", "completed", "specific clarification requested")
        ],
    }


def tool_node(state: AgentState) -> dict:
    """Call a mock tool.

    Runs deterministic mock tool logic with idempotency and structured output.
    """
    attempt = int(state.get("attempt", 0))
    scenario_id = str(state.get("scenario_id", "unknown"))
    existing = state.get("tool_results", []) or []
    if existing:
        latest = _load_tool_result(existing[-1])
        same_attempt = int(latest.get("attempt", -1)) == attempt
        same_scenario = str(latest.get("scenario_id", "")) == scenario_id
        if same_attempt and same_scenario:
            return {
                "events": [
                    make_event(
                        "tool",
                        "completed",
                        "idempotent reuse of previous tool result",
                        attempt=attempt,
                    )
                ]
            }

    query = str(state.get("query", ""))
    route = str(state.get("route", Route.SIMPLE.value))
    metadata = state.get("query_metadata") or {}
    order_ids = metadata.get("order_ids", [])
    if route == Route.ERROR.value and attempt < 2:
        payload: dict[str, Any] = {
            "status": "error",
            "attempt": attempt,
            "scenario_id": scenario_id,
            "error_code": "TRANSIENT_TIMEOUT",
            "message": "mock transient tool failure",
        }
    else:
        payload = {
            "status": "success",
            "attempt": attempt,
            "scenario_id": scenario_id,
            "action": "lookup_order" if order_ids else "generic_support_action",
            "data": {
                "order_id": order_ids[0] if order_ids else None,
                "summary": f"mock tool processed query: {query[:80]}",
            },
        }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {
        "tool_results": [serialized],
        "events": [
            make_event(
                "tool",
                "completed",
                f"tool executed attempt={attempt}",
                status=payload["status"],
            )
        ],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for approval.

    Builds proposed action with evidence and risk justification.
    """
    query = str(state.get("query", ""))
    tokens = set(_tokenize(query))
    evidence = sorted(token for token in tokens if token in RISKY_KEYWORDS)
    proposed_action = {
        "action": "execute_high_risk_support_change",
        "query_excerpt": query[:120],
        "risk_justification": "contains high-impact keywords requiring human approval",
        "evidence": evidence,
    }
    return {
        "proposed_action": json.dumps(proposed_action, ensure_ascii=False, sort_keys=True),
        "events": [
            make_event(
                "risky_action",
                "pending_approval",
                "approval required before risky execution",
                evidence=evidence,
            )
        ],
    }


def approval_node(state: AgentState) -> dict:
    """Human approval step with optional LangGraph interrupt().

    Set LANGGRAPH_INTERRUPT=true to use real interrupt() for HITL demos.
    Default uses mock decision so tests and CI run offline.

    Supports approve/reject/edit/timeout in mock mode.
    """
    proposed_action = state.get("proposed_action")
    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt

        value = interrupt({
            "proposed_action": proposed_action,
            "risk_level": state.get("risk_level"),
        })
        if isinstance(value, dict):
            decision = ApprovalDecision(**value)
        else:
            decision = ApprovalDecision(status="approved", approved=bool(value))
    else:
        mode = os.getenv("MOCK_APPROVAL_MODE", "approve")
        action_text = str(proposed_action) if proposed_action is not None else None
        decision = _decision_from_mode(mode, action_text)

    updated_proposed_action = proposed_action
    if decision.edited_action:
        updated_proposed_action = decision.edited_action

    event_type = "escalated" if decision.escalated else "completed"
    return {
        "approval": decision.model_dump(),
        "proposed_action": updated_proposed_action,
        "events": [
            make_event(
                "approval",
                event_type,
                f"status={decision.status} approved={decision.approved}",
                escalated=decision.escalated,
            )
        ],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a retry attempt or fallback decision.

    Records retry metadata with exponential backoff.
    """
    attempt = int(state.get("attempt", 0)) + 1
    max_attempts = int(state.get("max_attempts", 3))
    backoff_seconds = min(2 ** max(attempt - 1, 0), 30)
    reason = str(state.get("evaluation_result") or "needs_retry")
    exhausted = attempt >= max_attempts
    errors = [f"retry attempt={attempt} reason={reason} exhausted={exhausted}"]
    return {
        "attempt": attempt,
        "backoff_seconds": backoff_seconds,
        "errors": errors,
        "events": [
            make_event(
                "retry",
                "completed",
                "retry attempt recorded",
                attempt=attempt,
                max_attempts=max_attempts,
                backoff_seconds=backoff_seconds,
                exhausted=exhausted,
            )
        ],
    }


def answer_node(state: AgentState) -> dict:
    """Produce a final response.

    Grounds final answer on tool output and approval state.
    """
    approval = state.get("approval") or {}
    if approval and not approval.get("approved", False):
        answer = "Yêu cầu rủi ro chưa được duyệt. Mình cần thêm xác nhận trước khi thực thi."
    elif state.get("tool_results"):
        latest = _load_tool_result(state["tool_results"][-1])
        if latest.get("status") == "success":
            data = latest.get("data") or {}
            summary = data.get("summary", "mock tool completed")
            answer = f"Kết quả từ mock tool: {summary}"
        else:
            answer = "Mình đã thử xử lý nhưng tool mock đang lỗi tạm thời."
    else:
        answer = "Đây là phản hồi mock an toàn cho yêu cầu của bạn."

    if approval.get("status") == "edited" and approval.get("edited_action"):
        answer = f"{answer} | Hành động đã chỉnh sửa: {approval['edited_action']}"

    return {
        "final_answer": answer,
        "events": [make_event("answer", "completed", "answer generated")],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the 'done?' check that enables retry loops.

    Structured validation over mock tool payloads.
    """
    tool_results = state.get("tool_results", [])
    if not tool_results:
        return {
            "evaluation_result": "needs_retry",
            "events": [make_event("evaluate", "completed", "missing tool result, retry needed")],
        }

    latest = _load_tool_result(tool_results[-1])
    if latest.get("status") != "success":
        message = str(latest.get("message") or latest.get("error_code") or "tool failure")
        return {
            "evaluation_result": "needs_retry",
            "errors": [f"evaluation failed: {message}"],
            "events": [
                make_event(
                    "evaluate",
                    "completed",
                    "tool result indicates failure, retry needed",
                )
            ],
        }

    return {
        "evaluation_result": "success",
        "events": [make_event("evaluate", "completed", "tool result satisfied structured checks")],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Log unresolvable failures for manual review.

    Third layer of error strategy: retry -> fallback -> dead letter.
    Uses mock dead-letter ticket to keep execution offline.
    """
    scenario_id = str(state.get("scenario_id", "unknown"))
    attempt = int(state.get("attempt", 0))
    ticket_id = f"DLQ-{scenario_id}-{attempt}"
    return {
        "final_answer": (
            "Yêu cầu chưa thể hoàn tất sau số lần retry tối đa. "
            f"Đã tạo mock support ticket {ticket_id} để xử lý thủ công."
        ),
        "errors": [f"dead_letter_ticket={ticket_id}"],
        "events": [
            make_event(
                "dead_letter",
                "completed",
                "max retries exceeded, escalated to mock support queue",
                ticket_id=ticket_id,
            )
        ],
    }


def finalize_node(state: AgentState) -> dict:
    """Finalize the run and emit a final audit event."""
    return {"events": [make_event("finalize", "completed", "workflow finished")]}
