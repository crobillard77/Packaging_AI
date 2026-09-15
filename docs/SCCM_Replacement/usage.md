# How this estate actually uses SCCM

Recommendations that ignore this page will fail. This is not a generic “move to Intune” shop.

## Scale and topology

- About **250,000** devices.
- Mix of **Intune-enrolled PCs** and a large **on-prem / Active Directory** population that is **not** an Intune machine. Intune cannot see or deploy to those devices.
- **Servers** are in scope. For servers, **maintenance windows are essential**.
- Tanium is **already available**. The question is whether it can take SCCM’s jobs — not whether to buy another agent.

## Software catalog

- About **5,000 packages** already work in SCCM.
- **Every title is PSADT** (PowerShell App Deployment Toolkit): `Deploy-Application.exe` / toolkit folder + `Files` + `SupportFiles`. That is the unit you recreate in Tanium — not a raw MSI dropped on the box.
- There will be **no project to rebuild packages** (no Cloudpager, no MSIX conversion factory, no App-V revival, no rewrite of 5,000 `Deploy-Application.ps1` files).
- Uniform PSADT is an advantage for the factory (one or two command-line templates). It does **not** skip recreate + retest. See [converting-sccm-apps.md](converting-sccm-apps.md).
- Most large ConfigMgr catalogs are not 5,000 unique live products. They are versions, superseded titles, dead vendors, and software nobody has launched in years. The work is **classify and republish**, not rewrite installers.

## How software is installed today

Two patterns, both first-class:

1. **Standalone applications / packages** — detection, command line, collections, required vs available.
2. **Task sequences**
   - **New machines:** PXE or media → disk, WIM, drivers, domain join, baseline, then a long tail of Install Application / Install Package / Run Command / reboots / updates.
   - **Ordered stacks:** a TS used as an orchestrator (on a new box or an existing one) to install many applications **in order**, sometimes with a reboot in the middle.

Tanium Deploy can take (1) and many of (2) that do **not** need a mid-sequence reboot contract. It does not replace the OSD task sequence engine. See [task-sequences-and-ordered-apps.md](task-sequences-and-ordered-apps.md).

## What already failed or will not last

| Approach | Why it is out |
|---|---|
| **Numecent Cloudpager** (and similar streaming / layering) | Changes how the app *runs*. Extra control plane, cloud stream, container compatibility. Simple points of failure. Forces a rewrite of 5,000 working packages. |
| **SCCM + CMG + Intune as equals** | Two authorities (ConfigMgr client vs Intune MDM). Client Apps workload fights itself. CMG content vs Intune content, certs, cost. Already painful. Microsoft is not investing in CMG as a forever platform. |
| **Intune as the SCCM replacement** | Cannot manage non-enrolled on-prem devices. Weak maintenance windows. Reporting is not SCCM-grade. No on-prem OSD. “Server support” will not give MW + 250k + 5,000 packages. |
| **Another full UEM next to Tanium** (BigFix “just in case”, Ivanti, PDQ as the estate engine) | Second brain — same class of risk as Cloudpager + SCCM. Only reopen BigFix if Tanium fails a written lab on Deploy or server MW. |

## Intune’s only allowed role

**MDM, Autopilot, Windows 365 provisioning, and compliance on enrolled PCs.** Tanium cannot replace Intune for those. Details: [tanium-vs-intune-and-autopilot.md](tanium-vs-intune-and-autopilot.md).

Intune must **not**:

- Own Client Apps (Win32) as the enterprise deployer
- Patch servers
- Be the maintenance-window authority
- Be the reason we wait to retire SCCM

That boundary is how we avoid the CMG + Intune mess. Details: [pilot-and-sunset.md](pilot-and-sunset.md).

## Workloads SCCM owns today (and must have an owner after)

| Workload | Must move off SCCM | Notes |
|---|---|---|
| Application deployment (the catalog) | Yes | Republish to Tanium Deploy; same payloads |
| Patching / software updates | Yes | Server MW is the go/no-go |
| Inventory and operator reporting | Yes | Live = Tanium; history = Connect + warehouse |
| Run Script / CMPivot | Yes | Interact + Deploy Action; move first |
| OS imaging / task sequences | Yes, but separately | Job A — do not assume Tanium Deploy or Intune |

## What leadership should not fund

- Growing CMG or adding distribution points
- New applications created only in ConfigMgr (freeze, then drain)
- A packaging conversion program
- Intune Win32 as the 250k / server path
- A second endpoint manager “because Tanium packaging is different”
