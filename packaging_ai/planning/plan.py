from __future__ import annotations

import re
from pathlib import Path

from packaging_ai.installers.silent import build_install_parameters, log_param_for
from packaging_ai.models import DetectedInstaller, InstallPlan, InstallerFamily
from packaging_ai.psadt.requirements import (
    normalize_uninstall_command,
    parse_meta_clarification,
)


def build_install_plan(
    detected: list[DetectedInstaller],
    user_clarifications: list[str] | None = None,
) -> InstallPlan:
    """Build a structured Install_Plan from classified installers (FR-6, FR-7)."""
    clarifications = user_clarifications or []
    primary = _select_primary(detected, clarifications)
    if primary is None:
        return InstallPlan(
            open_questions=["No primary installer (.msi/.exe) found in the folder."],
            assumptions=[],
        )

    transforms = [d.path for d in detected if d.family == InstallerFamily.MST]
    secondary = [
        d.path
        for d in detected
        if d.path != primary.path and d.family != InstallerFamily.MST
    ]

    vendor, name, version = _metadata_from_primary(primary)
    product_code = primary.msi.product_code if primary.msi else None
    upgrade_code = primary.msi.upgrade_code if primary.msi else None

    install_cmd, uninstall_cmd, log_param, suggested_uninstall = _commands(
        primary, transforms, product_code
    )

    # Apply clarification overrides (metadata + uninstall)
    for text in clarifications:
        meta = parse_meta_clarification(text)
        if meta:
            vendor, name, version = meta
        if text.startswith("UNINSTALL_CMD:"):
            override = text.split(":", 1)[1].strip()
            if override:
                uninstall_cmd = normalize_uninstall_command(override)

    open_questions: list[str] = []
    assumptions: list[str] = [
        "Single primary installer selected unless user clarification overrides.",
        f"Detected installer family: {primary.family.value}.",
    ]
    if clarifications:
        assumptions.append(f"Applied user clarifications: {clarifications}")
    if primary.extracted_via_dark and primary.source_exe:
        assumptions.append(
            f"Primary MSI was extracted from EXE via dark.exe ({Path(primary.source_exe).name})."
        )

    if primary.family == InstallerFamily.UNKNOWN_EXE:
        open_questions.append(
            "EXE installer family is unknown; silent/log switches may be incorrect."
        )
    if primary.family != InstallerFamily.MSI and log_param_for(primary.family) is None:
        assumptions.append(
            f"{primary.family.value} has no standard log-file CLI switch; "
            "installer log parameter omitted."
        )
    if primary.family == InstallerFamily.MSI and not product_code:
        open_questions.append("MSI ProductCode could not be read; uninstall may need adjustment.")
    if not name:
        open_questions.append("Application name is missing; confirm app name for PSADT variables.")
    if not version:
        open_questions.append("Application version is missing; confirm version for PSADT variables.")
    if primary.family != InstallerFamily.MSI and primary.family != InstallerFamily.MST:
        if not vendor or not name or not version:
            open_questions.append(
                "EXE Publisher, AppName, and/or Version could not be read; "
                "confirm as Publisher|AppName|Version."
            )
    if len([d for d in detected if d.is_primary_candidate]) > 1:
        open_questions.append(
            "Multiple primary installer candidates found; confirm the correct primary."
        )

    # MSI: fall back to filename / 1.0.0. EXE uses the same display defaults until
    # META clarification supplies Publisher|AppName|Version (stem / 1.0.0 are not "found").
    app_vendor = vendor or ""
    app_name = name or Path(primary.path).stem
    app_version = version or "1.0.0"
    pre_steps: list[str] = []
    post_steps: list[str] = []
    post_uninstall_steps: list[str] = []
    footprint_mst_name: str | None = None
    footprint_reg_name: str | None = None

    # MSI without MST → create MST embedding footprint registry (from FootPrint template)
    if primary.family == InstallerFamily.MSI and not transforms:
        footprint_mst_name = _footprint_mst_filename(app_vendor, app_name)
        footprint_reg_name = f"{app_vendor}{app_name}".strip() or "PackageFootprint"
        # Planned MST name in transforms for plan/review consistency (file created at generate)
        transforms = [footprint_mst_name]
        arch_hint = _resolve_arch(primary) or "x86"
        reg_view = (
            "64-bit HKLM\\SOFTWARE"
            if arch_hint.lower() in {"x64", "amd64", "arm64"}
            else "32-bit registry view (Wow6432Node on 64-bit Windows)"
        )
        assumptions.append(
            "MSI has no MST; a footprint MST will be created from "
            f"FootPrintTemplate.reg and applied via Execute-MSI -Transform ({footprint_mst_name}). "
            f"Footprint registry name is '{footprint_reg_name}' (Vendor+AppName); "
            f"uses {reg_view}. No .reg file is placed in Package/."
        )
        file_name = Path(primary.path).name
        install_cmd = (
            f'Execute-MSI -Action Install -Path "$scriptDirectory\\{file_name}" '
            f'-Transform "$scriptDirectory\\{footprint_mst_name}"'
        )

    # EXE → footprint via Set-RegistryKey / Remove-RegistryKey (same key as FootPrint template)
    if primary.family not in {InstallerFamily.MSI, InstallerFamily.MST}:
        exe_arch = _resolve_arch(primary)
        footprint_reg_name = f"{app_vendor}{app_name}".strip() or "PackageFootprint"
        post_steps = [_exe_footprint_set_registry(exe_arch)]
        post_uninstall_steps = [_exe_footprint_remove_registry(exe_arch)]
        wow = " -Wow6432Node" if (exe_arch or "").lower() == "x86" else ""
        assumptions.append(
            "EXE footprint: Post-Installation Set-RegistryKey and Post-Uninstallation "
            "Remove-RegistryKey for HKLM\\SOFTWARE\\Package_Footprint"
            f"{wow} (name '{footprint_reg_name}' / $($appVendor)$($appName), value 1.00)."
        )

    app_arch = _resolve_arch(primary)
    plan = InstallPlan(
        app_vendor=app_vendor,
        app_name=app_name,
        app_version=app_version,
        app_arch=app_arch,
        primary_installer=primary.path,
        primary_family=primary.family,
        source_exe=primary.source_exe,
        extracted_via_dark=primary.extracted_via_dark,
        transforms=transforms,
        secondary_files=secondary,
        install_command=install_cmd,
        uninstall_command=uninstall_cmd,
        suggested_uninstall=suggested_uninstall,
        log_file_parameter=log_param,
        footprint_reg_name=footprint_reg_name,
        footprint_mst_name=footprint_mst_name,
        deploy_script_name=_deploy_script_name(
            primary.family, app_vendor, app_name, app_version
        ),
        pre_install_steps=pre_steps,
        post_install_steps=post_steps,
        post_uninstall_steps=post_uninstall_steps,
        product_code=product_code,
        upgrade_code=upgrade_code,
        assumptions=assumptions,
        open_questions=open_questions,
    )
    return plan


