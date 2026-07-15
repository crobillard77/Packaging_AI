from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from packaging_ai.models import VulnerabilityFinding


def _resolve_cve_bin_tool() -> list[str] | None:
    """Locate cve-bin-tool even when the venv Scripts dir is not on PATH."""
    found = shutil.which("cve-bin-tool")
    if found:
        return [found]

    scripts_dir = Path(sys.executable).resolve().parent
    for name in ("cve-bin-tool.exe", "cve-bin-tool", "cve_bin_tool.exe", "cve_bin_tool"):
        candidate = scripts_dir / name
        if candidate.is_file():
            return [str(candidate)]

    # Module fallback (same interpreter as Packaging AI)
    try:
        import cve_bin_tool  # noqa: F401

        return [sys.executable, "-m", "cve_bin_tool"]
    except ImportError:
        return None


def lookup_cve_bin_tool(paths: list[str]) -> tuple[list[VulnerabilityFinding], list[str]]:
    """Optional deep binary scan via Intel cve-bin-tool if installed."""
    cmd_prefix = _resolve_cve_bin_tool()
    if not cmd_prefix:
        return [], []

    findings: dict[str, VulnerabilityFinding] = {}
    errors: list[str] = []
    for path in paths:
        file_path = Path(path)
        if not file_path.is_file():
            continue
        try:
            proc = subprocess.run(
                [
                    *cmd_prefix,
                    "--input",
                    str(file_path),
                    "--format",
                    "json",
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"cve-bin-tool failed ({file_path.name}): {exc}")
            continue

        raw = (proc.stdout or "").strip()
        if not raw:
            if proc.returncode not in {0, 1}:
                errors.append(
                    f"cve-bin-tool returned {proc.returncode} for {file_path.name}: "
                    f"{(proc.stderr or '')[:200]}"
                )
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Some versions print a path to a report file
            errors.append(f"cve-bin-tool JSON parse failed for {file_path.name}")
            continue

        rows = data if isinstance(data, list) else data.get("results") or data.get("vulnerabilities") or []
        if isinstance(data, dict) and not rows:
            # nested map product -> cves
            for _product, cves in data.items():
                if isinstance(cves, list):
                    rows.extend(cves)

        for row in rows:
            if not isinstance(row, dict):
                continue
            cve_id = str(row.get("cve_number") or row.get("cve_id") or row.get("id") or "").upper()
            if not cve_id.startswith("CVE-"):
                continue
            severity = str(row.get("severity") or row.get("cvss_severity") or "UNKNOWN").upper()
            score = row.get("score") or row.get("cvss")
            try:
                score_f = float(score) if score is not None else None
            except (TypeError, ValueError):
                score_f = None
            findings[cve_id] = VulnerabilityFinding(
                cve_id=cve_id,
                severity=severity if severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"} else "UNKNOWN",
                cvss_score=score_f,
                summary=str(row.get("remarks") or row.get("description") or "")[:500],
                source="cve-bin-tool",
                matched_cpe=str(row.get("cpe") or "") or None,
                references=[],
            )

    return list(findings.values()), errors
