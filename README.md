<a href="https://explosion.ai"><img src=".github/explosion.svg" width="100" alt="Explosion" align="right" /></a>

# Ellf Templates

This repository contains a collection of project templates for [Ellf](https://ellf.ai), our new tool platform for agentic NLP development. Templates make it easy to get started by setting up end-to-end workflows and adapt them for different use cases. For more details, see the [templates documentation](https://ellf.ai/docs/templates).

> ✨ **Try Ellf:** Read more and sign up for a free trial [here](https://ellf.ai)!

To use a template, run the [`ellf-template`](https://ellf.ai/docs/modules#templates) skill in your coding assistant like Claude Code and point it to the URL or a local directory of the template you want to use. Ellf will then take care of the rest and set up everything you need to run the project:

```bash
# Your coding agent, e.g. Claude Code
/ellf-template Set up this project: https://github.com/explosion/ellf-templates/tree/main/helpdesk-routing
```

The template documents what's needed to adapt it to your custom use case and data, and your coding agent will ask any required follow-up questions. If you prefer doing it manually, you can run the CLI commands included with the template.

You can also use `ellf-template` to [export](https://ellf.ai/docs/templates#create) any existing Ellf project to a reusable template to share your workflows with others or adapt them for different use cases. To contribute a template you've built, [get in touch](mailto:[[EMAIL]]?subject=Ellf%20Templates).

## Templates

### [Helpdesk Routing with Jev](helpdesk-routing)

Find out whether Jev is good enough to route IT support tickets to the right technician by problem area. Settles the label scheme in a pilot with a Gemini second opinion, builds a human-labelled evaluation set with an agreement check and a blind slip check, scores Jev against a bar agreed in advance, and sets up daily routing with a monthly problem-area report.

| Use cases | Tasks | Actions | Agents | Plans | Sample data | API keys |
| --- | :---: | :---: | :---: | :---: | :---: | --- |
| Text Classification, Evaluation | 9 | 3 | 1 | 4 | ✓ | Google AI, TypeSafe |

---

_The list is kept in sync with [`templates.json`](templates.json), the source of truth for template metadata._
