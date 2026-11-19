# Databricks notebook source
# MAGIC %md
# MAGIC # 1 · Create the Contract Search (Vector Search + UC Function Tool)
# MAGIC
# MAGIC Builds the agent's document-retrieval tool. Free Edition has no Knowledge Assistant, so retrieval
# MAGIC uses **Vector Search**:
# MAGIC
# MAGIC 1. **`ai_parse_document`** runs layout analysis (and OCR for scanned pages) on each PDF,
# MAGIC    and **`ai_prep_search`** turns the result into search-ready chunks with a context-enriched
# MAGIC    `chunk_to_embed` field.
# MAGIC 2. The chunks go to a Delta table (change data feed on), synced into a **Delta Sync index** with
# MAGIC    managed embeddings.
# MAGIC 3. **`search_contracts(query)`**, a Unity Catalog function over the index, is the agent's tool. A UC
# MAGIC    function keeps retrieval governed: the agent can call it only with `EXECUTE` on it and `SELECT`
# MAGIC    on the index (notebook `4`).
# MAGIC
# MAGIC > `ai_prep_search` needs Databricks Runtime 18.2+ or serverless environment version 3+.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Define Parameters
# MAGIC
# MAGIC | Widget | Default | What it controls |
# MAGIC | --- | --- | --- |
# MAGIC | `CATALOG_NAME` / `SCHEMA_NAME` | `workspace` / `marketing_campaign` | Where the contracts volume, chunks, index, and function live. |
# MAGIC | `VOLUME_NAME` | `contracts` | Volume with the contract PDFs (landed by stage 0). |
# MAGIC | `SOURCE_TABLE` | `contract_chunks` | Delta table with the search-ready chunks. |
# MAGIC | `VS_ENDPOINT_NAME` / `INDEX_NAME` | `marketing_campaign_vs` / `contract_chunks_index` | Vector Search endpoint and index. |
# MAGIC | `EMBEDDING_MODEL` | `databricks-gte-large-en` | Managed embedding model. |
# MAGIC | `FUNCTION_NAME` / `NUM_RESULTS` | `search_contracts` / `5` | The UC function tool and chunks per search. |
# MAGIC | `GENIE_SPACE_TITLE` | `Marketing Campaign Analytics — Genie Space` | Used to print the `agentbricks` commands. |

# COMMAND ----------

dbutils.widgets.text("CATALOG_NAME", "workspace", "CATALOG_NAME — Unity Catalog catalog for demo objects")
dbutils.widgets.text("SCHEMA_NAME", "marketing_campaign", "SCHEMA_NAME — schema inside the catalog")
dbutils.widgets.text("VOLUME_NAME", "contracts", "VOLUME_NAME — UC volume with fictional_*.pdf contracts")
dbutils.widgets.text("SOURCE_TABLE", "contract_chunks", "SOURCE_TABLE — search-ready chunks table (CDF enabled)")
dbutils.widgets.text("VS_ENDPOINT_NAME", "marketing_campaign_vs", "VS_ENDPOINT_NAME — Vector Search endpoint name")
dbutils.widgets.text("INDEX_NAME", "contract_chunks_index", "INDEX_NAME — Vector Search index name")
dbutils.widgets.text("EMBEDDING_MODEL", "databricks-gte-large-en", "EMBEDDING_MODEL — managed embedding model endpoint")
dbutils.widgets.text("FUNCTION_NAME", "search_contracts", "FUNCTION_NAME — UC function tool name")
dbutils.widgets.text("NUM_RESULTS", "5", "NUM_RESULTS — chunks returned per search")
dbutils.widgets.text("GENIE_SPACE_TITLE", "Marketing Campaign Analytics — Genie Space", "GENIE_SPACE_TITLE — title used in 2_genie/0")

CATALOG_NAME = dbutils.widgets.get("CATALOG_NAME")
SCHEMA_NAME = dbutils.widgets.get("SCHEMA_NAME")
VOLUME_NAME = dbutils.widgets.get("VOLUME_NAME")
SOURCE_TABLE = dbutils.widgets.get("SOURCE_TABLE")
VS_ENDPOINT_NAME = dbutils.widgets.get("VS_ENDPOINT_NAME")
INDEX_NAME = dbutils.widgets.get("INDEX_NAME")
EMBEDDING_MODEL = dbutils.widgets.get("EMBEDDING_MODEL")
FUNCTION_NAME = dbutils.widgets.get("FUNCTION_NAME")
NUM_RESULTS = int(dbutils.widgets.get("NUM_RESULTS"))
GENIE_SPACE_TITLE = dbutils.widgets.get("GENIE_SPACE_TITLE").strip()

