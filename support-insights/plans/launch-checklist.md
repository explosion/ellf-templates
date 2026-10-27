# Launch Readiness Checklist

What has to be true before the ticket pipeline runs against live traffic. The
work itself is tracked in @@Plans/project_plan@@; this page is only the gate.
Nothing ships while an unchecked box remains in the first two sections.

## Data

- [ ] Training pool published — @@Assets/Support Tickets (train)@@
- [ ] Eval set held out and annotated without a model in the loop — @@Assets/Support Tickets (eval)@@
- [ ] Gold set adjudicated — @@Datasets/support-ner-gold@@
- [ ] Match patterns loaded into the manual interface — @@Assets/Ticket entity patterns@@
- [ ] Label definitions published and attached to the annotation tasks — @@Assets/Ticket entity labels@@, @@Assets/Ticket routing labels@@
- [ ] Annotation guidelines published — @@Assets/Ticket entity guidelines@@, @@Assets/Ticket routing guidelines@@
- [ ] Training pool fully annotated — @@Tasks/tickets-ner-annotate-train@@
- [ ] Routing categories balanced in @@Datasets/support-routing-train@@

## Models

- [ ] @@Actions/train-ticket-ner-v1@@ run against the current gold set
- [ ] @@Actions/train-ticket-routing-v1@@ run once the categories are balanced
- [ ] Per-label F-score on the eval set read and recorded, `INTEGRATION` and `FEATURE` separately
- [ ] Learning curve from @@Actions/train-ticket-ner-curve@@ says whether more annotation still buys accuracy

## Agreement

- [ ] Boundary rules written down — @@Plans/label-scheme@@
- [ ] Agreement measured on an overlap sample after the boundary rules landed — @@Tasks/tickets-ner-review@@

## Operations

- [ ] Live annotation metrics available to the team — @@Services/ticket-annotation-dashboard@@
- [ ] Rollback path agreed: how a bad model is taken out of the ticket stream, and who does it

## Sign-off

Record here which sections are complete, what's still blocking and what it's
waiting on: a decision, or annotator time.
