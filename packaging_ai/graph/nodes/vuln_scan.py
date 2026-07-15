from __future__ import annotations

from packaging_ai.config import VULN_BLOCK_ON_CRITICAL, VULN_SCAN_ENABLED
from packaging_ai.graph.state import PackagingState
from packaging_ai.logutil import get_logger
from packaging_ai.vuln import review_findings_from_vuln, scan_install_plan

log = get_logger("graph.vuln")


def vuln_scan_node(state: PackagingState) -> dict:
    """Hash, Authenticode, NVD/OSV (+ optional cve-bin-tool) vulnerability assessment."""
    plan = state.get("install_plan")
    if plan is None:
        return {
            "vulnerability_report": None,
            "error": state.get("error"),
        }

    log.info("Scanning installer for known vulnerabilities (hash, Authenticode, NVD/OSV)...")
    report = scan_install_plan(plan)
    log.info(
        "Vuln scan: %s finding(s) (CRITICAL=%s, HIGH=%s, MEDIUM=%s, LOW=%s)",
        len(report.findings),
        report.critical_count,
        report.high_count,
        report.medium_count,
        report.low_count,
    )
    for note in report.notes[:5]:
        log.info("Vuln note: %s", note)
    for err in report.errors[:5]:
        log.warning("Vuln scan error: %s", err)
    if len(report.errors) > 5:
        log.warning("… %s more vuln scan error(s)", len(report.errors) - 5)

    update: dict = {"vulnerability_report": report}
    if (
        VULN_SCAN_ENABLED
        and VULN_BLOCK_ON_CRITICAL
        and report.critical_count > 0
    ):
        msg = (
            f"Blocked: {report.critical_count} CRITICAL CVE(s) matched for "
            f"{report.app_name} {report.app_version}. "
            "Set vuln_block_on_critical=false to allow packaging."
        )
        log.error(msg)
        update["error"] = msg
    return update
