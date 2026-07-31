from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

from packaging_ai.config import (
    FOOTPRINT_REG_TEMPLATE,
    PSADT_SCRIPT_TEMPLATE,
    PSADT_TOOLKIT_DIR,
)
from packaging_ai.models import (
    InstallPlan,
    InstallerFamily,
    PackageArtifacts,
    ReviewReport,
    VulnerabilityReport,
)
from packaging_ai.msi.transform import create_footprint_mst
from packaging_ai.logutil import get_logger, write_package_log
from packaging_ai.psadt.requirements import (
    load_psadt_requirements,
    normalize_uninstall_command,
    validate_generated_script,
)

log = get_logger("psadt.generate")


def generate_psadt_package(
    plan: InstallPlan,
    review: ReviewReport,
    output_root: str | Path,
    vulnerability_report: VulnerabilityReport | None = None,
) -> PackageArtifacts:
    """Create output/{App}_{Ver}/Package and output/{App}_{Ver}/logs."""
    requirements_text = load_psadt_requirements()
    if not PSADT_SCRIPT_TEMPLATE.is_file():
        raise FileNotFoundError(f"Missing PSADT template: {PSADT_SCRIPT_TEMPLATE}")
    if not PSADT_TOOLKIT_DIR.is_dir():
        raise FileNotFoundError(f"Missing AppDeployToolkit: {PSADT_TOOLKIT_DIR}")

    safe_name = _safe_name(plan.app_name or "Application")
    safe_ver = _safe_name(plan.app_version or "1.0.0")
    root_dir = Path(output_root) / f"{safe_name}_{safe_ver}"
    log.info("Writing package under %s", root_dir)
    if root_dir.exists():
        log.info("Removing existing output folder for clean rebuild: %s", root_dir)
        shutil.rmtree(root_dir)
    package_dir = root_dir / "Package"
    logs_dir = root_dir / "logs"
    package_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Persist this run's log under the package logs folder (full session so far + generate)
    packaging_log_path = str(write_package_log(logs_dir, "Packaging_AI.log"))

    toolkit_dest = package_dir / "AppDeployToolkit"
    if toolkit_dest.exists():
        shutil.rmtree(toolkit_dest)
    shutil.copytree(PSADT_TOOLKIT_DIR, toolkit_dest)

    _copy_media(plan, package_dir)

    footprint_mst_path = ""
    working_plan = plan
    if _needs_footprint_mst(plan):
        footprint_mst_path, working_plan = _create_footprint_mst_artifacts(plan, package_dir)

    working_plan = working_plan.model_copy(
        update={
            "model": review.model or working_plan.model,
            "reviewer": review.reviewer or working_plan.reviewer,
        }
    )

    script_text = PSADT_SCRIPT_TEMPLATE.read_text(encoding="utf-8", errors="replace")
    script_text = _fill_template(script_text, working_plan)

    script_issues = validate_generated_script(script_text, working_plan)
    if script_issues:
        review = review.model_copy(
            update={"findings": list(review.findings) + [f"Script check: {i}" for i in script_issues]}
        )

    script_name = deployment_script_name(working_plan)
    deploy_path = package_dir / script_name
    deploy_path.write_text(script_text, encoding="utf-8")

    requirements_dest = logs_dir / "PSADT_Requirements.md"
    requirements_dest.write_text(requirements_text, encoding="utf-8")

    plan_path = logs_dir / "Install_Plan.json"
    plan_path.write_text(working_plan.model_dump_json(indent=2), encoding="utf-8")

    review_path = logs_dir / "Review_Report.json"
    review_path.write_text(review.model_dump_json(indent=2), encoding="utf-8")

    vulnerability_path = ""
    if vulnerability_report is not None:
        vuln_path = logs_dir / "Vulnerability_Report.json"
        vuln_path.write_text(vulnerability_report.model_dump_json(indent=2), encoding="utf-8")
        vulnerability_path = str(vuln_path)

    if not toolkit_dest.is_dir():
        raise RuntimeError("Generated package is missing AppDeployToolkit (invalid).")
    if not requirements_dest.is_file():
        raise RuntimeError("Generated package is missing logs/PSADT_Requirements.md (invalid).")
    if _needs_footprint_mst(plan) and (not footprint_mst_path or not Path(footprint_mst_path).is_file()):
        raise RuntimeError("MSI without MST requires a generated footprint MST (missing).")

    return PackageArtifacts(
        package_dir=str(package_dir),
        deploy_script=str(deploy_path),
        toolkit_dir=str(toolkit_dest),
        files_dir=str(package_dir),
        logs_dir=str(logs_dir),
        install_plan_path=str(plan_path),
        review_path=str(review_path),
        requirements_path=str(requirements_dest),
        vulnerability_path=vulnerability_path,
        packaging_log_path=packaging_log_path,
        footprint_reg_path="",
        footprint_mst_path=footprint_mst_path,
    )


