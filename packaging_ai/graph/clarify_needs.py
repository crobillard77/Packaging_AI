from __future__ import annotations

from packaging_ai.graph.state import PackagingState
from packaging_ai.psadt.requirements import (
    exe_metadata_incomplete,
    is_valid_uninstall,
    parse_meta_clarification,
)


def clarification_needs(state: PackagingState) -> dict:
    """Compute what the client must supply before packaging can continue."""
    plan = state.get("install_plan")
    clarifications = state.get("user_clarifications") or []
    already_got_meta = any(parse_meta_clarification(c) for c in clarifications)
    already_got_uninstall = any(c.startswith("UNINSTALL_CMD:") for c in clarifications)

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
    score = float(state.get("confidence_score") or 0.0)
    needs_soft_confirm = (
        not needs_meta
        and not needs_uninstall
        and not state.get("user_confirmed")
        and not (
            state.get("auto_confirm")
            and plan is not None
            and is_valid_uninstall(plan.uninstall_command)
            and not exe_metadata_incomplete(plan)
        )
        and score < 0.75
    )
    return {
        "needs_meta": needs_meta,
        "needs_uninstall": needs_uninstall,
        "needs_soft_confirm": needs_soft_confirm,
        "suggested_uninstall": (plan.suggested_uninstall if plan else None),
        "open_questions": list(plan.open_questions) if plan and plan.open_questions else [],
    }
