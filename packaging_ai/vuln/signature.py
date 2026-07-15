from __future__ import annotations

import json
import subprocess
from pathlib import Path

from packaging_ai.models import SignatureInfo


def check_authenticode(path: str | Path) -> SignatureInfo:
    """Verify Authenticode signature via PowerShell Get-AuthenticodeSignature."""
    file_path = Path(path).resolve()
    if not file_path.is_file():
        return SignatureInfo(path=str(file_path), status="Missing", is_valid=False)

    # Single-quoted PowerShell literal path (escape embedded single quotes)
    ps_path = str(file_path).replace("'", "''")
    script = (
        f"$s = Get-AuthenticodeSignature -LiteralPath '{ps_path}'; "
        "[pscustomobject]@{"
        "Status=[string]$s.Status; "
        "Signer=($(if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { $null })); "
        "Timestamp=($(if ($s.TimeStamperCertificate) { $s.TimeStamperCertificate.Subject } else { $null }))"
        "} | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return SignatureInfo(
            path=str(file_path),
            status=f"Error:{exc}",
            is_valid=False,
        )

    raw = (proc.stdout or "").strip()
    if proc.returncode != 0 or not raw:
        err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        return SignatureInfo(path=str(file_path), status=f"Error:{err}", is_valid=False)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return SignatureInfo(path=str(file_path), status="ParseError", is_valid=False)

    status = str(data.get("Status") or "Unknown")
    return SignatureInfo(
        path=str(file_path),
        status=status,
        signer=(str(data["Signer"]) if data.get("Signer") else None),
        timestamp=(str(data["Timestamp"]) if data.get("Timestamp") else None),
        is_valid=status.lower() == "valid",
    )
