from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from packaging_ai.models import MsiMetadata
from packaging_ai.msi import MsiEditNotSupportedError, MsiLibrary

ERROR_SUCCESS = 0
ERROR_NO_MORE_ITEMS = 259
ERROR_MORE_DATA = 234
MSIDBOPEN_READONLY = 0

# MSIHANDLE is ULONG
MSIHANDLE = wintypes.DWORD

# Summary Information property IDs
PID_TEMPLATE = 7  # platform;language(s) — e.g. "x64;1033", "Intel;1033"
VT_LPSTR = 30


class Win32MsiReader:
    """v1.0 read-only MSI access via Windows Installer API (msi.dll)."""

    _PROPERTY_KEYS = (
        "ProductName",
        "ProductVersion",
        "Manufacturer",
        "ProductCode",
        "UpgradeCode",
        "Platform",
    )

    def __init__(self) -> None:
        self._msi = ctypes.WinDLL("msi")
        self._configure_api()

    def _configure_api(self) -> None:
        m = self._msi
        m.MsiOpenDatabaseW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.POINTER(MSIHANDLE),
        ]
        m.MsiOpenDatabaseW.restype = wintypes.UINT
        m.MsiDatabaseOpenViewW.argtypes = [
            MSIHANDLE,
            wintypes.LPCWSTR,
            ctypes.POINTER(MSIHANDLE),
        ]
        m.MsiDatabaseOpenViewW.restype = wintypes.UINT
        m.MsiViewExecute.argtypes = [MSIHANDLE, MSIHANDLE]
        m.MsiViewExecute.restype = wintypes.UINT
        m.MsiViewFetch.argtypes = [MSIHANDLE, ctypes.POINTER(MSIHANDLE)]
        m.MsiViewFetch.restype = wintypes.UINT
        m.MsiRecordGetStringW.argtypes = [
            MSIHANDLE,
            wintypes.UINT,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        m.MsiRecordGetStringW.restype = wintypes.UINT
        m.MsiCloseHandle.argtypes = [MSIHANDLE]
        m.MsiCloseHandle.restype = wintypes.UINT
        m.MsiGetSummaryInformationW.argtypes = [
            MSIHANDLE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.POINTER(MSIHANDLE),
        ]
        m.MsiGetSummaryInformationW.restype = wintypes.UINT
        m.MsiSummaryInfoGetPropertyW.argtypes = [
            MSIHANDLE,
            wintypes.UINT,
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_void_p,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        m.MsiSummaryInfoGetPropertyW.restype = wintypes.UINT

    def read_metadata(self, msi_path: str) -> MsiMetadata:
        path = str(Path(msi_path).resolve())
        hdb = MSIHANDLE()
        persist = ctypes.cast(MSIDBOPEN_READONLY, wintypes.LPCWSTR)
        status = self._msi.MsiOpenDatabaseW(path, persist, ctypes.byref(hdb))
        if status != ERROR_SUCCESS:
            raise RuntimeError(f"MsiOpenDatabase failed ({status}) for {path}")

        try:
            properties = self._query_properties(hdb)
            template = self._read_summary_template(hdb)
        finally:
            self._msi.MsiCloseHandle(hdb)

        platform_raw = _platform_from_sources(properties, template)
        architecture = normalize_msi_architecture(platform_raw)

        return MsiMetadata(
            product_name=properties.get("ProductName"),
            product_version=properties.get("ProductVersion"),
            manufacturer=properties.get("Manufacturer"),
            product_code=properties.get("ProductCode"),
            upgrade_code=properties.get("UpgradeCode"),
            platform=platform_raw,
            architecture=architecture,
            properties=properties,
        )

    def _read_summary_template(self, hdb: int) -> str | None:
        """Read Summary Information PID_TEMPLATE (platform;language)."""
        hsum = MSIHANDLE()
        status = self._msi.MsiGetSummaryInformationW(hdb, None, 0, ctypes.byref(hsum))
        if status != ERROR_SUCCESS:
            return None
        try:
            data_type = wintypes.UINT(0)
            int_value = ctypes.c_int(0)
            size = wintypes.DWORD(0)
            status = self._msi.MsiSummaryInfoGetPropertyW(
                hsum,
                PID_TEMPLATE,
                ctypes.byref(data_type),
                ctypes.byref(int_value),
                None,
                None,
                ctypes.byref(size),
            )
            if status not in (ERROR_SUCCESS, ERROR_MORE_DATA):
                return None
            if data_type.value != VT_LPSTR:
                return None
            buf = ctypes.create_unicode_buffer(size.value + 1)
            cch = wintypes.DWORD(size.value + 1)
            status = self._msi.MsiSummaryInfoGetPropertyW(
                hsum,
                PID_TEMPLATE,
                ctypes.byref(data_type),
                ctypes.byref(int_value),
                None,
                buf,
                ctypes.byref(cch),
            )
            if status != ERROR_SUCCESS:
                return None
            return buf.value or None
        finally:
            self._msi.MsiCloseHandle(hsum)

    def _query_properties(self, hdb: int) -> dict[str, str]:
        properties: dict[str, str] = {}
        hview = MSIHANDLE()
        sql = "SELECT `Property`, `Value` FROM `Property`"
        status = self._msi.MsiDatabaseOpenViewW(hdb, sql, ctypes.byref(hview))
        if status != ERROR_SUCCESS:
            for key in self._PROPERTY_KEYS:
                value = self._get_property(hdb, key)
                if value:
                    properties[key] = value
            return properties

        try:
            status = self._msi.MsiViewExecute(hview, 0)
            if status != ERROR_SUCCESS:
                return properties
            while True:
                hrec = MSIHANDLE()
                status = self._msi.MsiViewFetch(hview, ctypes.byref(hrec))
                if status == ERROR_NO_MORE_ITEMS:
                    break
                if status != ERROR_SUCCESS:
                    break
                try:
                    prop = self._record_string(hrec, 1)
                    val = self._record_string(hrec, 2)
                    if prop:
                        properties[prop] = val
                finally:
                    self._msi.MsiCloseHandle(hrec)
        finally:
            self._msi.MsiCloseHandle(hview)
        return properties

    def _get_property(self, hdb: int, name: str) -> str | None:
        hview = MSIHANDLE()
        sql = f"SELECT `Value` FROM `Property` WHERE `Property`='{name}'"
        status = self._msi.MsiDatabaseOpenViewW(hdb, sql, ctypes.byref(hview))
        if status != ERROR_SUCCESS:
            return None
        try:
            if self._msi.MsiViewExecute(hview, 0) != ERROR_SUCCESS:
                return None
            hrec = MSIHANDLE()
            status = self._msi.MsiViewFetch(hview, ctypes.byref(hrec))
            if status != ERROR_SUCCESS:
                return None
            try:
                return self._record_string(hrec, 1) or None
            finally:
                self._msi.MsiCloseHandle(hrec)
        finally:
            self._msi.MsiCloseHandle(hview)

    def _record_string(self, hrec: int, field: int) -> str:
        size = wintypes.DWORD(0)
        status = self._msi.MsiRecordGetStringW(hrec, field, None, ctypes.byref(size))
        if status not in (ERROR_SUCCESS, ERROR_MORE_DATA):
            return ""
        buf = ctypes.create_unicode_buffer(size.value + 1)
        cch = wintypes.DWORD(size.value + 1)
        status = self._msi.MsiRecordGetStringW(hrec, field, buf, ctypes.byref(cch))
        if status != ERROR_SUCCESS:
            return ""
        return buf.value

    def edit_msi(self, msi_path: str, changes: dict) -> None:
        raise MsiEditNotSupportedError(
            "MSI edit is out of scope for v1.0; use the future MSI library (Phase 2)."
        )

    def create_msi(self, spec: dict, output_path: str) -> None:
        raise MsiEditNotSupportedError(
            "MSI create is out of scope for v1.0; use the future MSI library (Phase 2)."
        )


def _platform_from_sources(properties: dict[str, str], template: str | None) -> str | None:
    """Prefer Property.Platform; else Summary Information Template platform token."""
    prop = (properties.get("Platform") or "").strip()
    if prop:
        return prop
    if not template:
        return None
    # Template format: "platform;lang[,lang...]" — platform may be empty (Intel default)
    platform = template.split(";", 1)[0].strip()
    return platform or "Intel"


def normalize_msi_architecture(platform: str | None) -> str | None:
    """Map MSI platform tokens to PSADT $appArch values."""
    if platform is None:
        return None
    token = platform.strip().lower()
    if not token:
        return "x86"
    if token in {"x64", "intel64", "amd64"}:
        return "x64"
    if token in {"intel", "x86", "i386"}:
        return "x86"
    if token in {"arm64", "aarch64"}:
        return "ARM64"
    if token in {"arm", "arm32"}:
        return "ARM"
    # Multi-platform or unknown — leave unset rather than guess wrong
    if "," in token or ";" in token:
        parts = [normalize_msi_architecture(p) for p in token.replace(";", ",").split(",")]
        parts = [p for p in parts if p]
        if len(set(parts)) == 1:
            return parts[0]
        return None
    return None


def get_msi_library() -> MsiLibrary:
    return Win32MsiReader()