def _needs_footprint_mst(plan: InstallPlan) -> bool:
    """True when this MSI package needs a generated footprint MST."""
    return plan.primary_family == InstallerFamily.MSI and bool(plan.footprint_mst_name)


def _create_footprint_mst_artifacts(
    plan: InstallPlan, package_dir: Path
) -> tuple[str, InstallPlan]:
    """Create MST embedding footprint registry from FootPrintTemplate.reg (no .reg in Package/)."""
    if not FOOTPRINT_REG_TEMPLATE.is_file():
        raise FileNotFoundError(f"Missing footprint template: {FOOTPRINT_REG_TEMPLATE}")

    vendor = plan.app_vendor or "UnknownVendor"
    app_name = plan.app_name or "Application"
    mst_name = plan.footprint_mst_name or f"{_safe_name(vendor)}_{_safe_name(app_name)}_FootPrint.mst"
    footprint_reg_name = plan.footprint_reg_name or f"{vendor}{app_name}".strip() or "PackageFootprint"

    mst_path = package_dir / mst_name
    create_footprint_mst(
        plan.primary_installer,
        mst_path,
        vendor=vendor,
        app_name=app_name,
        footprint_value=(plan.app_version or "").strip() or "1.0.0",
        architecture=plan.app_arch or None,
    )

    msi_name = Path(plan.primary_installer).name
    install_cmd = (
        f'Execute-MSI -Action Install -Path "$scriptDirectory\\{msi_name}" '
        f'-Transform "$scriptDirectory\\{mst_name}"'
    )
    arch = (plan.app_arch or "").strip().lower()
    if arch in {"x64", "amd64", "arm64"}:
        reg_view = "64-bit HKLM\\SOFTWARE (native)"
    else:
        reg_view = "32-bit registry view (Wow6432Node on 64-bit Windows)"
    updated = plan.model_copy(
        update={
            "transforms": [str(mst_path)],
            "install_command": install_cmd,
            "footprint_reg_name": footprint_reg_name,
            "footprint_mst_name": mst_name,
            "deploy_script_name": deployment_script_name(plan),
            "post_install_steps": [],
            "assumptions": list(plan.assumptions)
            + [
                f"Generated footprint MST {mst_name} from FootPrintTemplate.reg "
                f"(registry name '{footprint_reg_name}', value '{(plan.app_version or '').strip() or '1.0.0'}', "
                f"{reg_view}; no .reg file in Package/)."
            ],
        }
    )
    return str(mst_path), updated


def _copy_media(plan: InstallPlan, package_dir: Path) -> None:
    """Copy installer media to Package/ root (no Files/ or SupportFiles/)."""
    paths = [plan.primary_installer, *plan.transforms, *plan.secondary_files]
    for raw in paths:
        if not raw:
            continue
        src = Path(raw)
        if src.is_file():
            dest = package_dir / src.name
            if not dest.exists():
                shutil.copy2(src, dest)


