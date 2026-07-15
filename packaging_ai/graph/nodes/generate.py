from __future__ import annotations

from packaging_ai.config import DEFAULT_OUTPUT_DIR
from packaging_ai.graph.state import PackagingState
from packaging_ai.logutil import get_logger
from packaging_ai.psadt import generate_psadt_package
from packaging_ai.psadt.requirements import exe_metadata_incomplete, is_valid_uninstall

log = get_logger("graph.generate")


def generate_node(state: PackagingState) -> dict:
    if state.get("error"):
        log.error("Skipping generate due to error: %s", state.get("error"))
        return {}
    plan = state.get("install_plan")
    review = state.get("review_report")
    if plan is None:
        return {"error": "Cannot generate package without an Install_Plan."}
    if exe_metadata_incomplete(plan):
        return {
            "error": "Cannot generate package without EXE Publisher, AppName, and Version."
        }
    if not is_valid_uninstall(plan.uninstall_command):
        return {
            "error": "Cannot generate package without a valid uninstall command."
        }
    if review is None:
        from packaging_ai.models import ReviewReport

        review = ReviewReport(
            confidence_score=state.get("confidence_score", 0.0),
            findings=state.get("review_findings") or [],
            approved=True,
            model="unknown",
            reviewer="unknown",
        )
    output_dir = state.get("output_dir") or str(DEFAULT_OUTPUT_DIR)
    log.info(
        "Generating PSADT package for %s %s → %s",
        plan.app_name,
        plan.app_version,
        output_dir,
    )
    artifacts = generate_psadt_package(
        plan,
        review,
        output_dir,
        vulnerability_report=state.get("vulnerability_report"),
    )
    log.info("Package generated: %s", artifacts.package_dir)
    return {"generated_artifacts": artifacts}
