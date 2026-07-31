"""Create MST transforms that embed package footprint registry values."""

from __future__ import annotations

import ctypes
import shutil
import tempfile
import uuid
from ctypes import wintypes
from pathlib import Path

ERROR_SUCCESS = 0
ERROR_NO_MORE_ITEMS = 259
ERROR_MORE_DATA = 234
ERROR_NO_DATA = 232
MSIDBOPEN_READONLY = 0
MSIDBOPEN_TRANSACT = 1
MSIDB_REGISTRY_ROOT_LOCAL_MACHINE = 2
MSIDB_COMPONENT_ATTRIBUTES_REGISTRY_KEYPATH = 4
MSIDB_COMPONENT_ATTRIBUTES_64BIT = 256

MSIHANDLE = wintypes.DWORD


class MsiTransformError(RuntimeError):
    pass


class Win32MsiTransformBuilder:
    """Build an MST that adds HKLM\\SOFTWARE\\Package_Footprint registry value.

    32-bit MSIs use a 32-bit component (no 64-bit flag) so Windows Installer
    writes under the 32-bit registry view (Wow6432Node on 64-bit Windows).
    64-bit MSIs mark the component 64-bit so the value lands in native HKLM\\SOFTWARE.
    """

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
        m.MsiDatabaseCommit.argtypes = [MSIHANDLE]
        m.MsiDatabaseCommit.restype = wintypes.UINT
        m.MsiDatabaseGenerateTransformW.argtypes = [
            MSIHANDLE,
            MSIHANDLE,
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.c_int,
        ]
        m.MsiDatabaseGenerateTransformW.restype = wintypes.UINT
        m.MsiCreateTransformSummaryInfoW.argtypes = [
            MSIHANDLE,
            MSIHANDLE,
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.c_int,
        ]
        m.MsiCreateTransformSummaryInfoW.restype = wintypes.UINT
        m.MsiCloseHandle.argtypes = [MSIHANDLE]
        m.MsiCloseHandle.restype = wintypes.UINT

    def create_footprint_mst(
        self,
        msi_path: str | Path,
        output_mst: str | Path,
        *,
        vendor: str,
        app_name: str,
        footprint_value: str = "1.0.0",
        architecture: str | None = None,
    ) -> Path:
        """Create an MST adding Package_Footprint registry (FootPrintTemplate.reg semantics).

        Registry name is Vendor+AppName; value is the package version (%Version%).
        For 32-bit MSIs (`architecture` x86 / Intel), the footprint component is
        32-bit so Windows Installer writes to the 32-bit registry view
        (Wow6432Node on 64-bit Windows). Do not embed Wow6432Node in the key path.
        """
        msi = Path(msi_path).resolve()
        mst = Path(output_mst).resolve()
        if not msi.is_file():
            raise FileNotFoundError(f"MSI not found: {msi}")
        mst.parent.mkdir(parents=True, exist_ok=True)

        value_name = f"{vendor}{app_name}".replace('"', "").replace("'", "")
        if not value_name:
            value_name = "PackageFootprint"

        component = "pkgai_Footprint"
        registry_id = "pkgai_FootprintReg"
        component_guid = "{" + str(uuid.uuid4()).upper() + "}"
        reg_key = r"SOFTWARE\Package_Footprint"
        component_attrs = _footprint_component_attributes(architecture)

        with tempfile.TemporaryDirectory(prefix="pkgai_mst_") as tmp:
            temp_msi = Path(tmp) / msi.name
            shutil.copy2(msi, temp_msi)

            h_orig = self._open(msi, MSIDBOPEN_READONLY)
            h_edit = self._open(temp_msi, MSIDBOPEN_TRANSACT)
            try:
                feature = self._first_feature(h_edit)
                if not feature:
                    raise MsiTransformError(
                        "MSI has no Feature rows to attach footprint component."
                    )

                self._exec_sql(
                    h_edit,
                    "INSERT INTO `Component` (`Component`,`ComponentId`,`Directory_`,"
                    "`Attributes`,`Condition`,`KeyPath`) "
                    f"VALUES ('{component}','{component_guid}','TARGETDIR',"
                    f"{component_attrs},'',"
                    f"'{registry_id}')",
                )
                self._exec_sql(
                    h_edit,
                    "INSERT INTO `Registry` (`Registry`,`Root`,`Key`,`Name`,`Value`,`Component_`) "
                    f"VALUES ('{registry_id}',{MSIDB_REGISTRY_ROOT_LOCAL_MACHINE},"
                    f"'{self._sql_escape(reg_key)}','{self._sql_escape(value_name)}',"
                    f"'{self._sql_escape(footprint_value)}','{component}')",
                )
                self._exec_sql(
                    h_edit,
                    "INSERT INTO `FeatureComponents` (`Feature_`,`Component_`) "
                    f"VALUES ('{self._sql_escape(feature)}','{component}')",
                )

                status = self._msi.MsiDatabaseCommit(h_edit)
                if status != ERROR_SUCCESS:
                    raise MsiTransformError(f"MsiDatabaseCommit failed ({status})")

                if mst.exists():
                    mst.unlink()
                status = self._msi.MsiDatabaseGenerateTransformW(
                    h_edit, h_orig, str(mst), 0, 0
                )
                if status not in (ERROR_SUCCESS, ERROR_NO_DATA) and not mst.is_file():
                    raise MsiTransformError(
                        f"MsiDatabaseGenerateTransform failed ({status})"
                    )
                if mst.is_file():
                    self._msi.MsiCreateTransformSummaryInfoW(
                        h_edit, h_orig, str(mst), 0, 0
                    )
            finally:
                self._msi.MsiCloseHandle(h_edit)
                self._msi.MsiCloseHandle(h_orig)

        if not mst.is_file():
            raise MsiTransformError(f"MST was not created: {mst}")
        return mst

    def _open(self, path: Path, mode: int) -> MSIHANDLE:
        hdb = MSIHANDLE()
        persist = ctypes.cast(mode, wintypes.LPCWSTR)
        status = self._msi.MsiOpenDatabaseW(str(path), persist, ctypes.byref(hdb))
        if status != ERROR_SUCCESS:
            raise MsiTransformError(f"MsiOpenDatabase failed ({status}) for {path}")
        return hdb

    def _exec_sql(self, hdb: MSIHANDLE, sql: str) -> None:
        hview = MSIHANDLE()
        status = self._msi.MsiDatabaseOpenViewW(hdb, sql, ctypes.byref(hview))
        if status != ERROR_SUCCESS:
            raise MsiTransformError(f"OpenView failed ({status}): {sql[:120]}")
        try:
            status = self._msi.MsiViewExecute(hview, 0)
            if status != ERROR_SUCCESS:
                raise MsiTransformError(f"ViewExecute failed ({status}): {sql[:120]}")
        finally:
            self._msi.MsiCloseHandle(hview)

    def _first_feature(self, hdb: MSIHANDLE) -> str | None:
        for sql in (
            "SELECT `Feature` FROM `Feature` WHERE `Level` > 0",
            "SELECT `Feature` FROM `Feature`",
        ):
            hview = MSIHANDLE()
            status = self._msi.MsiDatabaseOpenViewW(hdb, sql, ctypes.byref(hview))
            if status != ERROR_SUCCESS:
                continue
            try:
                if self._msi.MsiViewExecute(hview, 0) != ERROR_SUCCESS:
                    continue
                hrec = MSIHANDLE()
                status = self._msi.MsiViewFetch(hview, ctypes.byref(hrec))
                if status != ERROR_SUCCESS:
                    continue
                try:
                    value = self._record_string(hrec, 1)
                    if value:
                        return value
                finally:
                    self._msi.MsiCloseHandle(hrec)
            finally:
                self._msi.MsiCloseHandle(hview)
        return None

    def _record_string(self, hrec: MSIHANDLE, field: int) -> str:
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

    @staticmethod
    def _sql_escape(value: str) -> str:
        return value.replace("'", "''")


def _footprint_component_attributes(architecture: str | None) -> int:
    """Registry keypath component; add 64-bit flag only for x64/ARM64 MSIs."""
    attrs = MSIDB_COMPONENT_ATTRIBUTES_REGISTRY_KEYPATH
    arch = (architecture or "").strip().lower()
    if arch in {"x64", "amd64", "arm64"}:
        attrs |= MSIDB_COMPONENT_ATTRIBUTES_64BIT
    return attrs


def create_footprint_mst(
    msi_path: str | Path,
    output_mst: str | Path,
    *,
    vendor: str,
    app_name: str,
    footprint_value: str = "1.0.0",
    architecture: str | None = None,
) -> Path:
    return Win32MsiTransformBuilder().create_footprint_mst(
        msi_path,
        output_mst,
        vendor=vendor,
        app_name=app_name,
        footprint_value=footprint_value,
        architecture=architecture,
    )
