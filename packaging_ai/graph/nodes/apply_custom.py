from __future__ import annotations

from packaging_ai.graph.state import PackagingState
from packaging_ai.logutil import get_logger
from packaging_ai.planning.custom_requirements import apply_custom_requirements

log = get_logger("graph.apply_custom")


def apply_custom_node(state: PackagingState) -> dict:
    """LLM-merge operator custom requirements into InstallPlan step lists."""
    plan = state.get("install_plan")
    custom = (state.get("custom_requirements") or "").strip()
    if plan is None or not custom:
        return {}

    log.info("Applying custom requirements (%s chars)", len(custom))
    updated = apply_custom_requirements(
        plan,
        custom,
        user_clarifications=list(state.get("user_clarifications") or []),
    )
    if updated.open_questions:
        log.warning(
            "Custom requirements left %s open question(s)",
            len(updated.open_questions),
        )
    return {"install_plan": updated}
