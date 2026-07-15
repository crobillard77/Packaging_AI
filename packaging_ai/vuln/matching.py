from __future__ import annotations

import re
from typing import Any


def normalize_token(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("++", "_plus_plus")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in re.split(r"[^\d]+", (version or "").strip()):
        if piece.isdigit():
            parts.append(int(piece))
    return tuple(parts) if parts else (0,)


def version_cmp(a: str, b: str) -> int:
    ta, tb = version_tuple(a), version_tuple(b)
    n = max(len(ta), len(tb))
    ta = ta + (0,) * (n - len(ta))
    tb = tb + (0,) * (n - len(tb))
    if ta < tb:
        return -1
    if ta > tb:
        return 1
    return 0


def version_in_range(
    version: str,
    *,
    start_including: str | None = None,
    start_excluding: str | None = None,
    end_including: str | None = None,
    end_excluding: str | None = None,
    exact: str | None = None,
) -> bool:
    if exact and exact not in {"*", "-", ""}:
        return version_cmp(version, exact) == 0
    if start_including and version_cmp(version, start_including) < 0:
        return False
    if start_excluding and version_cmp(version, start_excluding) <= 0:
        return False
    if end_including and version_cmp(version, end_including) > 0:
        return False
    if end_excluding and version_cmp(version, end_excluding) >= 0:
        return False
    return True


def severity_rank(severity: str) -> int:
    return {
        "CRITICAL": 4,
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1,
        "UNKNOWN": 0,
    }.get((severity or "UNKNOWN").upper(), 0)


def meets_min_severity(severity: str, minimum: str) -> bool:
    return severity_rank(severity) >= severity_rank(minimum)


def candidate_cpes(vendor: str, product: str, version: str) -> list[str]:
    """Build plausible CPE 2.3 URIs for NVD queries."""
    vendors = _vendor_aliases(vendor, product)
    products = _product_aliases(product)
    ver = (version or "*").strip() or "*"
    cpes: list[str] = []
    for v in vendors:
        for p in products:
            cpes.append(f"cpe:2.3:a:{v}:{p}:{ver}:*:*:*:*:*:*:*")
            if ver != "*":
                cpes.append(f"cpe:2.3:a:{v}:{p}:*:*:*:*:*:*:*:*")
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for cpe in cpes:
        if cpe not in seen:
            seen.add(cpe)
            out.append(cpe)
    return out[:12]


def _vendor_aliases(vendor: str, product: str) -> list[str]:
    raw = normalize_token(vendor) or "unknown"
    aliases = [raw]
    # Common NVD CPE vendor spellings
    mapping = {
        "opensource": ["notepad-plus-plus"],
        "don_ho": ["notepad-plus-plus"],
        "notepad": ["notepad-plus-plus"],
        "microsoft": ["microsoft"],
        "net_foundation": ["dotnetfoundation", "microsoft"],
        "dotnet_foundation": ["dotnetfoundation", "microsoft"],
        "winscp": ["winscp"],
        "simon_tatham": ["putty"],
        "putty": ["putty"],
    }
    for key, vals in mapping.items():
        if key in raw or key in normalize_token(product):
            aliases.extend(vals)
    prod = normalize_token(product)
    if prod and prod not in aliases:
        aliases.append(prod)
    return list(dict.fromkeys(aliases))


def _product_aliases(product: str) -> list[str]:
    raw = normalize_token(product) or "unknown"
    aliases = [raw, raw.replace("_", "")]
    if "notepad" in raw:
        aliases.extend(["notepad++", "notepad_plus_plus"])
    if "wix" in raw:
        aliases.extend(["wix", "wix_toolset"])
    if "putty" in raw:
        aliases.append("putty")
    if "winscp" in raw:
        aliases.append("winscp")
    return list(dict.fromkeys(a for a in aliases if a))


def keyword_queries(vendor: str, product: str) -> list[str]:
    queries: list[str] = []
    product = (product or "").strip()
    vendor = (vendor or "").strip()
    if product:
        queries.append(product)
    if vendor and product and vendor.lower() not in {"opensource", "unknown"}:
        queries.append(f"{vendor} {product}")
    # Prefer shorter unique tokens for NVD keyword search
    cleaned = re.sub(r"\s+v?\d[\d\.]*$", "", product, flags=re.I).strip()
    if cleaned and cleaned not in queries:
        queries.append(cleaned)
    return list(dict.fromkeys(q for q in queries if q))[:4]


def extract_cvss(metrics: dict[str, Any] | None) -> tuple[str, float | None]:
    if not metrics:
        return "UNKNOWN", None
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        rows = metrics.get(key) or []
        if not rows:
            continue
        primary = next((r for r in rows if r.get("type") == "Primary"), rows[0])
        data = primary.get("cvssData") or {}
        severity = str(data.get("baseSeverity") or primary.get("baseSeverity") or "UNKNOWN").upper()
        score = data.get("baseScore")
        try:
            return severity, float(score) if score is not None else None
        except (TypeError, ValueError):
            return severity, None
    return "UNKNOWN", None
