# SCCM vs Tanium — comparison for this estate

Verdict in one line: **Tanium wins live ops, servers, agent simplicity, and ad-hoc scripts. SCCM wins the app catalog, collection-based maintenance windows, historical deployment reports, and task sequences. Neither is Intune.**

HCL BigFix is the closer SCCM clone. Reopen it only if this comparison fails in the lab on Deploy or server maintenance windows. Do not run BigFix + Tanium + leftover SCCM.

## Scorecard

| Area | Winner | Note |
|---|---|---|
| Reporting (live) | Tanium | Seconds, not state messages |
| Reporting (deployment history / SSRS clones) | SCCM | Until Connect + a warehouse |
| App catalog / supersedence / Software Center | SCCM | 5,000 titles live here |
| Push installer at 250k without CMG | Tanium | Linear chain, no DP fabric |
| Content distribution worldwide | Tanium | Peers + few Zone Servers; SCCM = DP mesh + CMG. See [content-distribution.md](content-distribution.md) |
| Maintenance windows as a contract | SCCM | Tanium must prove Patch windows |
| Servers (reach, no MDM) | Tanium | Why Intune is out |
| Agent reliability / simplicity | Tanium | Fewer moving parts |
| Inventory freshness | Tanium | Sensors |
| Inventory as a historical CMDB | SCCM | Until a nightly Connect feed |
| Quick script (CMScript / Run Script / CMPivot) | Tanium | Interact + Action |
| Getting client deployment logs | Tanium | Live last-N-lines from the failed group; Intune/SCCM are painful |
| New machine build (PXE / OSD TS) | SCCM | Tanium Provision is not a TS port |
| Ordered multi-app install | SCCM | Tanium = bundles + dependencies, not SMSTS |

See [task-sequences-and-ordered-apps.md](task-sequences-and-ordered-apps.md) for PXE and ordered apps.

## Reporting

**SCCM wins historical “what did we deploy?”** Tanium wins “what is true right now?” Out of the box they are not substitutes.

### SCCM

- SQL + SSRS (and the data warehouse / Power BI if already built).
- Deployment ID, collection, success / fail / in progress, error codes, subscriptions, custom SQL.
- This is why operators trust it.
- Inventory in those reports is as stale as the last hardware/software cycle (often days).
- CMPivot is the live add-on, not the default.

### Tanium

- Interact answers in seconds.
- **Trends** and **Reporting** for history.
- **Connect** to Splunk / Sentinel / Snowflake / SQL is how a 250k estate gets SCCM-like operational reports.
- If you only open the Tanium console the way you open Software Library → Reports, you will call reporting worse than Intune.

### Implication

Replacing SCCM reports is a **warehouse project**, not a module checkbox. List the 15 reports people actually open. Recreate each via Trends or Connect. If three cannot be built, that is a no-go — or a written exception to keep a read-only SCCM SQL replica for a year.

Lab steps: [pilot-and-sunset.md](pilot-and-sunset.md).

## Client deployment logs (why did it fail?)

**Tanium is better than SCCM. Intune is worse than both.** This is one of the few operator pains Tanium actually fixes on day one.

The log still lives on the box. The difference is how you **get a useful slice** without RDP, Support Center, or “Collect diagnostics” and a coffee.

### SCCM — painful (you already know)

