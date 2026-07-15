from __future__ import annotations

from pathlib import Path

from packaging_ai.config import (
    VULN_MIN_SEVERITY,
    VULN_SCAN_ENABLED,
)
from packaging_ai.models import InstallPlan, VulnerabilityFinding, VulnerabilityReport
from packaging_ai.logutil import get_logger
from packaging_ai.vuln.cve_bin import lookup_cve_bin_tool
from packaging_ai.vuln.hashing import sha256_file
from packaging_ai.vuln.matching import candidate_cpes, meets_min_severity, severity_rank
from packaging_ai.vuln.nvd import lookup_nvd
from packaging_ai.vuln.osv import lookup_osv
from packaging_ai.vuln.signature import check_authenticode

log = get_logger("vuln.scan")


def scan_install_plan(plan: InstallPlan) -> VulnerabilityReport:
    """Multi-source vulnerability assessment for the planned installer."""
    report = VulnerabilityReport(
        app_vendor=plan.app_vendor or "",
        app_name=plan.app_name or "",
        app_version=plan.app_version or "",
    )
    if not VULN_SCAN_ENABLED:
        report.notes.append("Vulnerability scan disabled by config.")
        log.info("Vulnerability scan disabled by config")
        return report

    paths = _scan_paths(plan)
    report.scanned_paths = paths
    if not paths:
        report.errors.append("No installer path available to scan.")
        log.warning("No installer path available to scan")
        return report

    log.debug("Scanning paths: %s", paths)

    # 1) Hashes
    for path in paths:
        try:
            report.file_hashes.append(sha256_file(path))
        except OSError as exc:
            report.errors.append(f"Hash failed ({path}): {exc}")

    # 2) Authenticode
    for path in paths:
        try:
            report.signatures.append(check_authenticode(path))
        except Exception as exc:
            report.errors.append(f"Signature check failed ({path}): {exc}")

    vendor = plan.app_vendor or ""
    product = plan.app_name or ""
    version = plan.app_version or ""
    if not product or not version:
        report.notes.append(
            "Limited CVE matching: product/version incomplete; hash/signature still recorded."
        )

    findings: dict[str, VulnerabilityFinding] = {}

    # 3) NVD (most accurate for CVE + CPE version ranges)
    if product and version:
        cpes = candidate_cpes(vendor, product, version)
        report.cpes_tried = cpes
        nvd_findings, nvd_errors = lookup_nvd(vendor, product, version, cpes)
        report.sources_used.append("nvd")
        report.errors.extend(nvd_errors)
        for item in nvd_findings:
            findings[item.cve_id] = item

        # 4) OSV (aliases / open-source projects)
        osv_findings, osv_errors = lookup_osv(product, version)
        report.sources_used.append("osv")
        report.errors.extend(osv_errors)
        for item in osv_findings:
            key = item.cve_id
            if key in findings:
                findings[key] = _prefer(findings[key], item)
            else:
                findings[key] = item

    # 5) Optional cve-bin-tool deep scan
    from packaging_ai.vuln.cve_bin import _resolve_cve_bin_tool

    bin_available = _resolve_cve_bin_tool() is not None
    bin_findings, bin_errors = lookup_cve_bin_tool(paths)
    if bin_findings:
        report.sources_used.append("cve-bin-tool")
    elif bin_available and not bin_errors:
        report.sources_used.append("cve-bin-tool")
        report.notes.append("cve-bin-tool ran; no matching CVEs reported for scanned files.")
    report.errors.extend(bin_errors)
    for item in bin_findings:
        if item.cve_id in findings:
            findings[item.cve_id] = _prefer(findings[item.cve_id], item)
        else:
            findings[item.cve_id] = item
    if not bin_available:
        report.notes.append(
            "cve-bin-tool not installed; skipped binary component CVE scan "
            "(pip install cve-bin-tool into this project's .venv for deeper accuracy)."
        )

    # Filter + sort
    filtered = [
        f
        for f in findings.values()
        if meets_min_severity(f.severity, VULN_MIN_SEVERITY) or f.severity == "UNKNOWN"
    ]
    # Keep UNKNOWN only if CVSS suggests medium+ or from binary tool
    filtered = [
        f
        for f in filtered
        if f.severity != "UNKNOWN"
        or (f.cvss_score is not None and f.cvss_score >= 4.0)
        or f.source == "cve-bin-tool"
    ]
    filtered.sort(key=lambda f: (-severity_rank(f.severity), -(f.cvss_score or 0), f.cve_id))
    report.findings = filtered
    report.critical_count = sum(1 for f in filtered if f.severity == "CRITICAL")
    report.high_count = sum(1 for f in filtered if f.severity == "HIGH")
    report.medium_count = sum(1 for f in filtered if f.severity == "MEDIUM")
    report.low_count = sum(1 for f in filtered if f.severity == "LOW")

    unsigned = [s for s in report.signatures if not s.is_valid]
    if unsigned:
        report.notes.append(
            "One or more scanned files are not Valid Authenticode-signed: "
            + ", ".join(f"{Path(s.path).name} ({s.status})" for s in unsigned)
        )

    if not report.sources_used:
        report.sources_used.append("hash+signature")

    return report


def review_findings_from_vuln(report: VulnerabilityReport) -> list[str]:
    """Human-readable findings to merge into the packaging review."""
    lines: list[str] = []
    if report.critical_count or report.high_count:
        lines.append(
            f"Vulnerability scan: {report.critical_count} CRITICAL, "
            f"{report.high_count} HIGH CVE(s) matched for "
            f"{report.app_name} {report.app_version}."
        )
    for finding in report.findings[:8]:
        score = f" CVSS {finding.cvss_score}" if finding.cvss_score is not None else ""
        lines.append(
            f"CVE: {finding.cve_id} [{finding.severity}]{score} via {finding.source}"
            + (f" — {finding.summary[:120]}" if finding.summary else "")
        )
    for sig in report.signatures:
        if not sig.is_valid:
            lines.append(
                f"Authenticode: {Path(sig.path).name} status={sig.status}"
                + (f" signer={sig.signer}" if sig.signer else " (not validly signed)")
            )
    return lines


def _scan_paths(plan: InstallPlan) -> list[str]:
    paths: list[str] = []
    for candidate in (plan.primary_installer, plan.source_exe):
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file() and str(path.resolve()) not in paths:
            paths.append(str(path.resolve()))
    return paths


def _prefer(a: VulnerabilityFinding, b: VulnerabilityFinding) -> VulnerabilityFinding:
    if severity_rank(b.severity) > severity_rank(a.severity):
        return b
    if (b.cvss_score or 0) > (a.cvss_score or 0):
        return b
    # Prefer NVD for CPE match metadata
    if a.source == "nvd":
        return a.model_copy(
            update={"references": list(dict.fromkeys(a.references + b.references))[:8]}
        )
    if b.source == "nvd":
        return b.model_copy(
            update={"references": list(dict.fromkeys(b.references + a.references))[:8]}
        )
    return a


def __getattr__(name: str):
    # compatibility for "from packaging_ai.vuln import scan_install_plan"
    if name == "scan_install_plan":
        return scan_install_plan
    raise AttributeError(name)
