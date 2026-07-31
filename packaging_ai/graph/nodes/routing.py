from __future__ import annotations

from packaging_ai.graph.clarify_needs import clarification_needs, effective_confidence
from packaging_ai.graph.state import PackagingState
from packaging_ai.logutil import get_logger
from packaging_ai.config import CONFIDENCE_THRESHOLD
from packaging_ai.psadt.requirements import (
    exe_metadata_incomplete,
    is_valid_uninstall,
    parse_meta_clarification,
)

log = get_logger("graph.routing")


def route_after_review(state: PackagingState) -> str:
    if state.get("error"):
        log.info("Route after review → end (error set)")
        return "end"
    plan = state.get("install_plan")
    clarifications = state.get("user_clarifications") or []
    already_got_meta = any(parse_meta_clarification(c) for c in clarifications)
    already_got_uninstall = any(c.startswith("UNINSTALL_CMD:") for c in clarifications)
    needs = clarification_needs(state)
    if needs.get("needs_custom_clarify"):
        log.info("Route after review → clarify (custom requirements)")
        return "clarify"
    if plan is not None and exe_metadata_incomplete(plan) and not already_got_meta:
        log.info("Route after review → clarify (EXE metadata)")
        return "clarify"
    if plan is not None and not is_valid_uninstall(plan.uninstall_command):
        log.info("Route after review → clarify (uninstall)")
        return "clarify"
    if (
        plan is not None
        and plan.primary_family is not None
        and plan.primary_family.value not in {"msi", "mst"}
        and not already_got_uninstall
    ):
        log.info("Route after review → clarify (EXE uninstall confirm)")
        return "clarify"
    if state.get("user_confirmed"):
        log.info("Route after review → generate (user confirmed)")
        return "generate"
    if state.get("auto_confirm") and (
        plan is None
        or (
            is_valid_uninstall(plan.uninstall_command)
            and not exe_metadata_incomplete(plan)
            and not needs.get("needs_custom_clarify")
        )
    ):
        log.info("Route after review → generate (auto_confirm)")
        return "generate"
    score = effective_confidence(state)
    if score >= CONFIDENCE_THRESHOLD:
        log.info(
            "Route after review → generate (confidence=%.2f threshold=%.2f)",
            score,
            CONFIDENCE_THRESHOLD,
        )
        return "generate"
    log.info(
        "Route after review → clarify (confidence=%.2f threshold=%.2f)",
        score,
        CONFIDENCE_THRESHOLD,
    )
    return "clarify"


def route_after_clarify(state: PackagingState) -> str:
    if state.get("error"):
        log.info("Route after clarify → end (error set)")
        return "end"
    if state.get("awaiting_clarification"):
        log.info("Route after clarify → end (awaiting API clarification)")
        return "end"
    if state.get("user_confirmed"):
        log.info("Route after clarify → generate")
        return "generate"
    log.info("Route after clarify → plan")
    return "plan"