- Truth is on the client: `AppEnforce.log`, `AppDiscovery.log`, `execmgr.log`, `smsts.log`, plus **PSADT** under `C:\Windows\Logs\Software\`.
- The site gets a **status message and an error code**, not the toolkit log. Software Center does not upload PSADT logs.
- Built-in “client diagnostics” / log upload is per machine, slow, and not made for “these 400 failed last night.”
- CMPivot can read a file; it is an add-on and clumsy for large logs.
- Reality in most 250k shops: Recast / Support Center / a share / ask the user. That is why this hurts.

### Intune — more painful

- IME logs (`IntuneManagementExtension.log`, AppWorkload) stay local.
- Admin center: status + a short error. **Collect diagnostics** is one device, delayed, Azure-side.
- No natural “question the failed group, return last 80 lines.”
- On-prem machines that are not enrolled: **no log path at all** through Intune.

### Tanium — this is Interact

You ask the **failed computer group** a question. You do not RDP 400 boxes.

Typical pattern for this estate (all PSADT):

1. Deploy shows who failed.
2. Interact sensor: newest file matching `*PSAppDeployToolkit*` (or your log name) under `C:\Windows\Logs\Software\` — return **last N lines** (or lines containing `Error` / `Exit Code`).
3. Answers come back in tens of seconds. That is usually enough to see “cwd wrong,” “MSI 1618,” “defer 60012,” “ServiceUI waiting for session.”

For a **full** log from a few machines: Deploy Action to copy that file to a central share, or Direct Connect / live response on a single endpoint. Do **not** slurp 20 MB logs from 250k clients in one question — result-size limits and you will hurt the linear chain. Target the failure set; bound the sensor (last N lines, max file size).

| Need | SCCM | Intune | Tanium |
|---|---|---|---|
| Error code in the console | Yes | Yes | Yes (Deploy status) |
| PSADT log from 1 box | Painful | Painful | Sensor or pull file |
| Last 80 lines from 400 failures | Recast / RDP / hope | Essentially no | **Interact on that group** |
| Archive every log forever | SQL will not do this | No | Connect / copy-to-share / SIEM — still a design, not automatic |
| smsts.log during OSD | Local / TS debugging | N/A | Only if you still have a TS engine |

Tanium is not a log SIEM. It is a **live collector**. If compliance wants 90 days of every PSADT log, that is still Connect or a copy-to-share action — but you are no longer blind while the incident is happening.

**Lab check:** after the 20-app Deploy pilot, pick a forced failure and prove: question → last 80 lines of the PSADT log from every failed box, no RDP. If that sensor is not built, operators will say Tanium logging is “the same pain.”

## Application deployment

**SCCM wins the 5,000-app *model*.** Tanium Deploy wins *delivery mechanics* (no DP/CMG) and “push this installer now.”

### SCCM

- Applications: detection, requirements, global conditions, dependencies, supersedence, user vs system, required vs available.
- Software Center, packages, task sequences.
- Content via distribution points, peer cache, Delivery Optimization, CMG.
- Collections as targeting.
- This is why the 5,000 titles work as a catalog.

### Tanium Deploy

- This estate: the **whole PSADT folder** wrapped as a Tanium package or bundle (not an unwrapped MSI). Silent mode for unattended Deploy.
- Applicability and success = **sensors**, not SCCM detection rules.
- Targeting = computer groups from saved questions, not collections.
- Linear-chain content distribution scales to 250k without CMG.
- No 1:1 supersedence, nested dependencies, or Software Center-equivalent catalog unless you build or buy self-service on top.

### Implication

Do not “import SCCM.” Republish silent installers. Deep App Model (requirement forests, chained supersedence) is the pain — not the EXE. Pilot 20 real titles including one dependency pair before committing the catalog. Never dual-deploy a title from SCCM and Tanium.

## Maintenance windows

**SCCM wins as a first-class object.** Tanium can enforce change calendars, but you re-express them. You do not export collections + MW.

### SCCM

- Maintenance window on the collection (all deployments / software updates / task sequences).
- Multiple windows, local or UTC.
- Deployments can honor or override.
- This is the server-ops contract: nothing installs or reboots outside Sunday 02:00–06:00.

### Tanium

- **Tanium Patch:** maintenance windows and **blackouts**, plus reboot control and notifications.
- Deploy and Interact actions are scheduled **separately**. They do not automatically inherit a collection MW the way ConfigMgr deployments do.
- Overlapping windows, clustered servers, and “missed the window, wait until next” must be proven in a lab.

### Implication

Treat MW as the **server go/no-go**. Side-by-side one real server ring. If Tanium cannot guarantee no patch or reboot outside the window, Tanium is not the SCCM replacement for servers.

## Server support

**Tanium wins.** This is the main reason Intune is out and Tanium is in the conversation.

### SCCM

- Works on Windows Server and is widely used.
- It is still a desktop-client architecture pointed at servers (management points, policy, WUA, Software Center).
- Fine, heavy, collection- and MW-centric.

### Tanium

- Servers are a native use case.
- No Entra / Intune enrollment.
- Question the whole server estate in one pass.
- Patch for Server OS is core.
- Zone Servers cover isolated / on-prem rings without CMG.

### Intune “server support”

Do not wait for it. It will not give you maintenance windows + 250k + 5,000 packages.

## Agent reliability

**Tanium client is simpler and usually more reliable.** SCCM client does more in the background and fails in more ways.

### SCCM (`CcmExec`)

- Many components: policy, inventory, WUA, configuration items, task sequences, BITS / DO.
- Client health, broken WMI, stuck deployments, high CPU during inventory are normal operations work at 250k.
- Needs boundaries, management points, cloud management gateway.
- When it works it is robust. When it breaks it is a career.

### Tanium Client

- One agent, one connection pattern (Tanium Server, Zone Server, or linear peers).
- Few moving parts. Low idle cost if questions are disciplined.
- Risk is operational: a bad question or a topology mistake at 250k (expensive sensors, broken linear-chain “islands”).
- High availability is a Tanium Server / Module Server design problem, not 250k unique client bugs.

### Implication

Running both agents during transition is normal. End state is Tanium only (plus Intune MDM on enrolled PCs). Sunset **removes `CcmExec`**. It does not add a third agent.

## Inventory

**Tanium wins freshness and custom questions.** SCCM wins a stable historical asset database if you never built Connect.

### SCCM

- Scheduled hardware / software inventory into SQL (Asset Intelligence, metering, file collection).
- Collections from WQL.
- Excellent for “as of last cycle” CMDB feeds. Stale by design.
- Extending inventory (MOF / hardware inventory) is slower than writing a Tanium sensor.

### Tanium

- Sensors are live. “Which servers have this KB / this service / this file” is the product.
- **Asset** normalizes installed software.
- **Discover** finds unmanaged.
- History and CMDB export = Trends + Connect (same pattern as reporting).

### Implication

Operators will prefer Tanium the first week. Finance / CMDB still need a **nightly warehouse snapshot** so inventory does not change every time someone asks.

## Quick scripts (Run Script / CMScript / CMPivot)

**Tanium wins.** This is Interact + Deploy Action — the original product, not an add-on.

### SCCM

- **Run Script** (Software Library → Scripts): approve a script, run on a collection, collect output.
- Parameters, timeout, RBAC / approval.
- **CMPivot** for live query and limited remediations.
- Recast and community tools fill gaps.
- Good enough; still collection-bound and slower to converge than Tanium.

### Tanium

- Ask a question → see who matches in about 15–60 seconds → **Deploy Action** (approved package: PowerShell, cmd, existing installer).
- Saved questions and scheduled actions.
- Output is sensor results, not a delayed script job.
- Approval and RBAC exist and **must stay mandatory** at 250k so “quick” does not mean untracked change.

### Implication

There is no feature gap. Map the approved CMScript library to Tanium packages and action groups. Keep the same approval you use in ConfigMgr. **This workload can move first** and will sell Tanium to operators.

## Where Tanium is weaker (decide before sunset)

- OSD / task sequences: **Tanium Provision** is not the TS library.
- Historical “deployment ID 12345, 14% failed, these 2,000 machines” until the warehouse exists.
- 5,000-app catalog operations (folders, supersedence, role-based admin as in ConfigMgr).
