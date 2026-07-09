# Agent Bricks — Vector Search Retriever & Supervisor Agent

Stage 3 of [Retail Campaign Analytics](../README.md). Builds a **Vector Search**
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
- **Genie Space id** from [`2_genie/0_CreateGenieSpace.ipynb`](../2_genie/0_CreateGenieSpace.ipynb).
- **Vector Search** and **Supervisor Agents** available (both work on Free Edition).
- An **embedding model** endpoint — `databricks-gte-large-en` is used by default.
- `contracts.zip` uploaded to the `contracts` volume before running notebook `0`.

## What gets created

| Resource | Name (default) | Description |
| --- | --- | --- |
| Volume | `<CATALOG>.<SCHEMA>.contracts` | Extracted contract PDFs |
| Delta table | `<CATALOG>.<SCHEMA>.contract_chunks` | Chunked contract text (CDF enabled) |
| Vector Search endpoint | `retail_campaign_vs` | Serves the index |
| Vector Search index | `<CATALOG>.<SCHEMA>.contract_chunks_index` | Managed-embedding Delta Sync index |
| Supervisor Agent | `Retail Insights Supervisor` | Routes the Vector Search index + Genie |

## Notebooks

| # | Notebook | Purpose |
| --- | --- | --- |
| 0 | [`0_ImportContractsToVolume.ipynb`](0_ImportContractsToVolume.ipynb) | Zip → Unity Catalog volume |
| 1 | [`1_CreateVectorSearchIndex.ipynb`](1_CreateVectorSearchIndex.ipynb) | PDFs → chunks → Delta → Vector Search index |
| 2 | [`2_QueryVectorSearchIndex.ipynb`](2_QueryVectorSearchIndex.ipynb) | Similarity-search test |
| 3 | [`3_CreateSupervisorAgent.ipynb`](3_CreateSupervisorAgent.ipynb) | Supervisor over the Vector Search index + Genie |
| 4 | [`4_QuerySupervisorAgent.ipynb`](4_QuerySupervisorAgent.ipynb) | Query Supervisor endpoint |

**Key parameters:** `GENIE_SPACE_ID` (from stage 2), `VS_ENDPOINT_NAME`,
`INDEX_NAME`, `EMBEDDING_MODEL`, `SUPERVISOR_NAME`

> **Next step:** deploy the chat app in [`4_apps/`](../4_apps/).

## How the retriever reaches the agent

```
contract PDFs (volume)
   └─ chunk → Delta table (CDF)
        └─ Vector Search Delta Sync index  (managed gte-large-en embeddings)
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
├── contracts/          # Source PDFs (one per file)
├── contracts.zip       # Packaged for upload to the contracts volume
└── README.md
```
