from __future__ import annotations

from packaging_ai.graph.state import PackagingState
from packaging_ai.logutil import get_logger
from packaging_ai.planning import build_install_plan

log = get_logger("graph.plan")


def plan_node(state: PackagingState) -> dict:
    detected = state.get("detected_installers") or []
    clarifications = state.get("user_clarifications") or []
    log.info(
        "Building Install_Plan (%s installer(s), %s clarification(s))",
        len(detected),
        len(clarifications),
    )
    plan = build_install_plan(detected, clarifications)
    log.info(
        "Plan ready: %s %s %s (%s)",
        plan.app_vendor,
        plan.app_name,
        plan.app_version,
        plan.primary_family,
    )
    if plan.open_questions:
        log.warning("Open questions: %s", "; ".join(plan.open_questions))
    return {"install_plan": plan}
