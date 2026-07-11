# Packaging AI v1.0

AI-assisted Windows software packaging that produces **PSADT 3.10.2** packages from a folder of installer media.

## Requirements

- Windows
- Python 3.13+ (project uses `D:\DEV\Python_3.13.14` / `.venv`)
- `pywin32` for read-only MSI metadata

## Setup

```powershell
D:\DEV\Python_3.13.14\python.exe -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\pip.exe install -e .
```

Optional AI review (otherwise a heuristic reviewer is used). **Prefer Cursor:**

```powershell
$env:CURSOR_API_KEY = "cursor_..."   # from https://cursor.com/dashboard/integrations
# optional model override (default from packaging_ai.config.json → model)
# $env:PACKAGING_AI_MODEL = "composer-2.5"
# runtime: cloud (default, recommended on Windows) or local
# $env:PACKAGING_AI_CURSOR_RUNTIME = "cloud"
```

OpenAI remains supported as a fallback:

```powershell
$env:OPENAI_API_KEY = "sk-..."
```

Review priority: `CURSOR_API_KEY` → `OPENAI_API_KEY` → heuristic.
Cursor review uses a **cloud** agent by default. On Windows, Packaging AI patches the Cursor SDK bridge discovery path (avoids WinError 10038 from `select()` on pipes).

## Usage

```powershell
.\.venv\Scripts\python.exe -m packaging_ai "D:\path\to\installer\folder"
.\.venv\Scripts\python.exe -m packaging_ai "D:\path\to\installer\folder" -o "D:\packages" -y
```

- Input must be an **absolute** folder path.
- If confidence &lt; **0.75**, the CLI asks for clarification (use `-y` to auto-confirm).
- Output layout: `{App}_{Version}/Package/` (script + toolkit + installer) and `{App}_{Version}/logs/` (plan, review, requirements).

## Templates store

Canonical PSADT assets live in `Templates/` (`Deploy-Application.ps1`, `AppDeployToolkit/`, `PSADT_Requirements.md`) and are never optional for generated packages.

Paths for the templates folder and `dark.exe` are configured in `packaging_ai.config.json` (override with `$env:PACKAGING_AI_CONFIG` pointing at another JSON file):

```json
{
  "templates_dir": "Templates",
  "dark_exe": "Tools/WIX/dark.exe",
  "dark_cache_dir": ".cache/dark",
  "output_dir": "output",
  "confidence_threshold": 0.75,
  "model": "composer-2.5",
  "openai_model": "gpt-4o-mini"
}
```

Relative paths resolve from the project root; absolute paths are also accepted.
`$env:PACKAGING_AI_MODEL` overrides `model` (Cursor). `$env:PACKAGING_AI_OPENAI_MODEL` overrides `openai_model`.
