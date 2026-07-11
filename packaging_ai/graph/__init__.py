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
)
from packaging_ai.graph.state import PackagingState


def build_graph():
    graph = StateGraph(PackagingState)
    graph.add_node("scan", scan_node)
    graph.add_node("classify", classify_node)
    graph.add_node("plan", plan_node)
    graph.add_node("review", review_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "scan")
    graph.add_edge("scan", "classify")
    graph.add_edge("classify", "plan")
    graph.add_edge("plan", "review")
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
) -> PackagingState:
    app = build_graph()
    initial: PackagingState = {
        "folder_path": folder_path,
        "output_dir": output_dir or "",
        "auto_confirm": auto_confirm,
        "user_confirmed": False,
        "user_clarifications": [],
        "detected_installers": [],
        "confidence_score": 0.0,
        "review_findings": [],
    }
    result = app.invoke(initial)
    return result  # type: ignore[return-value]
