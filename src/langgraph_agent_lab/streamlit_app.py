"""Streamlit audit UI for the Day 08 LangGraph lab.

This UI is offline-friendly and uses the existing mock workflow.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from langgraph_agent_lab.graph import build_graph
from langgraph_agent_lab.nodes import classify_node, intake_node
from langgraph_agent_lab.persistence import build_checkpointer
from langgraph_agent_lab.scenarios import load_scenarios
from langgraph_agent_lab.state import Route, Scenario, initial_state

HITL_MODES = ["approve", "reject", "edit", "timeout"]


def _preview_route(query: str) -> str:
    state: dict[str, Any] = {"query": query}
    intake_update = intake_node(state)
    merged = {**state, **intake_update}
    classify_update = classify_node(merged)
    return str(classify_update.get("route", Route.SIMPLE.value))


def _apply_mock_approval_mode(mode: str) -> str | None:
    previous = os.getenv("MOCK_APPROVAL_MODE")
    os.environ["MOCK_APPROVAL_MODE"] = mode
    return previous


def _restore_mock_approval_mode(previous: str | None) -> None:
    if previous is None:
        os.environ.pop("MOCK_APPROVAL_MODE", None)
    else:
        os.environ["MOCK_APPROVAL_MODE"] = previous


def _load_ui_scenarios(path: str) -> list[Scenario]:
    try:
        return load_scenarios(path)
    except Exception as exc:
        st.error(f"Không thể load scenarios từ {path}: {exc}")
        return []


def _render_hitl_controls(is_hitl_case: bool) -> tuple[str, str]:
    st.markdown("### Human-in-the-loop decision")
    if not is_hitl_case:
        st.caption("Case này `requires_approval=false` nên hệ thống tự động log quyết định.")
        st.code("AUTO_DECISION=approve")
        return "approve", "auto-log: requires_approval=false"

    if "selected_hitl_mode" not in st.session_state:
        st.session_state.selected_hitl_mode = "approve"

    cols = st.columns(len(HITL_MODES))
    for index, mode in enumerate(HITL_MODES):
        label = mode.upper()
        if cols[index].button(label, use_container_width=True):
            st.session_state.selected_hitl_mode = mode

    note = st.text_input(
        "Decision note (ghi chú audit)",
        value="",
        placeholder="Ví dụ: reject vì thiếu bằng chứng",
        help="Ghi chú này sẽ được lưu trong bảng decision logs của UI.",
    )

    current_mode = str(st.session_state.selected_hitl_mode)
    st.info(f"Case này yêu cầu phê duyệt. Quyết định hiện tại: `{current_mode}`")
    return current_mode, note


def _run_graph_for_query(
    query: str,
    scenario_id: str,
    requires_approval: bool,
    max_attempts: int,
    checkpointer_kind: str,
    database_url: str,
    hitl_mode: str,
) -> dict[str, Any]:
    scenario = Scenario(
        id=scenario_id,
        query=query,
        expected_route=Route.SIMPLE,
        requires_approval=requires_approval,
        max_attempts=max_attempts,
        tags=["ui"],
    )
    state = initial_state(scenario)
    state["thread_id"] = f"ui-{scenario_id}-{uuid4().hex[:8]}"

    checkpointer = build_checkpointer(
        checkpointer_kind,
        database_url if checkpointer_kind == "sqlite" else None,
    )
    graph = build_graph(checkpointer=checkpointer)

    previous = _apply_mock_approval_mode(hitl_mode)
    try:
        final_state = graph.invoke(
            state,
            config={"configurable": {"thread_id": state["thread_id"]}},
        )
    finally:
        _restore_mock_approval_mode(previous)

    return final_state


def main() -> None:
    st.set_page_config(page_title="LangGraph Audit UI", layout="wide")
    st.title("LangGraph Agent Audit UI")
    st.caption("Offline/mock workflow + HITL decision buttons for risky cases")

    with st.sidebar:
        st.header("Run settings")
        scenario_path = st.text_input("Scenarios path", value="data/sample/scenarios.jsonl")
        checkpointer_kind = st.selectbox("Checkpointer", ["memory", "sqlite"], index=0)
        database_url = st.text_input("SQLite DB path", value="checkpoints.db")

    scenarios = _load_ui_scenarios(scenario_path)
    scenario_map = {item.id: item for item in scenarios}

    selected_id = st.selectbox("Chọn scenario", list(scenario_map.keys()) if scenario_map else [])
    selected = scenario_map.get(selected_id)

    if selected is None:
        st.warning("Chưa có scenario hợp lệ để chạy.")
        return

    use_custom_query = st.checkbox("Dùng custom query", value=False)
    query_value = selected.query
    if use_custom_query:
        query_value = st.text_area("Custom query", value=selected.query, height=100)

    predicted_route = _preview_route(query_value)
    requires_approval = bool(selected.requires_approval)

    st.markdown("### Routing preview")
    c1, c2, c3 = st.columns(3)
    c1.metric("Scenario", selected.id)
    c2.metric("Predicted route", predicted_route)
    c3.metric("Requires approval", "Yes" if requires_approval else "No")

    hitl_mode, decision_note = _render_hitl_controls(requires_approval)

    run_clicked = st.button("Run Audit", type="primary", use_container_width=True)
    if not run_clicked:
        return

    with st.spinner("Running graph..."):
        final_state = _run_graph_for_query(
            query=query_value,
            scenario_id=selected.id,
            requires_approval=requires_approval,
            max_attempts=int(selected.max_attempts),
            checkpointer_kind=checkpointer_kind,
            database_url=database_url,
            hitl_mode=hitl_mode,
        )

    if "decision_logs" not in st.session_state:
        st.session_state.decision_logs = []

    st.session_state.decision_logs.append(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "scenario_id": selected.id,
            "query": query_value,
            "predicted_route": predicted_route,
            "hitl_mode": hitl_mode,
            "decision_note": decision_note,
            "approval_status": (final_state.get("approval") or {}).get("status", "n/a"),
            "actual_route": final_state.get("route"),
        }
    )

    st.success("Run completed")

    st.markdown("### Final summary")
    summary_cols = st.columns(4)
    summary_cols[0].metric("Actual route", str(final_state.get("route", "")))
    summary_cols[1].metric("Risk level", str(final_state.get("risk_level", "")))
    summary_cols[2].metric("Attempt", str(final_state.get("attempt", 0)))
    summary_cols[3].metric(
        "Approval status",
        str((final_state.get("approval") or {}).get("status", "n/a")),
    )

    st.markdown("### Final answer")
    st.write(final_state.get("final_answer") or final_state.get("pending_question") or "")

    st.markdown("### Audit events")
    st.dataframe(final_state.get("events", []), use_container_width=True)

    st.markdown("### Tool results")
    st.json(final_state.get("tool_results", []), expanded=False)

    st.markdown("### Errors")
    st.json(final_state.get("errors", []), expanded=False)

    st.markdown("### HITL decision logs (UI)")
    st.dataframe(st.session_state.decision_logs, use_container_width=True)


if __name__ == "__main__":
    main()
