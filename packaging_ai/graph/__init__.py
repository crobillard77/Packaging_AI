from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from packaging_ai.graph.nodes import (
    classify_node,
    clarify_node,
    generate_node,
    plan_node,
    review_node,
    route_after_clarify,
    route_after_review,
    scan_node,
    vuln_scan_node,
)
from packaging_ai.graph.state import PackagingState
from packaging_ai.logutil import begin_run_capture, end_package_log, get_logger

log = get_logger("graph")


def build_graph():
    graph = StateGraph(PackagingState)
    graph.add_node("scan", scan_node)
    graph.add_node("classify", classify_node)
    graph.add_node("plan", plan_node)
    graph.add_node("vuln_scan", vuln_scan_node)
    graph.add_node("review", review_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "scan")
    graph.add_edge("scan", "classify")
    graph.add_edge("classify", "plan")
    graph.add_edge("plan", "vuln_scan")
    graph.add_edge("vuln_scan", "review")
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {"generate": "generate", "clarify": "clarify", "end": END},
    )
    graph.add_conditional_edges(
        "clarify",
        route_after_clarify,
        {"plan": "plan", "generate": "generate", "end": END},
    )
    graph.add_edge("generate", END)
    return graph.compile()


def run_packaging(
    folder_path: str,
    output_dir: str | None = None,
    auto_confirm: bool = False,
    *,
    interactive: bool = True,
    user_clarifications: list[str] | None = None,
    user_confirmed: bool = False,
) -> PackagingState:
    begin_run_capture()
    log.info(
        "Starting packaging run (folder=%s, output=%s, auto_confirm=%s, interactive=%s)",
        folder_path,
        output_dir or "(default)",
        auto_confirm,
        interactive,
    )
    app = build_graph()
    initial: PackagingState = {
        "folder_path": folder_path,
        "output_dir": output_dir or "",
        "auto_confirm": auto_confirm,
        "user_confirmed": user_confirmed,
        "interactive": interactive,
        "awaiting_clarification": False,
        "user_clarifications": list(user_clarifications or []),
        "detected_installers": [],
        "confidence_score": 0.0,
        "review_findings": [],
    }
    result: PackagingState | None = None
    try:
        result = app.invoke(initial)  # type: ignore[assignment]
        if result.get("awaiting_clarification"):
            log.info("Packaging run paused awaiting clarification")
        elif result.get("error"):
            log.error("Packaging run ended with error: %s", result.get("error"))
        else:
            log.info("Packaging run finished successfully")
        return result  # type: ignore[return-value]
    finally:
        artifacts = result.get("generated_artifacts") if result else None
        # If no package log was created (failed before generate), clear handlers.
        # If package log exists, leave it attached so the CLI summary is appended;
        # CLI calls end_package_log() when done.
        if not (artifacts and getattr(artifacts, "packaging_log_path", None)):
            end_package_log()
