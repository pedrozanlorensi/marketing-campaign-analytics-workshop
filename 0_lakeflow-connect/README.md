# Lakeflow Connect — Ingest from Google Drive

Optional stage 0 of [Marketing Campaign Analytics](../README.md). Ingests the demo's
**structured** data (the sales star-schema CSVs) and **unstructured** data (the contract PDFs)
from a Google Drive folder with the managed
[Lakeflow Connect Google Drive connector](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/google-drive),
instead of downloading from Kaggle (`1_metric-views/0_IngestData`) and copying PDFs from this
repo (`3_agent-bricks/0_ImportContractsToVolume`).

> **Release status:** the Google Drive connector is in preview, and landing raw files into a
> volume (`format: FILE`) is **Beta**, so the pipeline runs on the `PREVIEW` channel. Managed
> connectors need Unity Catalog and serverless compute; check availability before using this
> stage on Databricks Free Edition.

## Prerequisites

1. **A Google Drive folder with two subfolders:**

   ```
   <your Drive folder>/
   ├── structured/     dim_campaigns.csv, dim_customers.csv, dim_dates.csv, dim_products.csv,
   │                   dim_salespersons.csv, dim_stores.csv, fact_sales_normalized.csv
   └── unstructured/   the four fictional_*.pdf files from 3_agent-bricks/contracts/
   ```

   The CSVs come from the [Kaggle retail star-schema dataset](https://www.kaggle.com/datasets/shrinivasv/retail-store-star-schema-dataset)
   (`fact_sales_denormalized.csv` is not used).
2. **A Google Drive UC connection.** Catalog Explorer → External data → Connections →
   Create connection → **Google Drive**, then sign in with a Google account that can read the
   folder. See [Create a Google Drive connection](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/google-drive-connection).
3. `CREATE TABLE` on the target schema (or `CREATE SCHEMA` on the catalog) and `USE CONNECTION`
   on the connection.

## Notebook

### 0_IngestFromGoogleDrive

Creates one serverless ingestion pipeline with:

| Source (Drive) | Format | Destination |
| --- | --- | --- |
| `structured/<table>.csv` (one object per file) | `CSV` with `schema_hints` | Delta table `<CATALOG>.<SCHEMA>.<table>` |
| `unstructured/*.pdf` | `FILE` | Files in the `<CATALOG>.<SCHEMA>.contracts` volume, plus the `contract_files` table |

The `schema_hints` pin the key, date, and amount columns to the types the original
`0_IngestData` notebook inferred, so the metric view in stage 1 works unchanged. The connector
stores each PDF in the volume under a generated id; `contract_files` maps it to the original
file name, and `3_agent-bricks/1_CreateVectorSearchIndex` uses that mapping to keep contract
names in search results.

The pipeline is looked up by name, so re-running the notebook updates it instead of creating
a duplicate. Lakeflow Connect pipelines are triggered: schedule the pipeline with a Lakeflow
Job (`pipeline_task`) to keep the tables in sync with Drive.

**Parameters:** `CATALOG_NAME` (default `workspace`), `SCHEMA_NAME`, `CONNECTION_NAME`,
`STRUCTURED_FOLDER_URL`, `UNSTRUCTURED_FOLDER_URL`, `VOLUME_NAME` (default `contracts`), `PIPELINE_NAME`

> **Next step:** skip `1_metric-views/0_IngestData` and continue with
> [`1_metric-views/1_CreateMetricView`](../1_metric-views/1_CreateMetricView.ipynb). In stage 3,
> skip `0_ImportContractsToVolume`.
