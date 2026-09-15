# SCCM replacement — Tanium, not Intune

This pack is for operators and leadership. It compares **Microsoft Configuration Manager (SCCM / MECM)** to **Tanium** for *this* estate, and it states what must be true before SCCM can be retired.

**Decision:** Intune is not the software, patch, or server engine. Tanium (already paid for) is the candidate to take applications, patch, inventory, and live scripts. Task sequences (new-machine imaging and ordered app chains) are the main gap and have their own owner.

## How to read this pack

| File | Read it for |
|---|---|
| [usage.md](usage.md) | Constraints: 250k devices, on-prem/non-Intune, servers, 5,000 packages, task sequences, rejected Cloudpager and CMG+Intune |
| [comparison-sccm-vs-tanium.md](comparison-sccm-vs-tanium.md) | Side-by-side: reporting, apps, maintenance windows, servers, agent, inventory, CMScript |
| [task-sequences-and-ordered-apps.md](task-sequences-and-ordered-apps.md) | Job A (OSD / new machines) vs Job B (many apps in order) |
| [pilot-and-sunset.md](pilot-and-sunset.md) | Go/no-go lab, package classify/republish, Intune boundary, dated SCCM teardown |
| [converting-sccm-apps.md](converting-sccm-apps.md) | SCCM → Tanium: same payload, **recreate + retest** every kept title. Not Intune. |
| [tanium-vs-intune-and-autopilot.md](tanium-vs-intune-and-autopilot.md) | Entra-only Autopilot/W365 + on-prem AD. Tanium manages both; cannot replace Intune. |
| [autopilot-alternatives.md](autopilot-alternatives.md) | What replaces Autopilot if Intune goes: Provision, OSDCloud/MDT, or thin Autopilot-only Intune. |
| [content-distribution.md](content-distribution.md) | Global WAN: Tanium linear chain + Zone Servers vs SCCM DPs + CMG. |

## One-line verdicts

- **Tanium is stronger** at live ops, servers, agent simplicity, inventory freshness, ad-hoc scripts (Interact vs CMScript), and **pulling client/PSADT logs from a failed group** (SCCM and Intune are both painful).
- **SCCM is stronger** at the 5,000-app catalog, collection maintenance windows, historical deployment reports, PXE/OSD, and ordered task sequences.
- **Intune** does not see on-prem machines, does not give server maintenance windows, and does not replace OSD at this scale. Waiting on Intune “server support” keeps SCCM forever.
- **Cloudpager / MSIX / App-V** stay rejected: new runtime, extra failure points, package rewrite.
- **HCL BigFix** is the only SCCM clone worth reopening — and only if the Tanium lab fails on Deploy or server maintenance windows. Do not run BigFix + Tanium + leftover SCCM.

## What we keep vs replace

**Keep:** the **PSADT folder** as it is today (`Deploy-Application.exe`, toolkit, `Files`, `SupportFiles`). No new package format. No rewrite of 5,000 toolkits.

**Replace:** SCCM site, distribution points, CMG, collections-as-targeting, software update point, built-in reports.

**Republish, do not rebuild:** same installer bits. Every kept title is still **created again** in Tanium and **tested again** on the Tanium client. SCCM green does not carry over. Detection becomes sensors.

## Success criteria

- Same installers run on PCs **and** servers, including machines that are not Intune objects.
- Maintenance windows hold for server patch and change.
- Operator reports exist without opening the ConfigMgr console.
- Intune never assigns Win32 apps or server patches.
- No streaming or virtualization runtime.
- SCCM is uninstalled after each workload has a named owner — including OSD.

Typical horizon for an estate this size: **18–36 months**, driven by OSD and server maintenance-window proof, not by how fast you can wrap an EXE.
