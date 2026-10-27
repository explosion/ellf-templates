# Eval overlap: agreement between the two annotators

**Question:** do two people apply the frozen problem-area definitions (@@Assets/Helpdesk problem areas@@, @@Assets/Helpdesk problem areas guidelines@@) the same way? The answer decides two things: whether the remaining 400 eval tickets can be labelled by one person, and how high Jev can realistically score. See @@Plans/project_plan@@ for the full evaluation design.

**Data:** the 100 tickets in @@Assets/Helpdesk tickets (eval_overlap)@@, labelled independently by the project lead and the second annotator in @@Tasks/helpdesk-eval-overlap@@ (dataset @@Datasets/helpdesk-eval-overlap@@). No drafts, and neither sees the other's answers. Check that both gave exactly one area for every ticket.

**Reproduce:** export @@Datasets/helpdesk-eval-overlap@@ with `ellf datasets export`, then run `scripts/agreement_overlap.py` on the export with the two annotators' Ellf user IDs (their sessions in the dataset).

## Result

| | Agreement |
|---|---|
| Problem area | <n> / 100 (Cohen's kappa) |
| Technician (area + the routing table) | <n> / 100 |
| Tickets nobody flagged | |
| Tickets flagged by at least one person | |

**Do the definitions hold?** If technician agreement is above ~90%, the project lead labels the remaining 400 tickets alone and the definitions stay frozen. Below it, fix the definitions first.

**Do the flags work?** Check whether the disagreements are on flagged tickets. If people never disagree when neither hesitated, flags are a reliable signal of hard tickets.

## Confusion matrix

Rows are the lead's answers, columns the second annotator's. The diagonal is agreement.

| Lead ↓ / Second → | APPS | WINDOWS | NETWORK | LINUX_AND_SERVERS | HARDWARE | STORAGE | OTHER |
|---|---|---|---|---|---|---|---|
| **APPS** | | | | | | | |
| **WINDOWS** | | | | | | | |
| **NETWORK** | | | | | | | |
| **LINUX_AND_SERVERS** | | | | | | | |
| **HARDWARE** | | | | | | | |
| **STORAGE** | | | | | | | |
| **OTHER** | | | | | | | |

Say whether the two used the areas in similar proportions, and whether one pair of areas stands out.

## The disagreements

| Ticket | Lead | Second | Flagged by | Changes technician | Subject |
|---|---|---|---|---|---|

Disagreements that change the technician matter for routing. Settle them in @@Tasks/helpdesk-eval-overlap-settle@@.

## What this means for evaluating Jev

- **The ceiling:** how often two people agree on the technician. Compare it with Jev's bar: if the bar is about as high as people get on all tickets, it's realistic only if Jev's confidence picks out the clear tickets.
- **The gold labels:** the 400 tickets only the lead labels carry one person's reading of the definitions. The overlap agreement says how many of them a second person would route differently.
- **Slips:** count empty accepts and likely wrong buttons; they feed the slip check.

## Next

- Settle the disagreements in @@Tasks/helpdesk-eval-overlap-settle@@.
- The project lead labels the other 400 eval tickets in @@Tasks/helpdesk-eval-lead@@.
