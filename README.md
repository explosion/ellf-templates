<a href="https://explosion.ai"><img src="https://explosion.ai/assets/img/logo.svg" width="125" height="125" align="right" alt="Explosion" /></a>

# Ellf Templates

This repository contains a collection of project templates for [Ellf](https://ellf.ai), our new tool platform for agentic NLP development. Templates make it easy to get started by setting up end-to-end workflows and adapt them for different use cases. For more details, see the [templates documentation](https://ellf.ai/docs/templates).

> ✨ **Try Ellf:** Read more and sign up for a free trial [here](https://ellf.ai)!

To use a template, run the [`ellf-template`](https://ellf.ai/docs/modules#templates) skill in your coding assistant like Claude Code and point it to the URL or a local directory of the template you want to use. Ellf will then take care of the rest and set up everything you need to run the project:

```bash
# Your coding agent, e.g. Claude Code
/ellf-template Set up this project: https://github.com/explosion/ellf-templates/tree/main/helpdesk-routing
```

The template documents what's needed to adapt it to your custom use case and data, and your coding agent will ask any required follow-up questions and ask you for confirmation before creating anything. If you prefer doing it manually, you can run the CLI commands included with the template. Once all resources are created in the platform, the agent will make a final pass over the project plans, update the `@@` placeholders with the correct links and update the plans to reflect any modifications you made.

You can also use `ellf-template` to [export](https://ellf.ai/docs/templates#create) any existing Ellf project to a reusable template to share your workflows with others or adapt them for different use cases. To contribute a template you've built, [get in touch](mailto:contact@explosion.ai?subject=Ellf%20Templates).

## Templates

### [Replacing an LLM Classifier with Jev](llm-to-jev)

Evaluate moving an LLM-based classifier to Jev, which answers with calibrated probabilities instead of text, and carry the move out. Compares Jev with the LLM on past records, has a person annotate a blind sample of disagreements and random records in about an hour, uses the annotations to add rules and choose per-label thresholds, and exports a configuration to run Jev in production, with optional checks for drift.

**Use cases:** Text Classification, Evaluation

| Tasks | Actions | Plans | API keys |
| :---: | :---: | :---: | --- |
| 2 | 3 | 1 | TypeSafe |

### [Helpdesk Routing with Jev](helpdesk-routing)

Find out whether Jev is good enough to route IT support tickets to the right technician by problem area. Settles the label scheme in a pilot with a Gemini second opinion, builds a human-labelled evaluation set with an agreement check and a blind slip check, scores Jev against a bar agreed in advance, and sets up daily routing with a monthly problem-area report.

**Use cases:** Text Classification, Evaluation

| Tasks | Actions | Agents | Plans | Sample data | API keys |
| :---: | :---: | :---: | :---: | :---: | --- |
| 9 | 3 | 1 | 4 | ✓ | Google AI, TypeSafe |

### [Support Ticket Insights](support-insights)

Extract products, features, error codes, versions and integrations from customer support tickets and route each ticket to the right queue. An LLM drafts the entity annotations, people curate them, a pretrained pipeline suggests the generic entity types, and the passes are adjudicated into a gold set that trains a custom spaCy NER pipeline and a separate routing classifier.

**Use cases:** Information Extraction, Text Classification, LLM Distillation, Evaluation

| Tasks | Actions | Agents | Services | Plans | Sample data | API keys |
| :---: | :---: | :---: | :---: | :---: | :---: | --- |
| 8 | 6 | 1 | 2 | 4 | ✓ | Google AI |

### [GitHub Docs Issue Classifier](github-docs-issues)

Train a binary text classifier that predicts whether a GitHub issue is about documentation. Annotate a single label with accept or reject on the included GitHub issues or your own, then train a spaCy pipeline on the answers.

**Use cases:** Getting Started, Text Classification

| Tasks | Actions | Plans | Sample data |
| :---: | :---: | :---: | :---: |
| 1 | 1 | 1 | ✓ |

### [Food Ingredient Extraction](food-ingredients-ner)

Train a named entity recognizer that finds food ingredients in cooking comments from Reddit or your own texts. Highlight ingredients with match patterns as suggestions, train a quick first model on CPU and a more accurate transformer-based pipeline on GPU, and optionally correct the first model's suggestions in a second round and check the annotations in a dashboard.

**Use cases:** Getting Started, Information Extraction, Named Entity Recognition

| Tasks | Actions | Services | Plans | GPU | Sample data |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 2 | 2 | 1 | 1 | ✓ | ✓ |

---

_The list is kept in sync with [`templates.json`](templates.json), the source of truth for template metadata._