def _select_primary(
    detected: list[DetectedInstaller],
    clarifications: list[str],
) -> DetectedInstaller | None:
    # Clarification may name a file
    for text in clarifications:
        lower = text.lower()
        for d in detected:
            if Path(d.path).name.lower() in lower or d.path.lower() in lower:
                if d.family in {
                    InstallerFamily.MSI,
                    InstallerFamily.INNO_SETUP,
                    InstallerFamily.NSIS,
                    InstallerFamily.INSTALLSHIELD,
                    InstallerFamily.WIX_BURN,
                    InstallerFamily.ADVANCED_INSTALLER,
                    InstallerFamily.SQUIRREL,
                    InstallerFamily.INSTALL4J,
                    InstallerFamily.UNKNOWN_EXE,
                }:
                    return d

    candidates = [d for d in detected if d.is_primary_candidate]
    if not candidates:
        return None
    # Prefer MSI over EXE
    msis = [d for d in candidates if d.family == InstallerFamily.MSI]
    if msis:
        return sorted(msis, key=lambda d: Path(d.path).name.lower())[0]
    return sorted(candidates, key=lambda d: Path(d.path).name.lower())[0]


def _metadata_from_primary(primary: DetectedInstaller) -> tuple[str | None, str | None, str | None]:
    if primary.msi:
        return (
            primary.msi.manufacturer,
            primary.msi.product_name,
            primary.msi.product_version,
        )
    # EXE: no reliable Publisher/AppName/Version without PE/MSI metadata
    return None, None, None


def _resolve_arch(primary: DetectedInstaller) -> str:
    """Prefer MSI Platform / Summary Template; fall back to filename hints."""
    if primary.msi and primary.msi.architecture:
        return primary.msi.architecture
    return _guess_arch(primary.source_exe or primary.path)


def _guess_arch(path: str) -> str:
    name = Path(path).name.lower()
    if "x64" in name or "amd64" in name or "64-bit" in name or "64bit" in name:
        return "x64"
    if "x86" in name or "win32" in name or "32-bit" in name:
        return "x86"
    return ""