def _fill_template(script: str, plan: InstallPlan) -> str:
    today = date.today().strftime("%m/%d/%Y")
    replacements = {
        "[String]$appVendor = ''": f"[String]$appVendor = '{_ps(plan.app_vendor)}'",
        "[String]$appName = ''": f"[String]$appName = '{_ps(plan.app_name)}'",
        "[String]$appVersion = ''": f"[String]$appVersion = '{_ps(plan.app_version)}'",
        "[String]$appArch = ''": f"[String]$appArch = '{_ps(plan.app_arch)}'",
        "[String]$appLang = 'EN'": f"[String]$appLang = '{_ps(plan.app_lang or 'EN')}'",
        "[String]$appScriptDate = 'XX/XX/20XX'": f"[String]$appScriptDate = '{today}'",
        "[String]$appScriptAuthor = '<author name>'": (
            "[String]$appScriptAuthor = 'Packaging AI'"
        ),
    }
    for old, new in replacements.items():
        script = script.replace(old, new)

    install_block = plan.install_command.strip() or "# (no install command generated)"
    uninstall_block = (
        normalize_uninstall_command(plan.uninstall_command).strip()
        or "# (no uninstall command generated)"
    )

    if plan.pre_install_steps:
        pre = "\n".join(f"        {s}" for s in plan.pre_install_steps)
    else:
        pre = "        # (none)"

    post_steps = list(plan.post_install_steps or [])
    post_uninstall_steps = list(plan.post_uninstall_steps or [])
    if plan.primary_family not in {InstallerFamily.MSI, InstallerFamily.MST}:
        # EXE: footprint registry lines must be last (after any custom requirements).
        arch = (plan.app_arch or "").strip().lower()
        wow = " -Wow6432Node" if arch == "x86" else ""
        set_line = (
            "Set-RegistryKey -Key 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Package_Footprint' "
            f"-Name \"$($appVendor)$($appName)\" -Value '1.00' -Type 'String'{wow}"
        )
        remove_line = (
            "Remove-RegistryKey -Key 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Package_Footprint' "
            f"-Name \"$($appVendor)$($appName)\"{wow}"
        )
        post_steps = [
            s for s in post_steps if not _is_exe_footprint_set_line(s)
        ]
        post_uninstall_steps = [
            s for s in post_uninstall_steps if not _is_exe_footprint_remove_line(s)
        ]
        post_steps.append(set_line)
        post_uninstall_steps.append(remove_line)

    if post_steps:
        post = "\n".join(f"        {s}" for s in post_steps)
    else:
        post = "        # (none)"
    if post_uninstall_steps:
        post_uninstall = "\n".join(f"        {s}" for s in post_uninstall_steps)
    else:
        post_uninstall = "        # (none)"

    script = script.replace(
        "## <Perform Pre-Installation tasks here>",
        f"## <Perform Pre-Installation tasks here>\n{pre}",
        1,
    )
    script = script.replace(
        "## <Perform Installation tasks here>",
        f"## <Perform Installation tasks here>\n        {install_block}",
        1,
    )
    script = script.replace(
        "## <Perform Post-Installation tasks here>",
        f"## <Perform Post-Installation tasks here>\n{post}",
        1,
    )
    script = script.replace(
        "## <Perform Uninstallation tasks here>",
        f"## <Perform Uninstallation tasks here>\n        {uninstall_block}",
        1,
    )
    script = script.replace(
        "## <Perform Post-Uninstallation tasks here>",
        f"## <Perform Post-Uninstallation tasks here>\n{post_uninstall}",
        1,
    )
    return script


def _is_exe_footprint_set_line(step: str) -> bool:
    s = step or ""
    return "Set-RegistryKey" in s and "Package_Footprint" in s


def _is_exe_footprint_remove_line(step: str) -> bool:
    s = step or ""
    return "Remove-RegistryKey" in s and "Package_Footprint" in s


def _ps(value: str) -> str:
    return (value or "").replace("'", "''")


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", value.strip())
    return cleaned.strip("_") or "Package"


def deployment_script_name(plan: InstallPlan) -> str:
    """Publisher_AppName_Version_001.ps1 for MSI and EXE packages."""
    publisher = _safe_name(plan.app_vendor or "UnknownPublisher")
    app_name = _safe_name(plan.app_name or "Application")
    version = _safe_name(plan.app_version or "1.0.0")
    return f"{publisher}_{app_name}_{version}_001.ps1"
