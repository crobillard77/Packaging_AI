from __future__ import annotations

from packaging_ai.config import CONFIDENCE_THRESHOLD
from packaging_ai.graph.state import PackagingState
from packaging_ai.logutil import get_logger
from packaging_ai.planning import review_install_plan
from packaging_ai.vuln import review_findings_from_vuln

log = get_logger("graph.review")


def review_node(state: PackagingState) -> dict:
    plan = state.get("install_plan")
    if plan is None:
        log.error("No install plan to review.")
        return {
            "confidence_score": 0.0,
            "review_findings": ["No install plan to review."],
            "review_report": None,
        }
    vuln = state.get("vulnerability_report")
    log.info("Reviewing Install_Plan against PSADT requirements...")
    report = review_install_plan(plan, vulnerability_report=vuln)
    if vuln is not None:
        extra = review_findings_from_vuln(vuln)
        merged = list(report.findings)
        for line in extra:
            if line not in merged:
                merged.append(line)
        score = float(report.confidence_score)
        if vuln.critical_count:
            score = min(score, max(0.0, score - 0.2))
        elif vuln.high_count:
            score = min(score, max(0.0, score - 0.1))
        score = round(score, 2)
        report = report.model_copy(
            update={
                "findings": merged,
                "confidence_score": score,
                "approved": bool(report.approved) and score >= CONFIDENCE_THRESHOLD,
            }
        )
    plan = plan.model_copy(
        update={
            "model": report.model,
            "reviewer": report.reviewer,
        }
    )
    log.info(
        "Review complete: confidence=%.2f approved=%s model=%s/%s findings=%s",
        report.confidence_score,
        report.approved,
        report.model,
        report.reviewer,
        len(report.findings),
    )
    for finding in report.findings:
        log.debug("Review finding: %s", finding)
    return {
        "install_plan": plan,
        "confidence_score": report.confidence_score,
        "review_findings": report.findings,
        "review_report": report,
    }
