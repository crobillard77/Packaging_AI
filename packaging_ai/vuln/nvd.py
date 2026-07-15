from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from packaging_ai.config import NVD_API_KEY
from packaging_ai.models import VulnerabilityFinding
from packaging_ai.vuln.matching import (
    extract_cvss,
    keyword_queries,
    normalize_token,
    version_in_range,
)

NVD_CVE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_LAST_NVD_CALL = 0.0


def lookup_nvd(
    vendor: str,
    product: str,
    version: str,
    cpes: list[str],
) -> tuple[list[VulnerabilityFinding], list[str]]:
    """Query NVD by keyword + virtual CPE match; keep version-affected findings."""
    findings: dict[str, VulnerabilityFinding] = {}
    errors: list[str] = []

    # 1) Keyword search (most reliable for desktop apps like Notepad++)
    for query in keyword_queries(vendor, product):
        try:
            payload = _nvd_get(
                {
                    "keywordSearch": query,
                    "resultsPerPage": "100",
                }
            )
            for item in payload.get("vulnerabilities") or []:
                finding = _finding_from_nvd(
                    item,
                    version,
                    product_hint=product,
                    vendor_hint=vendor,
                )
                if finding:
                    findings[finding.cve_id] = _merge(findings.get(finding.cve_id), finding)
        except Exception as exc:
            errors.append(f"NVD keyword query failed ({query}): {exc}")

    # 2) virtualMatchString on vendor:product (no version) — skip invalid CPEs quietly
    seen_virtual: set[str] = set()
    for cpe in cpes:
        parts = cpe.split(":")
        if len(parts) < 5:
            continue
        virtual = f"cpe:2.3:a:{parts[3]}:{parts[4]}"
        if virtual in seen_virtual:
            continue
        seen_virtual.add(virtual)
        # NVD rejects some characters in CPE product (e.g. literal ++); prefer normalized
        if "++" in virtual:
            continue
        try:
            payload = _nvd_get(
                {
                    "virtualMatchString": virtual,
                    "resultsPerPage": "100",
                }
            )
            for item in payload.get("vulnerabilities") or []:
                finding = _finding_from_nvd(
                    item,
                    version,
                    product_hint=product,
                    vendor_hint=vendor,
                    preferred_cpe=virtual,
                )
                if finding:
                    findings[finding.cve_id] = _merge(findings.get(finding.cve_id), finding)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue  # CPE not in NVD dictionary
            errors.append(f"NVD CPE match failed ({virtual}): {exc}")
        except Exception as exc:
            errors.append(f"NVD CPE match failed ({virtual}): {exc}")

    return list(findings.values()), errors


