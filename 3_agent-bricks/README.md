# Agent Bricks — Vector Search Retriever & Supervisor Agent

Stage 3 of [Marketing Campaign Analytics](../README.md). Builds a **Vector Search**
index over fictional contract PDFs and wraps it — together with the **Genie
space** from stage 2 — inside a **Supervisor Agent** on Databricks Agent Bricks.

> **Why Vector Search instead of a Knowledge Assistant?**
> Databricks **Free Edition does not include Knowledge Assistant**. A Supervisor
> Agent can still perform document retrieval by attaching a **Vector Search
> index** directly as a native tool (`tool_type = "vector_search_index"`). This
> stage builds that index, so the demo runs end-to-end on Free Edition (and on
> any workspace).

## Prerequisites

- Stages 1–2 complete (metric view + Genie space).
- The **Genie space title** (`Marketing Campaign Analytics — Genie Space`) from [`2_genie/0_CreateGenieSpace.ipynb`](../2_genie/0_CreateGenieSpace.ipynb) — the Supervisor notebook auto-finds the space by title, no id copy-paste needed.
- **Vector Search** and **Supervisor Agents** available (both work on Free Edition).
- An **embedding model** endpoint — `databricks-gte-large-en` is used by default.
- Import the repo folder `3_agent-bricks/` to your workspace so `./contracts` sits next to notebook `0` before running it.

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
| Volume | `<CATALOG>.<SCHEMA>.contracts` | Extracted contract PDFs |
| Delta table | `<CATALOG>.<SCHEMA>.contract_chunks` | Search-ready contract chunks from `ai_prep_search` (CDF enabled) |
| Vector Search endpoint | `marketing_campaign_vs` | Serves the index |
| Vector Search index | `<CATALOG>.<SCHEMA>.contract_chunks_index` | Managed-embedding Delta Sync index |
| Supervisor Agent | `Marketing Campaign Insights Supervisor` | Routes the Vector Search index + Genie |

## Notebooks

| # | Notebook | Purpose |
| --- | --- | --- |
| 0 | [`0_ImportContractsToVolume.ipynb`](0_ImportContractsToVolume.ipynb) | Copy `contracts/*.pdf` → Unity Catalog volume |
| 1 | [`1_CreateVectorSearchIndex.ipynb`](1_CreateVectorSearchIndex.ipynb) | `ai_parse_document` + `ai_prep_search` → chunks → Delta → Vector Search index |
| 2 | [`2_QueryVectorSearchIndex.ipynb`](2_QueryVectorSearchIndex.ipynb) | Similarity-search test |
| 3 | [`3_CreateSupervisorAgent.ipynb`](3_CreateSupervisorAgent.ipynb) | Supervisor over the Vector Search index + Genie |
| 4 | [`4_QuerySupervisorAgent.ipynb`](4_QuerySupervisorAgent.ipynb) | Query Supervisor endpoint |

**Key parameters:** `CATALOG_NAME` (default `workspace`), `SCHEMA_NAME`, `CONTRACTS_SOURCE_PATH` (`./contracts`), `GENIE_SPACE_TITLE` (auto-resolves the Genie space id), `VS_ENDPOINT_NAME`, `INDEX_NAME`, `SUPERVISOR_NAME`

> **Next step:** deploy the custom chat app in [`4_apps/`](../4_apps/).

## How the retriever reaches the agent

```
contract PDFs (volume)
   └─ ai_parse_document → ai_prep_search  (OCR + RAG-ready chunks)
        └─ Delta table (CDF)
             └─ Vector Search Delta Sync index  (managed gte-large-en embeddings on chunk_to_embed)
                  └─ Supervisor Agent tool (tool_type = "vector_search_index")
```

## Directory structure

```
3_agent-bricks/
├── 0_ImportContractsToVolume.ipynb
├── 1_CreateVectorSearchIndex.ipynb
├── 2_QueryVectorSearchIndex.ipynb
├── 3_CreateSupervisorAgent.ipynb
├── 4_QuerySupervisorAgent.ipynb
├── contracts/          # Four fictional sample PDFs (fictional_*.pdf)
└── README.md
```
