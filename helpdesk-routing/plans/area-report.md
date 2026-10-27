# Problem-area report

Which problem areas the helpdesk's tickets fall into, month by month, and what recurs inside each area. Part of @@Projects/Helpdesk routing@@; see @@Plans/project_plan@@ for how the areas and Jev were evaluated.

## How it's made
`scripts/area_report.py` gives each ticket one area, from the best source available:
1. **A person's answer**: the eval gold labels, the settled pilot answers, and later the monthly triage of tickets Jev wasn't sure about.
2. **Jev at or above the routing threshold.** Give its area accuracy on the eval set.
3. **Jev below the threshold.** Give how often these are right on the eval set; usually much less often.

Jev's answers for the backlog come from @@Actions/helpdesk-history-jev-v1@@, run on @@Assets/Helpdesk tickets (history)@@ into @@Datasets/helpdesk-history-jev-v1@@, with the same settings as the eval run: the pinned model, the final @@Assets/Helpdesk problem areas@@, the same instructions and `--min-confidence 0`. The eval tickets use @@Datasets/helpdesk-eval-jev-v1@@. Lock the exports (read-only, SHA-256 recorded here).

**How far the counts can be trusted.** On the eval set, compare the counts per area from Jev's answer on every ticket with people's counts. Jev's unsure answers usually skew some areas up and others down. Say which, and how much of this report rests on unsure answers. With people answering the tickets Jev is unsure about, the counts should be close to people's, which is the setup going forward.

## <First month> – <last month> (<n> tickets)
Say how many areas come from a person, from Jev above the threshold and from Jev below it, and mark part-months.

| Area | Tickets | Share | Of which Jev unsure |
|---|---|---|---|
| APPS | | | |
| WINDOWS | | | |
| LINUX_AND_SERVERS | | | |
| NETWORK | | | |
| HARDWARE | | | |
| STORAGE | | | |
| OTHER | | | |

### By month

| Month | APPS | WINDOWS | NETWORK | HARDWARE | LINUX_AND_SERVERS | STORAGE | OTHER | Total |
|---|---|---|---|---|---|---|---|---|

**Reading the trends.** If some months have more of people's labels than others (e.g. the months the eval set came from), compare months on Jev's answers alone, so every month is counted the same way. At around a hundred tickets a month, a 5-point move is a handful of tickets: treat it as worth watching rather than established.

## What recurs inside each area
Terms from the subject lines that set an area apart from the others (log-odds against all other tickets), with the number of tickets in the area mentioning them. They point to where to look, not to root causes: most tickets are "how do I…" questions, not faults.

- **APPS:** <the largest groups of apps and tools>
- **WINDOWS:** …
- **LINUX_AND_SERVERS:** …
- **NETWORK:** …
- **HARDWARE:** …
- **STORAGE:** …
- **OTHER:** …

**Where to look first:** <the largest single group of recurring questions, and what could prevent them, e.g. a how-to page or training>.

## Monthly routine
Once routing is live, each month's report comes from the live routing. Jev's sure answers come from the daily batches, and people give the area of the tickets Jev was unsure about in a monthly triage task:

1. After the month ends, create the triage task: the tickets Jev was unsure about plus a few it was sure about, mixed in blind as a check on Jev. People's answers on those count as people's answers in the report.
2. Once it's done, check that every ticket has an area and add the month here as a new section.

Live months have no "Jev unsure" answers, so their counts aren't skewed like the backlog's. Compare them with the first report on its Jev-only figures. See "Running it" in @@Plans/project_plan@@.