def _commands(
    primary: DetectedInstaller,
    transforms: list[str],
    product_code: str | None,
) -> tuple[str, str, str | None, str | None]:
    file_name = Path(primary.path).name
    # Runtime path under PSADT toolkit log directory
    log_path = r"$configToolkitLogDir\$($appName)_$($appVersion)_Install.log"

    if primary.family == InstallerFamily.MSI:
        transform_arg = ""
        if transforms:
            transform_arg = f' -Transform "$scriptDirectory\\{Path(transforms[0]).name}"'
        # Do not pass /qn, /norestart, or /l*v — PSADT Execute-MSI uses
        # AppDeployToolkitConfig.xml (MSI_LoggingOptions, reboot handling).
        install = (
            f'Execute-MSI -Action Install -Path "$scriptDirectory\\{file_name}"'
            f"{transform_arg}"
        )
        if product_code:
            uninstall = f'Execute-MSI -Action Uninstall -Path "{product_code}"'
        else:
            uninstall = f'Execute-MSI -Action Uninstall -Path "$scriptDirectory\\{file_name}"'
        return install, uninstall, None, None

    install_params, uninstall_params, log_used = build_install_parameters(
        primary.family, log_path=log_path
    )
    args = install_params or primary.silent_install_args or ""
    uargs = uninstall_params or primary.silent_uninstall_args or args
    args_ps = args.replace('"', '`"')
    install = (
        f'Execute-Process -Path "$scriptDirectory\\{file_name}" '
        f'-Parameters "{args_ps}" -WindowStyle Hidden'
    )
    # EXE uninstall is never auto-applied — user must confirm/paste at clarification
    uninstall = (
        f'# TODO: confirm uninstall for {primary.family.value}\n'
        f'        # Execute-Process -Path "<uninstall_path>" -Parameters "{uargs}"'
    )
    suggested = _known_exe_uninstall(primary, uargs)
    if product_code:
        uninstall = f'Execute-MSI -Action Uninstall -Path "{product_code}"'
        return install, uninstall, log_used, suggested
    return install, uninstall, log_used, suggested


def _known_exe_uninstall(primary: DetectedInstaller, silent_args: str) -> str | None:
    """Known EXE uninstall paths using PSADT env vars (no hardcoded drive letters)."""
    name = Path(primary.path).name.lower()
    args = silent_args or "/S"
    args_ps = args.replace('"', '`"')
    if primary.family == InstallerFamily.NSIS and (
        name.startswith("npp.") or "notepad++" in name or "notepadpp" in name
    ):
        return (
            f'Execute-Process -Path "$envProgramFiles\\Notepad++\\uninstall.exe" '
            f'-Parameters "{args_ps}" -WindowStyle Hidden'
        )
    return None


def _footprint_mst_filename(vendor: str, app_name: str) -> str:
    safe = re.sub(r"[^\w.\-]+", "_", f"{vendor}_{app_name}".strip())
    safe = safe.strip("_") or "Package"
    return f"{safe}_FootPrint.mst"


def _deploy_script_name(
    family: InstallerFamily | None,
    vendor: str,
    app_name: str,
    version: str,
) -> str:
    """Publisher_AppName_Version_001.ps1 for MSI and EXE."""
    _ = family  # naming is unified for MSI and EXE
    publisher = re.sub(r"[^\w.\-]+", "_", (vendor or "UnknownPublisher").strip()).strip("_") or "UnknownPublisher"
    name = re.sub(r"[^\w.\-]+", "_", (app_name or "Application").strip()).strip("_") or "Application"
    ver = re.sub(r"[^\w.\-]+", "_", (version or "1.0.0").strip()).strip("_") or "1.0.0"
    return f"{publisher}_{name}_{ver}_001.ps1"


def _exe_footprint_set_registry(architecture: str = "") -> str:
    """PSADT Set-RegistryKey matching FootPrintTemplate.reg semantics."""
    wow = " -Wow6432Node" if (architecture or "").lower() == "x86" else ""
    return (
        "Set-RegistryKey -Key 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Package_Footprint' "
        f"-Name \"$($appVendor)$($appName)\" -Value '1.00' -Type 'String'{wow}"
    )


def _exe_footprint_remove_registry(architecture: str = "") -> str:
    """PSADT Remove-RegistryKey for the EXE footprint value."""
    wow = " -Wow6432Node" if (architecture or "").lower() == "x86" else ""
    return (
        "Remove-RegistryKey -Key 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Package_Footprint' "
        f"-Name \"$($appVendor)$($appName)\"{wow}"
    )
