# Databricks notebook source
# MAGIC %md
# MAGIC # 0 · Ingest from Google Drive with Lakeflow Connect
# MAGIC
# MAGIC One managed **Lakeflow Connect** pipeline ingests the raw data from Google Drive: each CSV in
# MAGIC `structured/` becomes a Delta table, and the PDFs in `unstructured/` land in the `contracts` volume.
# MAGIC Continue with `1_metric-views/1_CreateMetricView` and `3_agent-bricks/1_CreateContractSearch`.
# MAGIC
# MAGIC > The Google Drive connector is in preview and `format: FILE` is Beta (`PREVIEW` channel).

# COMMAND ----------

# MAGIC %md
# MAGIC ### Before you start
# MAGIC
# MAGIC 1. A Drive folder with `structured/` (the 7 CSVs of the [Kaggle retail star-schema dataset](https://www.kaggle.com/datasets/shrinivasv/retail-store-star-schema-dataset))
# MAGIC    and `unstructured/` (the four fictional agency contract PDFs, `fictional_*.pdf`).
# MAGIC 2. A **Google Drive** UC connection (Catalog Explorer → External data → Connections; one-time OAuth sign-in).
# MAGIC 3. Paste the two subfolder URLs and the connection name into the widgets.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Parameters
# MAGIC
# MAGIC `CATALOG_NAME` (`workspace`), `SCHEMA_NAME` (`marketing_campaign`), `CONNECTION_NAME`,
# MAGIC `STRUCTURED_FOLDER_URL`, `UNSTRUCTURED_FOLDER_URL`, `VOLUME_NAME` (`contracts`, which stage 3
# MAGIC expects), `PIPELINE_NAME` (`marketing_campaign_gdrive_ingestion`).

# COMMAND ----------

dbutils.widgets.text("CATALOG_NAME", "workspace", "CATALOG_NAME — Unity Catalog catalog for demo objects")
dbutils.widgets.text("SCHEMA_NAME", "marketing_campaign", "SCHEMA_NAME — schema inside the catalog")
dbutils.widgets.text("CONNECTION_NAME", "", "CONNECTION_NAME — Google Drive UC connection")
dbutils.widgets.text("STRUCTURED_FOLDER_URL", "", "STRUCTURED_FOLDER_URL — Drive folder with the CSVs")
dbutils.widgets.text("UNSTRUCTURED_FOLDER_URL", "", "UNSTRUCTURED_FOLDER_URL — Drive folder with the PDFs")
dbutils.widgets.text("VOLUME_NAME", "contracts", "VOLUME_NAME — UC volume for the contract PDFs")
dbutils.widgets.text("PIPELINE_NAME", "marketing_campaign_gdrive_ingestion", "PIPELINE_NAME — ingestion pipeline name")

CATALOG_NAME = dbutils.widgets.get("CATALOG_NAME")
SCHEMA_NAME = dbutils.widgets.get("SCHEMA_NAME")
CONNECTION_NAME = dbutils.widgets.get("CONNECTION_NAME").strip()
STRUCTURED_FOLDER_URL = dbutils.widgets.get("STRUCTURED_FOLDER_URL").strip()
UNSTRUCTURED_FOLDER_URL = dbutils.widgets.get("UNSTRUCTURED_FOLDER_URL").strip()
VOLUME_NAME = dbutils.widgets.get("VOLUME_NAME")
PIPELINE_NAME = dbutils.widgets.get("PIPELINE_NAME")

for name, value in [("CONNECTION_NAME", CONNECTION_NAME),
                    ("STRUCTURED_FOLDER_URL", STRUCTURED_FOLDER_URL),
                    ("UNSTRUCTURED_FOLDER_URL", UNSTRUCTURED_FOLDER_URL)]:
    assert value, f"Set the {name} widget (see 'Before you start' above)."

VOLUME_PATH = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{VOLUME_NAME}/"
print("Target schema :", f"{CATALOG_NAME}.{SCHEMA_NAME}")
print("PDF volume    :", VOLUME_PATH)
print("Connection    :", CONNECTION_NAME)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create Schema and Volume
# MAGIC
# MAGIC The volume must exist before the pipeline runs; the connector writes the PDFs into it.

# COMMAND ----------

# Only create the catalog when it is missing: CREATE CATALOG IF NOT EXISTS still needs the
# metastore-level CREATE CATALOG privilege, even for a catalog that already exists.
existing_catalogs = {r[0] for r in spark.sql("SHOW CATALOGS").collect()}
if CATALOG_NAME not in existing_catalogs:
    spark.sql(f"CREATE CATALOG {CATALOG_NAME}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG_NAME}.{SCHEMA_NAME}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG_NAME}.{SCHEMA_NAME}.{VOLUME_NAME}")