VOLUME_PATH = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{VOLUME_NAME}"
SOURCE_TABLE_FQN = f"{CATALOG_NAME}.{SCHEMA_NAME}.{SOURCE_TABLE}"
INDEX_FQN = f"{CATALOG_NAME}.{SCHEMA_NAME}.{INDEX_NAME}"
FUNCTION_FQN = f"{CATALOG_NAME}.{SCHEMA_NAME}.{FUNCTION_NAME}"
print("Contracts volume :", VOLUME_PATH)
print("Chunks table     :", SOURCE_TABLE_FQN)
print("Index            :", INDEX_FQN)
print("Function         :", FUNCTION_FQN)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Parse + Chunk the Contracts in One Step
# MAGIC
# MAGIC `ai_parse_document` reads each PDF; `ai_prep_search` turns the parsed layout
# MAGIC into RAG-ready chunks — automatically splitting content, dropping boilerplate,
# MAGIC and enriching each chunk with document context (title, section, page, etc.).
# MAGIC
# MAGIC The result is a clean Delta table with one row per chunk:
# MAGIC - `id` — unique chunk id (used as the Vector Search primary key)
# MAGIC - `chunk_to_embed` — context-enriched text we embed for similarity search
# MAGIC - `chunk_to_retrieve` — raw chunk text returned to the agent at query time
# MAGIC - `source_uri` — the contract file name
# MAGIC
# MAGIC Change Data Feed (CDF) is enabled so the Delta Sync index can track updates.

# COMMAND ----------

spark.sql(f'CREATE SCHEMA IF NOT EXISTS {CATALOG_NAME}.{SCHEMA_NAME}')

# If the PDFs were landed by Lakeflow Connect (0_lakeflow-connect), the volume holds them
# under generated ids; the connector's contract_files table maps each one back to its
# original file name. Otherwise the volume file name is already the contract name.
# The inner join keeps only files the connector currently tracks: after a full refresh, older
# copies can remain in the volume under ids that contract_files no longer references.
CONTRACT_FILES_FQN = f"{CATALOG_NAME}.{SCHEMA_NAME}.contract_files"
if spark.catalog.tableExists(CONTRACT_FILES_FQN):
    files_source = f"""
    SELECT m._file_metadata.file_name AS file_name, f.content
    FROM READ_FILES('{VOLUME_PATH}/', format => 'binaryFile') f
    JOIN {CONTRACT_FILES_FQN} m ON m.file.uri = f.path"""
else:
    files_source = f"""
    SELECT regexp_extract(path, '([^/]+)$', 1) AS file_name, content
    FROM READ_FILES('{VOLUME_PATH}/', format => 'binaryFile')"""

spark.sql(f"""
CREATE OR REPLACE TABLE {SOURCE_TABLE_FQN} AS
WITH files AS ({files_source}
),
parsed_documents AS (
  SELECT file_name, ai_parse_document(content) AS parsed
  FROM files
),
prepped_documents AS (
  SELECT file_name, ai_prep_search(parsed) AS result
  FROM parsed_documents
)
SELECT
  chunk.value:chunk_id::STRING              AS id,
  chunk.value:chunk_position::INT           AS chunk_position,
  chunk.value:chunk_to_retrieve::STRING     AS chunk_to_retrieve,
  chunk.value:chunk_to_embed::STRING        AS chunk_to_embed,
  file_name                                 AS source_uri
FROM prepped_documents,
     LATERAL variant_explode(prepped_documents.result:document.contents) AS chunk
""")

spark.sql(f'ALTER TABLE {SOURCE_TABLE_FQN} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)')

cnt = spark.table(SOURCE_TABLE_FQN).count()
print(f'Wrote {cnt} search-ready chunks to {SOURCE_TABLE_FQN}')
display(spark.sql(f'SELECT source_uri, chunk_position, chunk_to_retrieve FROM {SOURCE_TABLE_FQN} ORDER BY source_uri, chunk_position LIMIT 8'))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create the Vector Search Endpoint

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.vectorsearch import (
    EndpointType, VectorIndexType, PipelineType,
    DeltaSyncVectorIndexSpecRequest, EmbeddingSourceColumn,
)

w = WorkspaceClient()

existing = [e.name for e in w.vector_search_endpoints.list_endpoints()]
if VS_ENDPOINT_NAME in existing:
    print('Reusing endpoint', VS_ENDPOINT_NAME)
else:
    print('Creating endpoint', VS_ENDPOINT_NAME, '(may take a few minutes)...')
    w.vector_search_endpoints.create_endpoint_and_wait(name=VS_ENDPOINT_NAME, endpoint_type=EndpointType.STANDARD)
    print('Endpoint online.')

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create (or Sync) the Delta Sync Index

# COMMAND ----------

import time

def index_exists(fqn):
    try:
        w.vector_search_indexes.get_index(index_name=fqn); return True
    except Exception:
        return False

