from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class InstallerFamily(str, Enum):
    MSI = "msi"
    MST = "mst"
    INNO_SETUP = "inno_setup"
    NSIS = "nsis"
    INSTALLSHIELD = "installshield"
    WIX_BURN = "wix_burn"
    ADVANCED_INSTALLER = "advanced_installer"
    SQUIRREL = "squirrel"
    INSTALL4J = "install4j"
    UNKNOWN_EXE = "unknown_exe"
    OTHER = "other"


class MsiMetadata(BaseModel):
    product_name: str | None = None
    product_version: str | None = None
    manufacturer: str | None = None
    product_code: str | None = None
    upgrade_code: str | None = None
    platform: str | None = None  # raw MSI Template/Platform (e.g. Intel, x64)
    architecture: str | None = None  # normalized for PSADT: x86 / x64 / ARM64
    properties: dict[str, str] = Field(default_factory=dict)


class DetectedInstaller(BaseModel):
    path: str
    extension: str
    family: InstallerFamily = InstallerFamily.OTHER
    is_primary_candidate: bool = False
    msi: MsiMetadata | None = None
    silent_install_args: str | None = None
    silent_uninstall_args: str | None = None
    log_file_parameter: str | None = None
    source_exe: str | None = None
    extracted_via_dark: bool = False
    notes: list[str] = Field(default_factory=list)


class InstallPlan(BaseModel):
    app_vendor: str = ""
    app_name: str = ""
    app_version: str = ""
    app_arch: str = ""
    app_lang: str = "EN"
    primary_installer: str = ""
    primary_family: InstallerFamily | None = None
    source_exe: str | None = None
    extracted_via_dark: bool = False
    transforms: list[str] = Field(default_factory=list)
    secondary_files: list[str] = Field(default_factory=list)
    install_command: str = ""
    uninstall_command: str = ""
    suggested_uninstall: str | None = None
    log_file_parameter: str | None = None
    footprint_reg_name: str | None = None
    footprint_mst_name: str | None = None
    deploy_script_name: str | None = None
    pre_install_steps: list[str] = Field(default_factory=list)
    post_install_steps: list[str] = Field(default_factory=list)
    post_uninstall_steps: list[str] = Field(default_factory=list)
    product_code: str | None = None
    upgrade_code: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    model: str | None = None  # review model used (e.g. composer-2.5, heuristic)
    reviewer: str | None = None  # cursor | openai | heuristic


class ReviewReport(BaseModel):
    confidence_score: float = 0.0
    findings: list[str] = Field(default_factory=list)
    approved: bool = False
    model: str | None = None  # e.g. composer-2.5, gpt-4o-mini, or "heuristic"
    reviewer: str | None = None  # cursor | openai | heuristic
    raw_response: str | None = None


class PackageArtifacts(BaseModel):
    package_dir: str = ""
    deploy_script: str = ""
    toolkit_dir: str = ""
    files_dir: str = ""
    logs_dir: str = ""
    install_plan_path: str = ""
    review_path: str = ""
    requirements_path: str = ""
    footprint_reg_path: str = ""
    footprint_mst_path: str = ""
