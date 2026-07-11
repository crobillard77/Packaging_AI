"""Load and apply Templates/PSADT_Requirements.md during packaging."""

from __future__ import annotations

import re

from packaging_ai.config import PSADT_REQUIREMENTS_FILE
from packaging_ai.models import InstallPlan, InstallerFamily

# Match: "C:\Path\uninstall.exe" /S   or   C:\Path\uninstall.exe /S
_RAW_UNINSTALL_RE = re.compile(
    r'^\s*(?:"(?P<quoted>[^"]+)"|(?P<bare>\S+\.exe))\s*(?P<args>.*)$',
    re.IGNORECASE,
)


def load_psadt_requirements() -> str:
    if not PSADT_REQUIREMENTS_FILE.is_file():
        raise FileNotFoundError(
            f"Missing PSADT requirements file: {PSADT_REQUIREMENTS_FILE}"
        )
    return PSADT_REQUIREMENTS_FILE.read_text(encoding="utf-8")


def strip_hardcoded_paths(text: str) -> str:
    """Replace common hardcoded Program Files roots with PSADT env vars."""
    patterns = [
        (r"(?i)C:\\Program Files \(x86\)\\", r"$envProgramFilesX86\\"),
        (r"(?i)C:\\Program Files\\", r"$envProgramFiles\\"),
        (r"(?i)%ProgramFiles\(x86\)%\\", r"$envProgramFilesX86\\"),
        (r"(?i)%ProgramFiles%\\", r"$envProgramFiles\\"),
        (r"(?i)\$env:ProgramFiles\(x86\)\\", r"$envProgramFilesX86\\"),
        (r"(?i)\$env:ProgramFiles\\", r"$envProgramFiles\\"),
    ]
    result = text
    for pattern, repl in patterns:
        result = re.sub(pattern, repl, result)
    return result


def normalize_uninstall_command(command: str | None) -> str:
    """Accept raw uninstall.exe forms and convert to Execute-Process without hardcoded roots.

    Example input:
      "C:\\Program Files\\Notepad++\\uninstall.exe" /S
      C:\\Program Files\\Notepad++\\uninstall.exe|/S
    Example output:
      Execute-Process -Path "$envProgramFiles\\Notepad++\\uninstall.exe" -Parameters "/S" -WindowStyle Hidden
    """
    if not command:
        return ""
    cmd = command.strip()
    if not cmd or "<uninstall_path>" in cmd or "TODO" in cmd:
        return cmd

    if "|" in cmd and "Execute-" not in cmd:
        path_part, args_part = cmd.split("|", 1)
        cmd = f'"{path_part.strip()}" {args_part.strip()}'

    if any(
        token in cmd
        for token in ("Execute-MSI", "Execute-Process", "Remove-MSIApplications")
    ):
        return strip_hardcoded_paths(cmd)

    match = _RAW_UNINSTALL_RE.match(cmd)
    if not match:
        return strip_hardcoded_paths(cmd)

    path = match.group("quoted") or match.group("bare") or ""
    args = (match.group("args") or "").strip()
    path = strip_hardcoded_paths(path)
    args_ps = args.replace('"', '`"')
    return (
        f'Execute-Process -Path "{path}" '
        f'-Parameters "{args_ps}" -WindowStyle Hidden'
    )


