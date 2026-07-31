from __future__ import annotations

import argparse
import sys
from pathlib import Path

from packaging_ai import __version__
from packaging_ai.config import DEFAULT_OUTPUT_DIR, LOG_FILE, LOG_LEVEL
from packaging_ai.graph import run_packaging
from packaging_ai.logutil import end_package_log, get_logger, setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="packaging-ai",
        description=(
            "Packaging AI v1.0 — scan installer media and generate a PSADT 3.10.2 package."
        ),
    )
    parser.add_argument(
        "folder",
        help="Absolute path to a folder containing installer media",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory for generated packages (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Auto-confirm when confidence is below 0.75 (does not skip a missing uninstall)",
    )
    parser.add_argument(
        "--custom-requirements",
        default=None,
        help="Free-text custom packaging requirements for LLM plan enrichment",
    )
    parser.add_argument(
        "--custom-requirements-file",
        default=None,
        help="Path to a text file with custom packaging requirements",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging on the console",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: config log_level / INFO)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Log file path (default: config log_file; empty string disables file logging)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    level = "DEBUG" if args.verbose else (args.log_level or LOG_LEVEL)
    if args.log_file is not None:
        log_file: str | Path | None = args.log_file.strip() or None
    else:
        log_file = LOG_FILE
    setup_logging(level, log_file=log_file, console=True)
    log = get_logger("cli")

    try:
        return _main_impl(args, log, log_file)
    finally:
        end_package_log()


def _main_impl(args: argparse.Namespace, log, log_file) -> int:
    folder = Path(args.folder)
    if not folder.is_absolute():
        log.error("Folder path must be absolute. Got: %s", args.folder)
        return 2
    if not folder.is_dir():
        log.error("Folder not found: %s", folder)
        return 2

    log.info("Packaging AI v%s", __version__)
    log.info("Scanning: %s", folder)
    if log_file:
        log.info("Log file: %s", log_file)

    custom_requirements = (args.custom_requirements or "").strip()
    if args.custom_requirements_file:
        custom_path = Path(args.custom_requirements_file)
        custom_requirements = custom_path.read_text(encoding="utf-8").strip()

    try:
        result = run_packaging(
            folder_path=str(folder),
            output_dir=str(Path(args.output)),
            auto_confirm=bool(args.yes),
            custom_requirements=custom_requirements or None,
        )
    except Exception as exc:
        log.exception("Packaging failed: %s", exc)
        return 1

    if result.get("error"):
        log.error("Stopped: %s", result["error"])
        return 1

    plan = result.get("install_plan")
    score = result.get("confidence_score", 0.0)
    findings = result.get("review_findings") or []
    artifacts = result.get("generated_artifacts")
    review = result.get("review_report")
    vuln = result.get("vulnerability_report")

    model = (plan.model if plan is not None else None) or (
        review.model if review is not None else None
    )
    reviewer = (plan.reviewer if plan is not None else None) or (
        review.reviewer if review is not None else None
    )

    log.info("Confidence: %.2f", score)
    if model:
        label = f"{model}" + (f" ({reviewer})" if reviewer and reviewer != model else "")
        log.info("Review model: %s", label)
    for f in findings:
        log.info("Finding: %s", f)

    if vuln is not None:
        log.info(
            "Vulnerability scan: %s finding(s) (CRITICAL=%s, HIGH=%s, MEDIUM=%s, LOW=%s)",
            len(vuln.findings),
            vuln.critical_count,
            vuln.high_count,
            vuln.medium_count,
            vuln.low_count,
        )
        for h in vuln.file_hashes[:2]:
            log.info("SHA256 %s = %s", Path(h.path).name, h.sha256)
        for s in vuln.signatures[:2]:
            log.info("Signature %s = %s", Path(s.path).name, s.status)
        for finding in vuln.findings[:5]:
            score_s = f" CVSS {finding.cvss_score}" if finding.cvss_score is not None else ""
            log.info("CVE %s [%s]%s", finding.cve_id, finding.severity, score_s)

    if plan is not None:
        log.info(
            "Install_Plan: %s %s %s | family=%s",
            plan.app_vendor,
            plan.app_name,
            plan.app_version,
            plan.primary_family,
        )
        log.info("Primary installer: %s", plan.primary_installer)
        if plan.extracted_via_dark and plan.source_exe:
            log.info("Extracted via dark.exe from: %s", plan.source_exe)
        log.info("Install command: %s", plan.install_command)
        if plan.model:
            model_line = plan.model
            if plan.reviewer and plan.reviewer != plan.model:
                model_line = f"{plan.model} ({plan.reviewer})"
            log.info("Plan model: %s", model_line)

    if artifacts is None:
        log.error("No package was generated.")
        return 1

    log.info("Package ready: %s", artifacts.package_dir)
    log.info("Script: %s", artifacts.deploy_script)
    log.info("AppDeployToolkit: %s", artifacts.toolkit_dir)
    if artifacts.logs_dir:
        log.info("Package logs: %s", artifacts.logs_dir)
    log.info("Install_Plan: %s", artifacts.install_plan_path)
    log.info("Review: %s", artifacts.review_path)
    if artifacts.requirements_path:
        log.info("Requirements: %s", artifacts.requirements_path)
    if getattr(artifacts, "vulnerability_path", None):
        log.info("Vulnerabilities: %s", artifacts.vulnerability_path)
    if getattr(artifacts, "packaging_log_path", None):
        log.info("Packaging log: %s", artifacts.packaging_log_path)
    if artifacts.footprint_mst_path:
        log.info("Footprint MST: %s", artifacts.footprint_mst_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
