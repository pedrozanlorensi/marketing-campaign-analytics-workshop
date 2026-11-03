# Agent Bricks — Vector Search Retriever & Agent Bricks CLI Agent

Stage 3 of [Marketing Campaign Analytics](../README.md). Builds a **Vector Search**
index over fictional contract PDFs, exposes it as a **Unity Catalog function** tool, and
deploys a code-first agent with the **[Agent Bricks CLI](https://docs.databricks.com/aws/en/agents/quickstart)**
(`databricks-agentbricks`) that combines it with the **Genie space** from stage 2.

The agent lives in [`agent/`](agent/): a LangGraph project scaffolded by `agentbricks init`.
`agent/agent.toml` declares its managed resources (tools, memory, sessions, tracing), and
`agentbricks deploy` provisions them and runs the agent on the Databricks agent runtime, with
a built-in chat UI.

> **Agent Bricks CLI is in Beta.** No workspace setting is required.

## Prerequisites

- Stages 1–2 complete (metric view + Genie space).
- **Vector Search** and an **embedding model** endpoint (`databricks-gte-large-en` by default).
- Import the repo folder `3_agent-bricks/` to your workspace so `./contracts` sits next to notebook `0`
  before running it (or land the PDFs with [`0_lakeflow-connect/`](../0_lakeflow-connect/) and skip notebook `0`).
- For the agent, a terminal (your laptop, or a Databricks web terminal) with the
  [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install), Python 3.11+ and
  [`uv`](https://docs.astral.sh/uv/), then:

  ```bash
  uv tool install --python 3.12 databricks-agentbricks
  ```

**Sample contracts** (in `contracts/`):

| File | Type |
| --- | --- |
| `fictional_marketing_services_echo.pdf` | Marketing services — Echo Podcast & Audio Network |
| `fictional_marketing_services_prism_web.pdf` | Marketing services — Prism Web & UX Studio |
| `fictional_marketing_services_pulse_digital.pdf` | Marketing services — Pulse Digital Media Group |
| `fictional_service_agreement_sentinel_security.pdf` | Service agreement — Sentinel Retail Security Group |

## What gets created

| Resource | Name (default) | Description |
| --- | --- | --- |
| Volume | `<CATALOG>.<SCHEMA>.contracts` | Contract PDFs |
| Delta table | `<CATALOG>.<SCHEMA>.contract_chunks` | Search-ready contract chunks from `ai_prep_search` (CDF enabled) |
| Vector Search endpoint | `marketing_campaign_vs` | Serves the index |
| Vector Search index | `<CATALOG>.<SCHEMA>.contract_chunks_index` | Managed-embedding Delta Sync index |
| UC function | `<CATALOG>.<SCHEMA>.search_contracts` | Contract search tool (`vector_search()` over the index) |
| Databricks App | `agent-bricks-marketing-agent` | The deployed agent, with its own service principal and chat UI |
| Memory / session stores | `marketing-agent-<suffix>-memory` / `-sessions` | Managed stores declared in `agent.toml` |
| MLflow experiment | `/Shared/agentbricks_traces/marketing-agent-<suffix>` | Agent traces |

## Steps

| # | Where | What |
| --- | --- | --- |
| 0 | [`0_ImportContractsToVolume.ipynb`](0_ImportContractsToVolume.ipynb) | Copy `contracts/*.pdf` → Unity Catalog volume (skip if you used Lakeflow Connect) |
| 1 | [`1_CreateVectorSearchIndex.ipynb`](1_CreateVectorSearchIndex.ipynb) | `ai_parse_document` + `ai_prep_search` → chunks → Delta → Vector Search index |
| 2 | [`2_QueryVectorSearchIndex.ipynb`](2_QueryVectorSearchIndex.ipynb) | Similarity-search test |
| 3 | [`3_CreateContractSearchTool.ipynb`](3_CreateContractSearchTool.ipynb) | Create the `search_contracts` UC function; prints the `agentbricks` commands with your Genie space id |
| — | Terminal, in [`agent/`](agent/) | Bind the tools and deploy (below) |
| 4 | [`4_GrantAgentAccess.ipynb`](4_GrantAgentAccess.ipynb) | Grant the agent's service principal access to Genie, the warehouse, the tables, the function, and the index |

### Bind the tools and deploy the agent

From the `3_agent-bricks/agent` folder (notebook `3` prints these with your values):

```bash
databricks auth login --host https://<your-workspace-url> --profile <profile>
agentbricks login --profile <profile>

agentbricks tools add genie-agent <GENIE_SPACE_ID> --name sales_analytics --auth app
agentbricks tools add uc-function <CATALOG>.<SCHEMA>.search_contracts --name search_contracts --auth app

agentbricks deploy            # first deploy takes ~3 minutes
```

Then run notebook `4`, and try the agent in its chat UI (the app URL printed by `deploy`) or with:

```bash
agentbricks endpoint invoke agent-bricks-marketing-agent --path /api/invocations \
  --json '{"id": "'$(uuidgen)'", "session_id": "'$(uuidgen)'",
           "input": {"messages": [{"role": "user", "content": "What are my top 5 campaigns by total sales?"}]}}'
```

To iterate locally before deploying, run `agentbricks dev` (local chat UI on port 8000; memory
and session stores only connect after deploy).

**Key parameters:** `CATALOG_NAME` (default `workspace`), `SCHEMA_NAME`, `CONTRACTS_SOURCE_PATH` (`./contracts`),
`VS_ENDPOINT_NAME`, `INDEX_NAME`, `FUNCTION_NAME`, `GENIE_SPACE_TITLE` (resolves the Genie space id), `AGENT_APP_NAME`

> **Next step:** deploy the custom chat app in [`4_apps/`](../4_apps/), which calls this agent.

## How the pieces reach the agent

```
contract PDFs (volume)
   └─ ai_parse_document → ai_prep_search  (OCR + RAG-ready chunks)
        └─ Delta table (CDF)
             └─ Vector Search Delta Sync index  (managed gte-large-en embeddings on chunk_to_embed)
                  └─ UC function search_contracts(query)  (vector_search() SQL function)
                       └─ agent.toml tool: uc_function, auth = app ─┐
Genie space (stage 2) ── agent.toml tool: genie_agent, auth = app ──┴─ LangGraph agent (agent/agent.py)
                                                                        └─ agentbricks deploy → agent-bricks-marketing-agent
```

The agent's routing instructions (`SYSTEM_PROMPT` in [`agent/agent/agent.py`](agent/agent/agent.py))
send analytics questions to Genie and contract questions to `search_contracts`.

## Directory structure

```
3_agent-bricks/
├── 0_ImportContractsToVolume.ipynb
├── 1_CreateVectorSearchIndex.ipynb
├── 2_QueryVectorSearchIndex.ipynb
├── 3_CreateContractSearchTool.ipynb
├── 4_GrantAgentAccess.ipynb
├── agent/              # Agent Bricks CLI project (agent.toml, agent/agent.py, chat UI)
├── contracts/          # Four fictional sample PDFs (fictional_*.pdf)
└── README.md
```
