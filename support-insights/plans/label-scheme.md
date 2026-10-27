# Entity Scheme: Support Ticket Extraction

The entity-level companion to @@Plans/project_plan@@.
Boundary rules, label definitions and agreement notes live here so the
overview stays readable.

What annotators actually see is published as assets: the definitions in
@@Assets/Ticket entity labels@@ and @@Assets/Ticket universal entity labels@@,
the boundary rules in @@Assets/Ticket entity guidelines@@. This page is the
reasoning behind them — change a rule here, republish the asset.

## Scope

Five domain labels are annotated by people. Three universal labels
(`ORG`, `MONEY`, `DATE`) are suggested by a pretrained pipeline in
@@Tasks/tickets-ner-agent-prelabel@@ and only corrected by hand — they are
generic enough for an off-the-shelf model and are not worth annotator time.

## Label definitions

| Label | Mark | Do not mark | Example |
|---|---|---|---|
| `PRODUCT` | A named product in the vendor's suite | Generic references: "the app", "the platform" | *Meridian Cloud*, *Meridian API* |
| `FEATURE` | A named capability inside a product | Verbs describing an action: "exporting", "logging in" | *CSV export*, *audit log* |
| `ERROR_CODE` | An error identifier, including HTTP statuses | Free-text error messages | *ERR-4032*, *HTTP 502* |
| `VERSION` | A release identifier of the vendor's own software | Version numbers of a customer's OS or browser | *v4.0.2*, *2026.8.1* |
| `INTEGRATION` | A third-party service the product connects to | The same company named as the *customer* | *Slack*, *Okta* |
| `ORG` | The customer's company | The vendor's own name | *Northwind Logistics* |
| `MONEY` | A monetary amount | Seat counts, quantities | *$1,200* |
| `DATE` | An absolute or relative date | Durations: "for three weeks" | *August 14*, *last Tuesday* |

The examples use Meridian, the fictional vendor of the sample tickets. Replace
them with your own product names.

## Distribution in the gold set

Once @@Datasets/support-ner-gold@@ is adjudicated, record the number of spans
per label here. Expect `INTEGRATION` to be the thinnest label and the one where
the LLM draft is weakest, because the same company name can be a customer
(`ORG`) or a connected service (`INTEGRATION`) depending on the sentence.

## Boundary rules

- **Shortest span that fully names the entity.** *Meridian Cloud*, not
  *the Meridian Cloud dashboard*.
- **Determiners stay out.** *the billing portal* is annotated as *billing portal*.
- **A product name inside a feature name wins as `PRODUCT`.** Nested spans are
  not supported by the manual NER interface; if the annotation genuinely needs
  to nest, it belongs in a span-categorization task instead.
- **Customer vs. integration is decided by role in the sentence**, not by the
  company. "our team at Spotify" is `ORG`; "syncing to Spotify" is `INTEGRATION`.

## Agreement

Measure agreement per label on an overlap sample (e.g. 40 examples annotated by
two people), and record it here:

| Label | Agreement | Main source of disagreement |
|---|---|---|
| `PRODUCT` | | |
| `ERROR_CODE` | | |
| `VERSION` | | |
| `FEATURE` | | |
| `INTEGRATION` | | |

`FEATURE` and `INTEGRATION` are where boundary disagreements usually show up;
the determiner rule and the customer/integration rule above address them.

## Adjudication

Conflicts between the human pass and the pre-labelling pass are resolved here:

@@Tasks/tickets-ner-review@@

## Decision Log

- **Nested spans**: Not supported in this scheme. _Rationale: the manual NER interface cannot express them, and splitting into a second span task costs more than the nesting is worth here._
- **Universal entity types split out**: `ORG`, `MONEY` and `DATE` are pre-labelled in a separate task rather than mixed into the human pass. _Rationale: they are solved by an existing pipeline, and mixing them in triples the spans per screen for no gain in model quality._
- **Determiners excluded from spans**: _Rationale: the trained model should not learn to include "the", and it's a common source of boundary disagreement._
- **`INTEGRATION` kept as its own label** rather than folded into `ORG`. _Rationale: routing depends on knowing which third-party system is involved; collapsing the two loses the signal that matters downstream._
