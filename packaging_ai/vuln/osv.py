from __future__ import annotations

import json
import urllib.request
from typing import Any

from packaging_ai.models import VulnerabilityFinding
from packaging_ai.vuln.matching import version_cmp

OSV_QUERY_URL = "https://api.osv.dev/v1/query"


def lookup_osv(product: str, version: str) -> tuple[list[VulnerabilityFinding], list[str]]:
    """Query OSV for the product/version (best-effort for desktop apps)."""
    errors: list[str] = []
    findings: dict[str, VulnerabilityFinding] = {}
    for name in _osv_names(product):
        query: dict[str, Any] = {"version": version, "package": {"name": name}}
        try:
            payload = _post_json(OSV_QUERY_URL, query)
        except Exception as exc:
            errors.append(f"OSV query failed ({name}): {exc}")
            continue
        for vuln in payload.get("vulns") or []:
            finding = _from_osv(vuln, version)
            if finding:
                findings[finding.cve_id] = finding
    return list(findings.values()), errors


def _osv_names(product: str) -> list[str]:
    raw = (product or "").strip()
    names = [raw]
    lower = raw.lower()
    if "notepad" in lower:
        names.extend(["notepad-plus-plus", "DonHo/notepad-plus-plus"])
    if "winscp" in lower:
        names.extend(["winscp", "winscp/winscp"])
    if "putty" in lower:
        names.extend(["putty"])
    if "wix" in lower:
        names.extend(["wix", "wixtoolset/wix3"])
    return list(dict.fromkeys(n for n in names if n and "++" not in n))[:6]


def _post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "PackagingAI/1.0 (vulnerability-assist)",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _from_osv(vuln: dict[str, Any], version: str) -> VulnerabilityFinding | None:
    aliases = [str(a) for a in (vuln.get("aliases") or [])]
    cve_id = next((a for a in aliases if a.upper().startswith("CVE-")), None)
    if not cve_id:
        vid = str(vuln.get("id") or "")
        if vid.upper().startswith("CVE-"):
            cve_id = vid
        else:
            cve_id = vid
    if not cve_id:
        return None

    if not _osv_affects_version(vuln, version):
        return None

    db = vuln.get("database_specific") or {}
    severity = str(db.get("severity") or "UNKNOWN").upper()
    if severity not in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
        severity = "UNKNOWN"

    summary = str(vuln.get("summary") or vuln.get("details") or "").strip()
    refs = [str(r.get("url")) for r in (vuln.get("references") or []) if r.get("url")][:8]
    return VulnerabilityFinding(
        cve_id=cve_id.upper() if cve_id.upper().startswith("CVE-") else cve_id,
        severity=severity,
        cvss_score=None,
        summary=summary[:500],
        source="osv",
        published=str(vuln.get("published") or "") or None,
        references=refs,
    )


def _osv_affects_version(vuln: dict[str, Any], version: str) -> bool:
    affected = vuln.get("affected") or []
    if not affected:
        return True
    for item in affected:
        for rng in item.get("ranges") or []:
            events = rng.get("events") or []
            introduced = "0"
            fixed = None
            for ev in events:
                if "introduced" in ev:
                    introduced = str(ev.get("introduced") or "0")
                if "fixed" in ev:
                    fixed = str(ev.get("fixed"))
            if version_cmp(version, introduced) < 0:
                continue
            if fixed and version_cmp(version, fixed) >= 0:
                continue
            return True
        versions = item.get("versions") or []
        if versions and version in versions:
            return True
        if not (item.get("ranges") or versions):
            return True
    return False
