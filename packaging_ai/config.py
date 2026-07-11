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

INSTALLER_EXTENSIONS = {".msi", ".mst", ".exe", ".msp", ".msix", ".appx"}
PRIMARY_INSTALLER_EXTENSIONS = {".msi", ".exe"}
