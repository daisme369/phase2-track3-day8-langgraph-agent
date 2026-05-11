"""Report generation helper."""

from __future__ import annotations

from pathlib import Path

from .metrics import MetricsReport


def render_report_stub(metrics: MetricsReport) -> str:
    """Render a structured markdown report from metrics output."""
    rows = [
        "| Scenario | Expected route | Actual route | Success | Retries | Interrupts |",
        "|---|---|---|---:|---:|---:|",
    ]
    for item in metrics.scenario_metrics:
        rows.append(
            "| "
            f"{item.scenario_id} | {item.expected_route} | {item.actual_route or '-'} | "
            f"{'yes' if item.success else 'no'} | {item.retry_count} | {item.interrupt_count} |"
        )

    return f"""# Day 08 Lab Report

## 1. Team / student

- Name: _update_me_
- Repo/commit: _update_me_
- Date: _update_me_

## 2. Architecture

Graph flow: `START -> intake -> classify` with conditional routing to
`answer/tool/clarify/risky/retry`.
Tool path follows `tool -> evaluate`, and retry loop uses `retry -> tool`
until bounded by `max_attempts`.
Risky path enforces `risky_action -> approval` before execution. Every
path ends at `finalize -> END`.

## 3. State schema

| Field | Reducer | Why |
|---|---|---|
| messages | append | keep chronological agent trace |
| tool_results | append | preserve all tool attempts for evaluation |
| errors | append | retain failure timeline |
| events | append | audit routing and node-level actions |
| route / evaluation_result / attempt | overwrite | latest decision drives control flow |

## 4. Scenario results

- Total scenarios: {metrics.total_scenarios}
- Success rate: {metrics.success_rate:.2%}
- Average nodes visited: {metrics.avg_nodes_visited:.2f}
- Total retries: {metrics.total_retries}
- Total interrupts: {metrics.total_interrupts}

{chr(10).join(rows)}

## 5. Failure analysis

1. Retry or tool failure: transient tool errors are converted into
   structured `evaluation_result=needs_retry`, then routed through bounded
   retry and dead-letter on exhaustion.
2. Risky action without approval: approval status gates execution
   (`approved/edited -> tool`, `rejected/timeout -> clarify`) to avoid
   unsafe automatic actions.

## 6. Persistence / recovery evidence

Factory supports `memory`, `sqlite`, and `postgres`. SQLite uses WAL mode
and stable connection-backed saver for checkpoint durability.

## 7. Extension work

- Added SQLite checkpointer compatibility with current API
  (`SqliteSaver(conn=sqlite3.connect(...))`).

## 8. Improvement plan

If given more time: add state history demo, richer dead-letter sink
(ticketing API), and optional real HITL UI via interrupt/resume.
"""


def write_report(metrics: MetricsReport, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report_stub(metrics), encoding="utf-8")
