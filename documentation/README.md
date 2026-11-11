# MomBoard documentation

What changed in each release is in [`../CHANGELOG.md`](../CHANGELOG.md). Start with
[`../README.md`](../README.md) for what MomBoard is and how to run it locally.

## Deployment and operations

| Doc | Read it when |
|---|---|
| [`deployment/agent-deployment.md`](deployment/agent-deployment.md) | A coding agent (or you) must turn a checkout into a verified deployment. The canonical runbook. |
| [`deployment/deploy.md`](deployment/deploy.md) | Running on Fly.io: create, back up, restore, roll back, move to PostgreSQL. |
| [`deployment/demo.md`](deployment/demo.md) | Standing up an internal demo on SQLite and getting conversations into it. |
| [`deployment/local-llm.md`](deployment/local-llm.md) | Running the models locally with Ollama instead of OpenAI or Bedrock. |
| [`deployment/mcp.md`](deployment/mcp.md) | Letting Claude read MomBoard over MCP with API tokens: switching it on, privacy, tokens, networking, audit. |

## Guides

| Doc | Read it when |
|---|---|
| [`guides/tagger-evaluation.md`](guides/tagger-evaluation.md) | Measuring the tagger against a hand-tagged test set. |
| [`guides/matching-evaluation.md`](guides/matching-evaluation.md) | Checking hypothesis matching against beliefs you know are in the data. |
| [`guides/retag-rollout.md`](guides/retag-rollout.md) | Retagging the library in stages, with gates and a way back. |

## Design

| Doc | What it covers |
|---|---|
| [`design/principles.md`](design/principles.md) | The principles and risks behind the product. |
| [`design/architecture.md`](design/architecture.md) | The original v0.1 architecture and data model. |
| [`design/T46-insight-mcp-surface.md`](design/T46-insight-mcp-surface.md) | The read-only insight tools exposed over MCP. |
| [`design/T48-evidence-gated-intake.md`](design/T48-evidence-gated-intake.md) | Evidence-gated hypothesis intake. |

The `docs/` folder at the repo root is the public GitHub Pages site (`index.html`, `CNAME`). Documents
live here, in `documentation/`, so they are not published with it.
