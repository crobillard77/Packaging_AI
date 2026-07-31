# PSADT Script Requirements

Edit this file to define how generated PSADT packages must look.
Packaging AI loads it from `Templates/PSADT_Requirements.md` on every package run
(plan review + script generation).

## Package layout

Output for each app is a folder named `{AppName}_{Version}` containing:

```
{AppName}_{Version}/
  Package/          # deployable PSADT content
  logs/             # plan, review, requirements copies
```

If `{AppName}_{Version}/` already exists under the output directory, delete it entirely before creating the new package (clean rebuild).

### `Package/` (deployable)

- MUST include the deployment script and a full `AppDeployToolkit/` copy.
- Do **NOT** create `Files/` or `SupportFiles/` folders.
- Installer media (MSI/EXE/MST and related files) MUST be placed at the **Package root**, next to the deployment script.
- **MSI without MST:** create a footprint **MST** that embeds the registry value from `Templates/FootPrint/FootPrintTemplate.reg` (`HKLM\SOFTWARE\Package_Footprint`, name `%Vendor%%AppName%`, value `%Version%` = package `$appVersion`). Apply the MST with `Execute-MSI ... -Transform`. Do **not** leave a `.reg` file in `Package/` — the registry change must come from the MST only.
  - **32-bit MSI** (`$appArch` = `x86` / Platform `Intel`): footprint component must be **32-bit** (no 64-bit component attribute) so Windows Installer writes to the **32-bit registry view** (`HKLM\SOFTWARE\Wow6432Node\...` on 64-bit Windows). Do **not** put `Wow6432Node` in the MSI Registry key path (avoids double redirection).
  - **64-bit MSI** (`x64` / `ARM64`): footprint component must include the **64-bit** attribute so the value is written to native `HKLM\SOFTWARE\Package_Footprint`.
- **EXE footprint (no MST):** in **Post-Installation**, the **last** line must be PSADT `Set-RegistryKey` for the footprint:
  - Key: `HKEY_LOCAL_MACHINE\SOFTWARE\Package_Footprint`
  - Name: `$($appVendor)$($appName)` (Vendor + AppName, no separator — same as `%Vendor%%AppName%`)
  - Value: `1.00` (String)
  - If `$appArch` is `x86`, add `-Wow6432Node` on both set and remove.
  - Required last Post-Installation line:
    `Set-RegistryKey -Key 'HKEY_LOCAL_MACHINE\SOFTWARE\Package_Footprint' -Name "$($appVendor)$($appName)" -Value '1.00' -Type 'String'`
  - In **Post-Uninstallation**, the **last** line must remove it:
    `Remove-RegistryKey -Key 'HKEY_LOCAL_MACHINE\SOFTWARE\Package_Footprint' -Name "$($appVendor)$($appName)"`
  - Any other post-install / post-uninstall steps (custom requirements, etc.) MUST come **before** these footprint lines.
  - Do **not** leave a `.reg` file in `Package/`.

### `logs/` (artifacts)

- `Install_Plan.json`
- `Review_Report.json`
- `PSADT_Requirements.md` (copy of the template requirements used for this run)

## Deployment script file name

- **MSI and EXE installers:** name the script  
  `%Publisher%_%AppName%_%Version%_001.ps1`  
  using package metadata (`$appVendor` → Publisher, `$appName` → AppName, `$appVersion` → Version).  
  - MSI: prefer MSI Property values (`Manufacturer`, `ProductName`, `ProductVersion`).  
  - EXE: use values confirmed via clarification when not readable from the installer.  
  Example: `Simon_Tatham_PuTTY_0.84.0.0_001.ps1`, `WinSCP_WinSCP_6.5.6_001.ps1`
- Sanitize Publisher / AppName / Version for Windows file names (replace invalid characters).

## Application variables

The deployment script MUST set:

- `$appVendor`
- `$appName`
- `$appVersion`
- `$appLang` (default `EN` if unknown)
- `$appRevision`
- `$appScriptVersion`
- `$appScriptDate` (generation date)
- `$appScriptAuthor` (default `Packaging AI` unless overridden)

`$appArch` SHOULD be set when known (`x86` / `x64` / `ARM64`).
- **MSI:** set `$appArch` from the MSI platform (Summary Information Template / Property `Platform`): `Intel`→`x86`, `x64`/`Intel64`→`x64`, `Arm64`→`ARM64`.
- **EXE:** set from filename hints when possible; otherwise leave empty.

## Script structure