if index_exists(INDEX_FQN):
    print('Index exists — triggering sync')
    for attempt in range(30):  # a sync started by an earlier run may still be in progress
        try:
            w.vector_search_indexes.sync_index(index_name=INDEX_FQN); break
        except Exception as e:
            if 'not ready to sync' not in str(e): raise
            print('Previous sync still running; retrying in 30s'); time.sleep(30)
else:
    w.vector_search_indexes.create_index(
        name=INDEX_FQN, endpoint_name=VS_ENDPOINT_NAME, primary_key='id',
        index_type=VectorIndexType.DELTA_SYNC,
        delta_sync_index_spec=DeltaSyncVectorIndexSpecRequest(
            source_table=SOURCE_TABLE_FQN, pipeline_type=PipelineType.TRIGGERED,
            embedding_source_columns=[EmbeddingSourceColumn(name='chunk_to_embed', embedding_model_endpoint_name=EMBEDDING_MODEL)],
        ),
    )
    print('Created index', INDEX_FQN)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Wait for the Index to Finish its Sync

# COMMAND ----------

# `ready` turns true as soon as the index is queryable, so also wait until every chunk is indexed.
expected_rows = spark.table(SOURCE_TABLE_FQN).count()
deadline = time.time() + 60 * 25
while True:
    idx = w.vector_search_indexes.get_index(index_name=INDEX_FQN)
    ready = getattr(idx.status, 'ready', None)
    rows_indexed = getattr(idx.status, 'indexed_row_count', None)
    print(f'ready={ready} indexed_rows={rows_indexed}/{expected_rows}')
    if ready and rows_indexed == expected_rows:
        break
    if time.time() > deadline:
        print('Still syncing; it is safe to continue once ready=True.'); break
    time.sleep(30)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create the UC Function
# MAGIC
# MAGIC The function comment and parameter comment are what the model sees as the tool
# MAGIC description, so they explain when to call it.

# COMMAND ----------

# CREATE OR REPLACE drops the function's own grants (for example the agent's EXECUTE from
# 4_GrantAgentAccess), so keep them and re-apply them after a rebuild.
try:
    kept_grants = [(r.Principal, r.ActionType) for r in spark.sql(f"SHOW GRANTS ON FUNCTION {FUNCTION_FQN}").collect()
                   if r.ObjectType == "FUNCTION"]
except Exception:  # first run: the function doesn't exist yet
    kept_grants = []

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FUNCTION_FQN}(
  query STRING COMMENT 'Natural-language question or keywords about the contracts, for example: payment terms of the Echo agreement'
)
RETURNS TABLE (source_uri STRING, chunk_to_retrieve STRING, score DOUBLE)
COMMENT 'Searches the marketing services contracts (parties, scope, fees, payment terms, dates, termination, obligations). Returns the most relevant passages with the contract file name in source_uri.'
RETURN
  SELECT source_uri, chunk_to_retrieve, search_score AS score
  FROM vector_search(
    index => '{INDEX_FQN}',
    query_text => query,
    num_results => {NUM_RESULTS}
  )
""")
for principal, privilege in kept_grants:
    spark.sql(f"GRANT {privilege} ON FUNCTION {FUNCTION_FQN} TO `{principal}`")
print("Created", FUNCTION_FQN, f"(re-applied {len(kept_grants)} grant(s))")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Test the Function

# COMMAND ----------

display(spark.sql(f"SELECT * FROM {FUNCTION_FQN}('What are the payment terms in the Echo contract?')"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Next Step: Bind the Tools and Deploy the Agent
# MAGIC
# MAGIC The Agent Bricks CLI runs from a terminal (your laptop, or the **web terminal** of a
# MAGIC Databricks cluster). The next cell resolves the Genie space id and prints the commands with
# MAGIC your values filled in. Both tools use `--auth app`, so they run as the agent's service
# MAGIC principal; notebook `4` grants it access.

# COMMAND ----------

# REST call so this works with any installed databricks-sdk version.
spaces, page_token = [], None
while True:
    query = {"page_size": 100, **({"page_token": page_token} if page_token else {})}
    resp = w.api_client.do("GET", "/api/2.0/genie/spaces", query=query)
    spaces.extend(resp.get("spaces", []))
    page_token = resp.get("next_page_token")
    if not page_token:
        break
match = next((s for s in spaces if s.get("title") == GENIE_SPACE_TITLE), None)
assert match, f"No Genie space titled '{GENIE_SPACE_TITLE}'. Run 2_genie/0_CreateGenieSpace first."
GENIE_SPACE_ID = match["space_id"]

print(f"""Run these from the 3_agent-bricks/agent folder:

  databricks auth login --host {w.config.host} --profile <profile>
  agentbricks login --profile <profile>
  agentbricks tools add genie-agent {GENIE_SPACE_ID} --name sales_analytics --auth app
  agentbricks tools add uc-function {FUNCTION_FQN} --name search_contracts --auth app
  agentbricks deploy

Then run notebook 4_GrantAgentAccess.""")