def _nvd_get(params: dict[str, str]) -> dict[str, Any]:
    global _LAST_NVD_CALL
    gap = 0.6 if NVD_API_KEY else 6.5
    elapsed = time.monotonic() - _LAST_NVD_CALL
    if elapsed < gap:
        time.sleep(gap - elapsed)

    query = urllib.parse.urlencode(params)
    headers = {
        "User-Agent": "PackagingAI/1.0 (vulnerability-assist)",
        "Accept": "application/json",
    }
    if NVD_API_KEY:
        headers["apiKey"] = NVD_API_KEY
    req = urllib.request.Request(
        f"{NVD_CVE_URL}?{query}",
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    finally:
        _LAST_NVD_CALL = time.monotonic()

    return json.loads(raw)


def _finding_from_nvd(
    wrapper: dict[str, Any],
    version: str,
    *,
    preferred_cpe: str | None = None,
    product_hint: str | None = None,
    vendor_hint: str | None = None,
) -> VulnerabilityFinding | None:
    cve = wrapper.get("cve") or {}
    cve_id = str(cve.get("id") or "").upper()
    if not cve_id.startswith("CVE-"):
        return None

    matched_cpe, affected = _version_affected(
        cve,
        version,
        product_hint=product_hint,
        vendor_hint=vendor_hint,
        preferred_cpe=preferred_cpe,
    )
    if not affected:
        return None

    severity, score = extract_cvss(cve.get("metrics"))
    summary = _english_description(cve)
    refs = [
        str(r.get("url"))
        for r in (cve.get("references") or [])
        if r.get("url")
    ][:8]
    return VulnerabilityFinding(
        cve_id=cve_id,
        severity=severity,
        cvss_score=score,
        summary=summary[:500],
        source="nvd",
        matched_cpe=matched_cpe or preferred_cpe,
        published=str(cve.get("published") or "") or None,
        references=refs,
    )


def _english_description(cve: dict[str, Any]) -> str:
    for row in cve.get("descriptions") or []:
        if str(row.get("lang") or "").lower() == "en":
            return str(row.get("value") or "").strip()
    rows = cve.get("descriptions") or []
    return str(rows[0].get("value") or "").strip() if rows else ""


def _version_affected(
    cve: dict[str, Any],
    version: str,
    *,
    product_hint: str | None,
    vendor_hint: str | None,
    preferred_cpe: str | None,
) -> tuple[str | None, bool]:
    """Return (matched_cpe, is_affected) using NVD configurations when present."""
    configs = cve.get("configurations") or []
    product_tok = normalize_token(product_hint or "")
    vendor_tok = normalize_token(vendor_hint or "")
    relevant_matches = 0
    matched: str | None = None

    for config in configs:
        for node in config.get("nodes") or []:
            for match in node.get("cpeMatch") or []:
                criteria = str(match.get("criteria") or match.get("cpe23Uri") or "")
                if not criteria.startswith("cpe:2.3:"):
                    continue
                if not _cpe_product_relevant(criteria, product_tok, vendor_tok, preferred_cpe):
                    continue
                relevant_matches += 1
                if match.get("vulnerable") is False:
                    continue
                parts = criteria.split(":")
                cpe_ver = parts[5] if len(parts) > 5 else "*"
                start_including = match.get("versionStartIncluding")
                start_excluding = match.get("versionStartExcluding")
                end_including = match.get("versionEndIncluding")
                end_excluding = match.get("versionEndExcluding")
                has_range = any(
                    [
                        start_including,
                        start_excluding,
                        end_including,
                        end_excluding,
                    ]
                )
                # Wildcard CPE with no range is too broad — do not claim this version is affected
                if cpe_ver in {"*", "-"} and not has_range:
                    matched = matched or criteria
                    continue
                if version_in_range(
                    version,
                    exact=None if cpe_ver in {"*", "-"} else cpe_ver,
                    start_including=start_including,
                    start_excluding=start_excluding,
                    end_including=end_including,
                    end_excluding=end_excluding,
                ):
                    return criteria, True
                matched = matched or criteria

    # No relevant CPE nodes: fall back to description/product mention + no version claim
    if relevant_matches == 0 and product_hint:
        summary = _english_description(cve).lower()
        prod = (product_hint or "").lower()
        if prod and prod in summary and version and version in summary:
            return None, True
    return matched, False


def _cpe_product_relevant(
    criteria: str,
    product_tok: str,
    vendor_tok: str,
    preferred_cpe: str | None,
) -> bool:
    parts = criteria.lower().split(":")
    if len(parts) < 5:
        return False
    cpe_vendor, cpe_product = parts[3], parts[4]
    if preferred_cpe:
        pref = preferred_cpe.lower().split(":")
        if len(pref) > 4 and pref[3] == cpe_vendor and pref[4] == cpe_product:
            return True
    cpe_prod_tok = normalize_token(cpe_product)
    if product_tok and product_tok in cpe_prod_tok:
        return True
    if product_tok and cpe_prod_tok in product_tok:
        return True
    if "notepad" in product_tok and "notepad" in cpe_product:
        return True
    if "wix" in product_tok and "wix" in cpe_product:
        return True
    if vendor_tok and vendor_tok in cpe_vendor and product_tok and product_tok[:4] in cpe_prod_tok:
        return True
    return False


def _merge(
    existing: VulnerabilityFinding | None,
    new: VulnerabilityFinding,
) -> VulnerabilityFinding:
    if existing is None:
        return new
    if (new.cvss_score or 0) >= (existing.cvss_score or 0):
        return new.model_copy(
            update={
                "references": list(dict.fromkeys(existing.references + new.references))[:8],
            }
        )
    return existing.model_copy(
        update={
            "references": list(dict.fromkeys(existing.references + new.references))[:8],
        }
    )