- Keep the PSADT 3.10.2 template regions and `DoNotModify` block intact.
- Implement Install and Uninstall paths (Repair optional).
- Use toolkit helpers only (`Execute-MSI`, `Execute-Process`, `Write-Log`, etc.). Do not invent custom install wrappers.
- Prefer package-root installer paths using `$scriptDirectory\...` (e.g. `$scriptDirectory\installer.msi`). Do **not** use `$dirFiles`, `$dirApp`, or `Files\`.

## Install / uninstall commands

- **MSI:** use `Execute-MSI` for install and uninstall; include MST transforms when present; uninstall by ProductCode when available.
- **MSI Parameters:** do **not** pass reboot or logging switches (e.g. `/qn`, `/norestart`, `/l*v`) via `Execute-MSI -Parameters`. Silent/logging/reboot behavior is already defined in `AppDeployToolkit/AppDeployToolkitConfig.xml` (e.g. `MSI_LoggingOptions`).
- **EXE:** classify the installer family first (Inno Setup, NSIS, InstallShield, WiX Burn, Advanced Installer, etc.), then use `Execute-Process` with that family's silent switches.
- Silent / unattended switches are required for enterprise deployment.
- **A valid uninstall command is MANDATORY.** Placeholders, `# TODO`, or `<uninstall_path>` are not allowed.
- Accepted uninstall forms:
  - `Execute-MSI -Action Uninstall -Path "{PRODUCT-CODE}"`
  - `Execute-Process -Path "$envProgramFiles\App\uninstall.exe" -Parameters "/S" -WindowStyle Hidden`
  - Raw: `"C:\Program Files\Notepad++\uninstall.exe" /S` (accepted at clarification; converted automatically)
- **Do not keep hardcoded paths** such as `C:\Program Files\...`. Convert them to PSADT variables:
  - `C:\Program Files\` → `$envProgramFiles\`
  - `C:\Program Files (x86)\` → `$envProgramFilesX86\`
- Example conversion:  
  `"C:\Program Files\Notepad++\uninstall.exe" /S`  
  → `Execute-Process -Path "$envProgramFiles\Notepad++\uninstall.exe" -Parameters "/S" -WindowStyle Hidden`
- **EXE uninstall confirmation:** for EXE installers, always prompt for uninstall confirmation before generating the package (even if a suggestion is known). The user may paste `"C:\Program Files\...\uninstall.exe" /S`, which MUST be converted to `Execute-Process` with `$envProgramFiles` / `$envProgramFilesX86` (no hardcoded paths). `--yes` cannot skip this EXE uninstall prompt.
- **EXE metadata confirmation:** for EXE installers, if Publisher (`$appVendor`), AppName (`$appName`), or Version (`$appVersion`) cannot be read from the installer (filename stem / default `1.0.0` do not count as found), prompt for clarification as `Publisher|AppName|Version` before generating. Example: `Notepad++|Notepad++|8.9.6.2`. `--yes` cannot skip this prompt. MSI packages (including MSI extracted via dark.exe) use MSI Property metadata and do not require this prompt when those properties are present.

## EXE → MSI via WiX dark.exe

- For **EXE** installers, the system MUST attempt to decompile/extract with WiX **dark.exe** located at `Tools/WIX/dark.exe`.
- Command pattern: `dark.exe -nologo -x <extract_dir> -out <out.wxs> <installer.exe>`
- If dark.exe extracts one or more `.msi` files (typical for WiX Burn bundles), select the **main MSI** (largest by default), read its metadata, and package **as an MSI** (script naming, `Execute-MSI`, ProductCode uninstall).
- Record `source_exe` and `extracted_via_dark` in the `Install_Plan`.
- If dark.exe fails (e.g. not a WiX Burn stub / DARK0339) or finds no MSI, continue with normal EXE packaging (family detection, silent/log switches, EXE uninstall confirmation).
- Do not invent an MSI when dark.exe cannot extract one.

- The system MUST detect the EXE installer type (family) from the binary (embedded signatures).
- After classification, resolve the **log file parameter** for that family and include it in the install command when the family supports logging.
- Default installer log path: `$configToolkitLogDir\$($appName)_$($appVersion)_Install.log`
- Known log-file parameters:

| Family | Silent (typical) | Log file parameter |
|--------|------------------|--------------------|
| Inno Setup | `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-` | `/LOG="{LOG}"` |
| NSIS (e.g. Notepad++) | `/S` | *(none — standard NSIS has no log switch)* |
| InstallShield | `/s /v"/qn"` | `/f2"{LOG}"` |
| WiX Burn | `/quiet /norestart` | `/log "{LOG}"` |
| Advanced Installer | `/qn` | `/log "{LOG}"` |
| Install4j | `-q` | `-Dinstall4j.alternativeLogfile={LOG}` |
| MSI | *(via Execute-MSI / AppDeployToolkitConfig.xml)* | *(via `MSI_LoggingOptions` in AppDeployToolkitConfig.xml — do not pass `/l*v` on Execute-MSI)* |

- If the family has **no** standard log switch (NSIS, Squirrel, unknown EXE), omit a fake log parameter and record that in the `Install_Plan` assumptions.
- Store the resolved `log_file_parameter` in `Install_Plan.json` when used.

## Pre / post steps

- Pre-Install / Post-Install steps from the `Install_Plan` SHOULD be written into the matching template markers.
- Do not leave interactive prompts that block silent deployments unless the plan explicitly requires them.

## Review gate

Before generation is accepted, review MUST check that:

1. Primary installer and install command are present.
2. App name and version are present.
3. Commands follow the MSI/EXE rules above (including EXE family detection and log-file parameter rules).
4. **A valid uninstall command is present** (mandatory).
5. Script file naming follows the MSI vs EXE rules above.
6. If confidence &lt; **0.75**, prompt the user for clarification and do not generate until resolved or aborted.
7. Missing/invalid uninstall always forces clarification (confidence capped below 0.75).
8. Missing EXE Publisher / AppName / Version always forces clarification (confidence capped below 0.75).