print("Schema and volume are ready.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Define the Pipeline
# MAGIC
# MAGIC One object per destination table. CSVs: a `path_filter` picks the file and `schema_hints` pin key,
# MAGIC date and amount types so the metric view joins stay stable. PDFs: `format: FILE` stores the bytes
# MAGIC in the volume and `contract_files` maps generated ids to original names (used in stage 3).

# COMMAND ----------

SCHEMA_HINTS = {
    "dim_campaigns": "campaign_sk INT, start_date_sk INT, end_date_sk INT, campaign_budget INT",
    "dim_customers": "customer_sk INT",
    "dim_dates": "full_date DATE, date_sk INT, year INT, month INT, day INT, weekday INT, quarter INT",
    "dim_products": "product_sk INT",
    "dim_salespersons": "salesperson_sk INT",
    "dim_stores": "store_sk INT, store_manager_sk INT",
    "fact_sales_normalized": (
        "sales_sk INT, customer_sk INT, product_sk INT, store_sk INT, salesperson_sk INT, "
        "campaign_sk INT, sales_date TIMESTAMP, total_amount DOUBLE"
    ),
}

def csv_object(table, hints):
    return {"table": {
        "destination_catalog": CATALOG_NAME,
        "destination_schema": SCHEMA_NAME,
        "destination_table": table,
        "connector_options": {"gdrive_options": {
            "entity_type": "FILE",
            "url": STRUCTURED_FOLDER_URL,
            "file_ingestion_options": {
                "format": "CSV",
                "schema_evolution_mode": "NONE",
                "file_filters": [{"path_filter": f"*{table}.csv"}],
                "schema_hints": hints,
                "format_options": {"header": "true"},
            },
        }},
    }}

pdf_object = {"table": {
    "destination_catalog": CATALOG_NAME,
    "destination_schema": SCHEMA_NAME,
    "destination_table": "contract_files",
    "table_configuration": {"table_properties": {"databricks.filespace-preview": VOLUME_PATH}},
    "connector_options": {"gdrive_options": {
        "entity_type": "FILE",
        "url": UNSTRUCTURED_FOLDER_URL,
        "file_ingestion_options": {
            "format": "FILE",
            "schema_evolution_mode": "NONE",
            "file_filters": [{"path_filter": "*.pdf"}],
        },
    }},
}}

pipeline_spec = {
    "name": PIPELINE_NAME,
    "channel": "PREVIEW",          # required for format FILE (Beta)
    "catalog": CATALOG_NAME,
    "schema": SCHEMA_NAME,
    "ingestion_definition": {
        "connection_name": CONNECTION_NAME,
        "objects": [csv_object(t, h) for t, h in SCHEMA_HINTS.items()] + [pdf_object],
    },
}
print(f"{len(pipeline_spec['ingestion_definition']['objects'])} objects defined")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create (or Update) and Run the Pipeline
# MAGIC
# MAGIC Looked up by name, so re-runs update it. Schedule it with a Lakeflow Job to keep Drive in sync.

# COMMAND ----------

import time
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

existing = [p for p in w.pipelines.list_pipelines(filter=f"name LIKE '{PIPELINE_NAME}'")
            if p.name == PIPELINE_NAME]
if existing:
    PIPELINE_ID = existing[0].pipeline_id
    w.api_client.do("PUT", f"/api/2.0/pipelines/{PIPELINE_ID}",
                    body={**pipeline_spec, "id": PIPELINE_ID})
    print("Updated pipeline", PIPELINE_ID)
else:
    PIPELINE_ID = w.api_client.do("POST", "/api/2.0/pipelines", body=pipeline_spec)["pipeline_id"]
    print("Created pipeline", PIPELINE_ID)

host = w.config.host.rstrip("/")
print(f"Pipeline UI: {host}/pipelines/{PIPELINE_ID}")

update_id = w.pipelines.start_update(pipeline_id=PIPELINE_ID).update_id
print("Started update", update_id, "(first run usually takes a few minutes)...")
while True:
    state = w.pipelines.get_update(pipeline_id=PIPELINE_ID, update_id=update_id).update.state.value
    if state in ("COMPLETED", "FAILED", "CANCELED"):
        break
    time.sleep(20)
print("Update finished with state:", state)
assert state == "COMPLETED", f"Pipeline update {state}. Open the pipeline UI above and check the event log."

# COMMAND ----------

# MAGIC %md
# MAGIC ### Verify

# COMMAND ----------

for table in SCHEMA_HINTS:
    fqn = f"{CATALOG_NAME}.{SCHEMA_NAME}.{table}"
    print(f"  {fqn}: {spark.table(fqn).count():,} rows")

# The connector stores each PDF in the volume under a generated id; the
# contract_files table maps it back to the original Drive file name.
display(spark.sql(f"""
  SELECT _file_metadata.file_name AS file_name, file.uri AS volume_path, size
  FROM {CATALOG_NAME}.{SCHEMA_NAME}.contract_files
  ORDER BY file_name
"""))
