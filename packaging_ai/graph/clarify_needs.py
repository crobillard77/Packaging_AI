from __future__ import annotations

from packaging_ai.config import CONFIDENCE_THRESHOLD
from packaging_ai.graph.state import PackagingState
from packaging_ai.planning.custom_requirements import (
    CUSTOM_REQ_PREFIX,
    custom_requirements_applied,
)
from packaging_ai.psadt.requirements import (
    exe_metadata_incomplete,
    is_valid_uninstall,
    parse_meta_clarification,
)


def effective_confidence(state: PackagingState) -> float:
    """Confidence used for routing / soft-confirm.

    Prefer ``review_report.confidence_score`` (same value written to Review_Report.json)
    when present, so UI and gates cannot disagree with the saved report.
    """
    report = state.get("review_report")
    if report is not None:
        return float(report.confidence_score)
    return float(state.get("confidence_score") or 0.0)


def clarification_needs(state: PackagingState) -> dict:
    """Compute what the client must supply before packaging can continue."""
    plan = state.get("install_plan")
    clarifications = state.get("user_clarifications") or []
    already_got_meta = any(parse_meta_clarification(c) for c in clarifications)
    already_got_uninstall = any(c.startswith("UNINSTALL_CMD:") for c in clarifications)
    already_got_custom = any(c.startswith(CUSTOM_REQ_PREFIX) for c in clarifications)
    custom_text = (state.get("custom_requirements") or "").strip()

    needs_meta = (
        plan is not None
        and not already_got_meta
        and exe_metadata_incomplete(plan)
    )
    needs_uninstall = (
        plan is not None
        and not already_got_uninstall
        and (
            not is_valid_uninstall(plan.uninstall_command)
            or (
                plan.primary_family is not None
                and plan.primary_family.value not in {"msi", "mst"}
            )
        )
    )
    open_questions = list(plan.open_questions) if plan and plan.open_questions else []

    # Pause for custom answers when operator text exists and either the LLM left
    # questions, or nothing was applied yet (empty LLM success used to skip this).
    needs_custom_clarify = bool(custom_text) and not already_got_custom and (
        bool(open_questions) or not custom_requirements_applied(plan)
    )
    if needs_custom_clarify and not open_questions:
        open_questions = [
            "Confirm how to apply these custom requirements (include full paths and "
            "when each should run: pre-install / post-install / uninstall):\n"
            f"{custom_text}"
        ]

    score = effective_confidence(state)
    needs_soft_confirm = (
        not needs_meta
        and not needs_uninstall
        and not needs_custom_clarify
        and not state.get("user_confirmed")
        and not (
            state.get("auto_confirm")
            and plan is not None
            and is_valid_uninstall(plan.uninstall_command)
            and not exe_metadata_incomplete(plan)
        )
        and score < CONFIDENCE_THRESHOLD
    )
    return {
        "needs_meta": needs_meta,
        "needs_uninstall": needs_uninstall,
        "needs_soft_confirm": needs_soft_confirm,
        "needs_custom_clarify": needs_custom_clarify,
        "suggested_uninstall": (plan.suggested_uninstall if plan else None),
        "open_questions": open_questions,
    }
