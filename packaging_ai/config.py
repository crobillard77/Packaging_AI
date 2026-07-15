from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "packaging_ai.config.json"


def _resolve_path(value: str | Path, *, base: Path = PROJECT_ROOT) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _load_json_config() -> dict[str, Any]:
    """Load packaging_ai.config.json (or PACKAGING_AI_CONFIG override)."""
    override = (os.environ.get("PACKAGING_AI_CONFIG") or "").strip()
    config_path = Path(override) if override else DEFAULT_CONFIG_FILE
    if not config_path.is_file():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


_CFG = _load_json_config()

PSADT_TEMPLATE_DIR = _resolve_path(_CFG.get("templates_dir", "Templates"))
PSADT_SCRIPT_TEMPLATE = PSADT_TEMPLATE_DIR / "Deploy-Application.ps1"
PSADT_TOOLKIT_DIR = PSADT_TEMPLATE_DIR / "AppDeployToolkit"
PSADT_REQUIREMENTS_FILE = PSADT_TEMPLATE_DIR / "PSADT_Requirements.md"
FOOTPRINT_REG_TEMPLATE = PSADT_TEMPLATE_DIR / "FootPrint" / "FootPrintTemplate.reg"

DARK_EXE = _resolve_path(_CFG.get("dark_exe", "Tools/WIX/dark.exe"))
DARK_CACHE_DIR = _resolve_path(_CFG.get("dark_cache_dir", ".cache/dark"))

CONFIDENCE_THRESHOLD = float(_CFG.get("confidence_threshold", 0.75))
DEFAULT_OUTPUT_DIR = _resolve_path(_CFG.get("output_dir", "output"))

# Review models (env overrides config):
#   PACKAGING_AI_MODEL       → Cursor review model
#   PACKAGING_AI_OPENAI_MODEL → OpenAI fallback model
DEFAULT_REVIEW_MODEL = str(
    os.environ.get("PACKAGING_AI_MODEL")
    or _CFG.get("model")
    or "composer-2.5"
).strip()
DEFAULT_OPENAI_MODEL = str(
    os.environ.get("PACKAGING_AI_OPENAI_MODEL")
    or _CFG.get("openai_model")
    or "gpt-4o-mini"
).strip()
DEFAULT_OPENAI_TEMPERATURE = float(
    os.environ.get("PACKAGING_AI_OPENAI_TEMPERATURE")
    or _CFG.get("openai_temperature")
    or 0
)

# Vulnerability scan (NVD/OSV/Authenticode/hash; optional cve-bin-tool)
VULN_SCAN_ENABLED = str(
    os.environ.get("PACKAGING_AI_VULN_SCAN")
    if os.environ.get("PACKAGING_AI_VULN_SCAN") is not None
    else _CFG.get("vuln_scan", True)
).strip().lower() not in {"0", "false", "no", "off"}
VULN_BLOCK_ON_CRITICAL = str(
    os.environ.get("PACKAGING_AI_VULN_BLOCK_ON_CRITICAL")
    if os.environ.get("PACKAGING_AI_VULN_BLOCK_ON_CRITICAL") is not None
    else _CFG.get("vuln_block_on_critical", False)
).strip().lower() in {"1", "true", "yes", "on"}
VULN_MIN_SEVERITY = str(
    os.environ.get("PACKAGING_AI_VULN_MIN_SEVERITY")
    or _CFG.get("vuln_min_severity")
    or "MEDIUM"
).strip().upper()
NVD_API_KEY = (
    os.environ.get("NVD_API_KEY") or str(_CFG.get("nvd_api_key") or "")
).strip()

# Logging
LOG_LEVEL = str(
    os.environ.get("PACKAGING_AI_LOG_LEVEL")
    or _CFG.get("log_level")
    or "INFO"
).strip().upper()
_LOG_FILE_RAW = (
    os.environ.get("PACKAGING_AI_LOG_FILE")
    if os.environ.get("PACKAGING_AI_LOG_FILE") is not None
    else _CFG.get("log_file", "logs/packaging_ai.log")
)
LOG_FILE: Path | None
if _LOG_FILE_RAW is None or str(_LOG_FILE_RAW).strip() in {"", "null", "none", "false", "off"}:
    LOG_FILE = None
else:
    LOG_FILE = _resolve_path(str(_LOG_FILE_RAW).strip())

INSTALLER_EXTENSIONS = {".msi", ".mst", ".exe", ".msp", ".msix", ".appx"}
PRIMARY_INSTALLER_EXTENSIONS = {".msi", ".exe"}

# HTTP API (Phase 3)
API_HOST = str(
    os.environ.get("PACKAGING_AI_API_HOST") or _CFG.get("api_host") or "127.0.0.1"
).strip()
API_PORT = int(os.environ.get("PACKAGING_AI_API_PORT") or _CFG.get("api_port") or 8000)
_API_KEYS_RAW = (
    os.environ.get("PACKAGING_AI_API_KEYS")
    if os.environ.get("PACKAGING_AI_API_KEYS") is not None
    else _CFG.get("api_keys", "")
)
API_KEYS: list[str] = [
    k.strip()
    for k in str(_API_KEYS_RAW or "").replace(";", ",").split(",")
    if k.strip()
]
SQL_CONNECTION = (
    os.environ.get("PACKAGING_AI_SQL_CONNECTION")
    or str(_CFG.get("sql_connection") or "")
).strip()
JOB_STORE = str(
    os.environ.get("PACKAGING_AI_JOB_STORE") or _CFG.get("job_store") or "sql"
).strip().lower()
# job_store: "sql" (default, requires SQL_CONNECTION) | "memory" (dev/smoke)