def is_valid_uninstall(command: str | None) -> bool:
    """A valid uninstall must be a real command, not a TODO/placeholder."""
    if not command or not command.strip():
        return False
    if "<uninstall_path>" in command or "TODO" in command:
        return False

    normalized = normalize_uninstall_command(command)
    active = [
        line.strip()
        for line in normalized.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not active:
        return False
    body = "\n".join(active)
    if any(
        token in body
        for token in ("Execute-MSI", "Execute-Process", "Remove-MSIApplications")
    ):
        return True
    # Raw uninstall.exe path still counts as valid input (will be normalized)
    return bool(_RAW_UNINSTALL_RE.match(command.strip()))


def is_exe_primary(plan: InstallPlan) -> bool:
    """True when the primary installer is an EXE family (not MSI/MST)."""
    family = plan.primary_family
    if family is None:
        return False
    return family not in {InstallerFamily.MSI, InstallerFamily.MST}


def exe_metadata_incomplete(plan: InstallPlan) -> bool:
    """EXE packages need Publisher, AppName, and Version from real metadata or META clarification.

    Filename stem / default 1.0.0 alone do not satisfy this (vendor stays empty until confirmed).
    """
    if not is_exe_primary(plan):
        return False
    vendor = (plan.app_vendor or "").strip()
    name = (plan.app_name or "").strip()
    version = (plan.app_version or "").strip()
    return not vendor or not name or not version


def parse_meta_clarification(text: str) -> tuple[str, str, str] | None:
    """Parse META:Publisher|AppName|Version from a clarification string."""
    if not text.startswith("META:"):
        return None
    payload = text[5:].strip()
    parts = [p.strip() for p in payload.split("|")]
    if len(parts) < 3:
        return None
    vendor, name, version = parts[0], parts[1], parts[2]
    if not vendor or not name or not version:
        return None
    return vendor, name, version


def requirements_findings(plan: InstallPlan) -> list[str]:
    """Check Install_Plan against PSADT_Requirements.md rules."""
    _ = load_psadt_requirements()  # ensure file exists and is used
    findings: list[str] = []

    if not plan.primary_installer:
        findings.append("Requirements: primary installer is required.")
    if not plan.app_name:
        findings.append("Requirements: $appName must be set.")
    if not plan.app_version:
        findings.append("Requirements: $appVersion must be set.")
    if not plan.install_command:
        findings.append("Requirements: install command is required.")
    if not is_valid_uninstall(plan.uninstall_command):
        findings.append(
            "Requirements: a valid uninstall command is MANDATORY "
            "(Execute-MSI / Execute-Process, or quoted uninstall.exe + args; "
            "TODO or placeholders are not allowed)."
        )
    elif plan.uninstall_command and re.search(
        r"(?i)C:\\Program Files", plan.uninstall_command
    ):
        findings.append(
            "Requirements: uninstall still contains a hardcoded Program Files path; "
            "use $envProgramFiles / $envProgramFilesX86."
        )

    family = plan.primary_family
    cmd = plan.install_command or ""
    if family == InstallerFamily.MSI and not plan.footprint_mst_name:
        has_existing_mst = any(
            str(t).lower().endswith(".mst") for t in (plan.transforms or [])
        )
        if not has_existing_mst:
            findings.append(
                "Requirements: MSI without MST must generate a footprint MST "
                "(from Templates/FootPrint/FootPrintTemplate.reg)."
            )
    if family == InstallerFamily.MSI and cmd and "-Parameters" in cmd:
        findings.append(
            "Requirements: do not pass -Parameters on Execute-MSI for reboot/logging; "
            "use AppDeployToolkitConfig.xml instead."
        )
    if family and family != InstallerFamily.MSI and family != InstallerFamily.MST:
        if family != InstallerFamily.OTHER and "Execute-Process" not in cmd and "Execute-MSI" not in cmd:
            findings.append("Requirements: EXE install must use Execute-Process (or Execute-MSI when applicable).")

    if cmd and ("$dirFiles" in cmd or "Files\\" in cmd or "Files/" in cmd or "$dirApp" in cmd):
        findings.append(
            "Requirements: do not use Files/, $dirFiles, or $dirApp; "
            "installer must be at package root ($scriptDirectory)."
        )
    elif cmd and "$scriptDirectory" not in cmd and not cmd.startswith(".\\"):
        if "Execute-MSI" in cmd or "Execute-Process" in cmd:
            if "Uninstall" not in cmd:
                findings.append(
                    "Requirements: installer path should use $scriptDirectory (package root)."
                )

    if family == InstallerFamily.MSI and not plan.app_vendor:
        findings.append(
            "Requirements: MSI script naming needs Publisher (Manufacturer); $appVendor is empty."
        )
    if family == InstallerFamily.MSI and not (plan.app_arch or "").strip():
        findings.append(
            "Requirements: MSI $appArch SHOULD be set from Platform / Summary Template (x86/x64)."
        )

    if exe_metadata_incomplete(plan):
        findings.append(
            "Requirements: EXE packaging requires Publisher, AppName, and Version "
            "(prompt for clarification when they cannot be read from the installer)."
        )

    if family and family not in {InstallerFamily.MSI, InstallerFamily.MST, InstallerFamily.OTHER}:
        post = "\n".join(plan.post_install_steps or [])
        post_un = "\n".join(plan.post_uninstall_steps or [])
        if "Set-RegistryKey" not in post or "Package_Footprint" not in post:
            findings.append(
                "Requirements: EXE packages must Set-RegistryKey Package_Footprint "
                "in Post-Installation (FootPrint template)."
            )
        if "Remove-RegistryKey" not in post_un or "Package_Footprint" not in post_un:
            findings.append(
                "Requirements: EXE packages must Remove-RegistryKey Package_Footprint "
                "in Post-Uninstallation."
            )

    return findings


def validate_generated_script(script: str, plan: InstallPlan) -> list[str]:
    """Post-generation checks against requirements."""
    _ = load_psadt_requirements()
    findings: list[str] = []
    required_vars = ("$appVendor", "$appName", "$appVersion", "$appScriptAuthor", "$appScriptDate")
    for var in required_vars:
        if var not in script:
            findings.append(f"Generated script missing {var}.")

    if plan.app_name and f"$appName = '{plan.app_name.replace(chr(39), chr(39)+chr(39))}'" not in script:
        if plan.app_name not in script:
            findings.append("Generated script does not contain the planned app name.")

    if plan.install_command and plan.install_command.split("\n")[0].strip() not in script:
        findings.append("Generated script is missing the planned install command.")

    if not is_valid_uninstall(plan.uninstall_command):
        findings.append("Generated plan is missing a valid uninstall command.")
    elif plan.uninstall_command:
        normalized = normalize_uninstall_command(plan.uninstall_command)
        first = next(
            (
                line.strip()
                for line in normalized.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ),
            "",
        )
        if first and first not in script:
            findings.append("Generated script is missing the planned uninstall command.")
        if re.search(r"(?i)C:\\Program Files", script):
            findings.append(
                "Generated script contains hardcoded Program Files path; use $envProgramFiles."
            )

    if "AppDeployToolkitMain.ps1" not in script:
        findings.append("Generated script must dot-source AppDeployToolkitMain.ps1.")

    if plan.primary_family and plan.primary_family not in {
        InstallerFamily.MSI,
        InstallerFamily.MST,
        InstallerFamily.OTHER,
    }:
        if "Set-RegistryKey" not in script or "Package_Footprint" not in script:
            findings.append(
                "Generated EXE script missing Set-RegistryKey Package_Footprint "
                "in Post-Installation."
            )
        if "Remove-RegistryKey" not in script:
            findings.append(
                "Generated EXE script missing Remove-RegistryKey for Package_Footprint "
                "on uninstall."
            )

    return findings
