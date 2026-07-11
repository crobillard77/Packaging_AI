from __future__ import annotations

import argparse
import sys
from pathlib import Path

from packaging_ai import __version__
from packaging_ai.config import DEFAULT_OUTPUT_DIR
from packaging_ai.graph import run_packaging


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
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    folder = Path(args.folder)
    if not folder.is_absolute():
        print(f"Error: folder path must be absolute. Got: {args.folder}", file=sys.stderr)
        return 2
    if not folder.is_dir():
        print(f"Error: folder not found: {folder}", file=sys.stderr)
        return 2

    print(f"Packaging AI v{__version__}")
    print(f"Scanning: {folder}")

    try:
        result = run_packaging(
            folder_path=str(folder),
            output_dir=str(Path(args.output)),
            auto_confirm=bool(args.yes),
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.get("error"):
        print(f"Stopped: {result['error']}", file=sys.stderr)
        return 1

    plan = result.get("install_plan")
    score = result.get("confidence_score", 0.0)
    findings = result.get("review_findings") or []
    artifacts = result.get("generated_artifacts")
    review = result.get("review_report")

    model = (plan.model if plan is not None else None) or (
        review.model if review is not None else None
    )
    reviewer = (plan.reviewer if plan is not None else None) or (
        review.reviewer if review is not None else None
    )

    print(f"\nConfidence: {score:.2f}")
    if model:
        label = f"{model}" + (f" ({reviewer})" if reviewer and reviewer != model else "")
        print(f"Review model: {label}")
    for f in findings:
        print(f"  - {f}")

    if plan is not None:
        print("\nInstall_Plan summary:")
        print(f"  App: {plan.app_vendor} {plan.app_name} {plan.app_version}")
        print(f"  Primary: {plan.primary_installer}")
        print(f"  Family: {plan.primary_family}")
        if plan.extracted_via_dark and plan.source_exe:
            print(f"  Extracted via dark.exe from: {plan.source_exe}")
        print(f"  Install: {plan.install_command}")
        if plan.model:
            model_line = plan.model
            if plan.reviewer and plan.reviewer != plan.model:
                model_line = f"{plan.model} ({plan.reviewer})"
            print(f"  Model: {model_line}")

    if artifacts is None:
        print("No package was generated.", file=sys.stderr)
        return 1

    print("\nPackage ready:")
    print(f"  Package: {artifacts.package_dir}")
    print(f"  Script: {artifacts.deploy_script}")
    print(f"  AppDeployToolkit: {artifacts.toolkit_dir}")
    if artifacts.logs_dir:
        print(f"  Logs: {artifacts.logs_dir}")
    print(f"  Install_Plan: {artifacts.install_plan_path}")
    print(f"  Review: {artifacts.review_path}")
    if artifacts.requirements_path:
        print(f"  Requirements: {artifacts.requirements_path}")
    if artifacts.footprint_mst_path:
        print(f"  Footprint MST: {artifacts.footprint_mst_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
