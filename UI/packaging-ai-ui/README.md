# Packaging AI UI

Angular **22.0.6** operator wizard for the Packaging AI API.

## Prerequisites

- Node.js **≥ 22.22.3** (Angular CLI requirement)
- Running Packaging AI API (see [`API/README.md`](../../API/README.md))

## Auth model

The UI **does not** ask for or store an API key. `X-API-Key` is injected by:

- **IIS** (production) when reverse-proxying `/v1` to uvicorn
- **Angular proxy** (local `npm start`) via [`proxy.conf.js`](proxy.conf.js)

Anyone who can open the website can create jobs — protect the IIS site (VPN, IP allowlist, Windows auth).

## Install and run (local)

```powershell
cd D:\DEV\Projects\Packaging_AI\UI\packaging-ai-ui
npm install
$env:PACKAGING_AI_API_KEYS = "dev-key-change-me"   # must match the API
npm start
```

Open `http://localhost:4200/`.

### API (separate terminal)

```powershell
cd D:\DEV\Projects\Packaging_AI
.\.venv\Scripts\Activate.ps1
$env:PACKAGING_AI_API_KEYS = "dev-key-change-me"
$env:PACKAGING_AI_JOB_STORE = "memory"
python -m packaging_ai.api
```

## IIS (production)

1. Build: `npm run build`
2. Copy `dist\packaging-ai-ui\browser\*` into the **PackagingAI-API** site physical path.
3. `web.config` — proxy only `/v1` and `/health`, and inject the key on `/v1`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="PackagingAI API v1" stopProcessing="true">
          <match url="^v1(/.*)?$" />
          <serverVariables>
            <set name="HTTP_X_API_KEY" value="YOUR_REAL_API_KEY" />
          </serverVariables>
          <action type="Rewrite" url="http://127.0.0.1:8000/{R:0}" />
        </rule>
        <rule name="PackagingAI health" stopProcessing="true">
          <match url="^health$" />
          <action type="Rewrite" url="http://127.0.0.1:8000/health" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

4. Allow the server variable once (elevated):

```powershell
# IIS Manager → URL Rewrite → View Server Variables → Add HTTP_X_API_KEY
# or edit applicationHost.config <rewrite><allowedServerVariables>
```

Use the same secret as `PACKAGING_AI_API_KEYS` on the uvicorn service. Do not commit the real key.

## Build for production

```powershell
npm run build
```

Output is under `dist/`. Keep `apiBaseUrl` empty for same-origin IIS hosting.

## Flow

Sources → create job → poll → clarifications (Required / Optional) → package location.
