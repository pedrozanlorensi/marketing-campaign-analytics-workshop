# Genie — Natural Language Analytics

Stage 2 of [Marketing Campaign Analytics](../README.md). Deploys a **Genie space**
on top of the metric view from stage 1, then validates queries via the Genie API.

Read [`docs/genie-best-practices.md`](docs/genie-best-practices.md) for curation,
testing, and governance guidance before handing the space to end users.

## Prerequisites

- Stage 1 complete — `sales_relationships` metric view exists.
- A **SQL Warehouse** (note the warehouse id from the workspace URL).
- Permissions to create Genie spaces.

## Notebooks

Run in order:

| # | Notebook | Purpose |
| --- | --- | --- |
| 0 | [`0_CreateGenieSpace.ipynb`](0_CreateGenieSpace.ipynb) | Deploy serialized Genie space from template |
| 1 | [`1_QueryGenieSpace.ipynb`](1_QueryGenieSpace.ipynb) | Query the space via Genie Conversation API |

**Parameters:** `CATALOG_NAME`, `SCHEMA_NAME`, `warehouse_id`, `GENIE_SPACE_ID`

> **Important:** Copy the **Genie Space id** printed by notebook `0` — stage 3
> ([`3_agent-bricks`](../3_agent-bricks/)) needs it for the Supervisor Agent.

## Templates

| File | Purpose |
| --- | --- |
| [`genie_space/genie_space.json`](genie_space/genie_space.json) | Serialized Genie space (instructions, tables, example questions) |

## Next step

Continue to [`3_agent-bricks/`](../3_agent-bricks/) to add contract retrieval and
a Supervisor Agent on top of this Genie space.
