# Ticket breakdown: keyword estimate for the area review

**What this is:** a rough estimate of how tickets split across the draft problem areas, made with keyword rules (`scripts/keyword_baseline.py`). The goal is to help the technicians review the areas before the pilot. It is **not** the real distribution: nobody has labelled these tickets yet, and the pilot gives the first measured breakdown. See @@Plans/project_plan@@ for the full plan.

**Which tickets:** the pilot and backlog tickets (@@Assets/Helpdesk tickets (history)@@). Leave the eval tickets out, so the keyword rules (which are also the baseline Jev has to beat) aren't tuned on them.

**How reliable:** each ticket goes to the area whose keywords it matches most, with subject-line matches counting more than body matches. Spot-check a few tickets per area and say how many look plausible. Generic words ("memory", "display", "permission") pull unrelated tickets into an area, so read the shares as give-or-take several points.

## By area

<A table and a pie chart of tickets per area, plus "no keyword match". Note the share of tickets where the runner-up area scored within one point of the winner: that's how often "which problem is the main one" is a real judgement call.>

| Area | Tickets | Share | Technician |
|---|---|---|---|
| WINDOWS | | | Windows PCs |
| APPS | | | by platform |
| HARDWARE | | | Hardware & storage |
| LINUX_AND_SERVERS | | | Linux & servers |
| NETWORK | | | Networking & VPN |
| STORAGE | | | by platform |
| OTHER | | | Triage |
| No keyword match | | | Triage |

## By technician

<The same tickets through `scripts/routing.py`, so the technicians see the load each would get.>

| Technician | Tickets | Share |
|---|---|---|
| Windows PCs | | |
| Hardware & storage | | |
| Linux & servers | | |
| Networking & VPN | | |
| Triage | | |

## Questions for the technicians

1. **Load:** is any technician's share more than one person can take? That's a change to the area→technician table, not to the areas.
2. **Tools with no clear home** (e.g. media and file tools such as FFmpeg, PDFs, Pandoc): do they belong in APPS, or need their own area?
3. **Small areas** (e.g. accounts and sign-in): keep them through the pilot and decide on the measured numbers.
4. **Which problem counts as the main one?** Proposed rule: *"the area of the thing the user needs fixed, not the area where they noticed it"*. Under it, a disk that won't mount on Windows is STORAGE, and a printer that won't join Wi-Fi is NETWORK.
5. **Macs and phones:** does anyone cover them, or do they go to triage (OTHER)?
6. **App and disk tickets that name no system:** who gets them?

## Examples by area

<Two subject lines per area from the backlog, keyword-assigned, so the technicians can see what each area holds.>

## Outcome of the review

<The technicians' answers to the questions above, and the changes to the areas and the routing table that follow from them.>
