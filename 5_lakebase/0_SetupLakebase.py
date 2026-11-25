# Databricks notebook source
# MAGIC %md
# MAGIC # 0 · Set Up Lakebase for the Chat App
# MAGIC
# MAGIC One notebook for the app's operational layer: creates (or reuses) the Lakebase project, attaches it
# MAGIC to the chat app, creates the app-owned `app_data` tables, copies the source campaigns and customers
# MAGIC in as read-only **synced tables** (`source_data`), and turns on **Lakehouse Sync** so app records
# MAGIC reach Unity Catalog (`dim_*_all` views), the metric view, and Genie. Run after
# MAGIC `4_apps/0_DeployChatApp`; re-running is safe.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Install Dependencies

# COMMAND ----------

# MAGIC %pip install --upgrade "databricks-sdk>=0.135.0" "psycopg[binary]>=3.2"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Parameters
# MAGIC
# MAGIC `PROJECT_ID` (`marketing-campaign-app`), `APP_NAME` (`marketing-app`), `PG_SCHEMA` (`app_data`),
# MAGIC `CATALOG_NAME` / `SCHEMA_NAME` (where the `dim_*` tables live and Lakehouse Sync writes),
# MAGIC `LAKEBASE_CATALOG` (`marketing_campaign_app`, the UC name for the database), `SOURCE_PG_SCHEMA`
# MAGIC (`source_data`), `GENIE_SPACE_TITLE` (the space that gets the `dim_*_all` views).

# COMMAND ----------

WIDGETS = {"PROJECT_ID": "marketing-campaign-app", "APP_NAME": "marketing-app", "PG_SCHEMA": "app_data",
           "CATALOG_NAME": "workspace", "SCHEMA_NAME": "marketing_campaign",
           "LAKEBASE_CATALOG": "marketing_campaign_app", "SOURCE_PG_SCHEMA": "source_data",
           "GENIE_SPACE_TITLE": "Marketing Campaign Analytics — Genie Space"}
for name, default in WIDGETS.items():
    dbutils.widgets.text(name, default, name)
PROJECT_ID, APP_NAME, PG_SCHEMA, CATALOG_NAME, SCHEMA_NAME, LAKEBASE_CATALOG, SOURCE_PG_SCHEMA, GENIE_SPACE_TITLE = (
    dbutils.widgets.get(name) for name in WIDGETS)
UC = f"{CATALOG_NAME}.{SCHEMA_NAME}"

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create (or Reuse) the Project
# MAGIC
# MAGIC Comes with a `production` branch and a scale-to-zero compute.

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.postgres import Project, ProjectSpec

w = WorkspaceClient()
project_name = f"projects/{PROJECT_ID}"
try:
    w.postgres.get_project(name=project_name)
    print("Reusing project", project_name)
except NotFound:
    print("Creating project", project_name, "(about a minute)...")
    w.postgres.create_project(project=Project(spec=ProjectSpec(display_name=PROJECT_ID)),
                              project_id=PROJECT_ID).wait()

BRANCH = f"{project_name}/branches/production"
DATABASE = next(d.name for d in w.postgres.list_databases(parent=BRANCH)
                if d.status and d.status.postgres_database == "databricks_postgres")
ENDPOINT = next(e.name for e in w.postgres.list_endpoints(parent=BRANCH)
                if "READ_WRITE" in str(e.status.endpoint_type if e.status else ""))
HOST = w.postgres.get_endpoint(name=ENDPOINT).status.hosts.host
print("Branch   :", BRANCH)
print("Database :", DATABASE)
print("Endpoint :", ENDPOINT, "|", HOST)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Attach the Database to the App and Redeploy
# MAGIC
# MAGIC The `postgres` resource gives the app's service principal `CAN_CONNECT_AND_CREATE` and injects
# MAGIC `PGHOST`, `PGUSER`, `LAKEBASE_ENDPOINT`. Existing resources are kept.

# COMMAND ----------

from databricks.sdk.service.apps import (
    App, AppDeployment, AppResource, AppResourcePostgres, AppResourcePostgresPostgresPermission,
)

app = w.apps.get(name=APP_NAME)
resources = [r for r in (app.resources or []) if r.name != "lakebase"]
resources.append(AppResource(name="lakebase", postgres=AppResourcePostgres(
    branch=BRANCH, database=DATABASE,
    permission=AppResourcePostgresPostgresPermission.CAN_CONNECT_AND_CREATE)))
w.apps.create_update_and_wait(app_name=APP_NAME, update_mask="resources",
                              app=App(name=APP_NAME, resources=resources))
print("Attached", DATABASE, "to", APP_NAME)

source = app.active_deployment.source_code_path if app.active_deployment else None
assert source, f"{APP_NAME} has no active deployment. Run 4_apps/0_DeployChatApp first."
print("Redeploying from", source, "...")
deployment = w.apps.deploy_and_wait(app_name=APP_NAME, app_deployment=AppDeployment(source_code_path=source))
print("Deployment:", deployment.status.state if deployment.status else None)
APP_SP = w.apps.get(name=APP_NAME).service_principal_client_id
print("App service principal:", APP_SP)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create the Tables and Grant the App
# MAGIC
# MAGIC Keys start at 1,000,001 so they never collide with source data; `REPLICA IDENTITY FULL` is
# MAGIC required by Lakehouse Sync.

# COMMAND ----------

import time
import psycopg

def connect():
    token = w.postgres.generate_database_credential(endpoint=ENDPOINT).token
    return psycopg.connect(host=HOST, dbname="databricks_postgres", user=w.current_user.me().user_name,
                           password=token, sslmode="require", connect_timeout=30, autocommit=True)

DDL = f"""
CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA};

CREATE SEQUENCE IF NOT EXISTS {PG_SCHEMA}.campaign_sk_seq START WITH 1000001;
CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.campaigns (
  campaign_sk     integer PRIMARY KEY,
  campaign_id     text    NOT NULL UNIQUE,
  campaign_name   text    NOT NULL,
  start_date_sk   integer NOT NULL CHECK (start_date_sk BETWEEN 1 AND 366),
  end_date_sk     integer NOT NULL CHECK (end_date_sk BETWEEN start_date_sk AND 366),
  campaign_budget integer NOT NULL CHECK (campaign_budget > 0),
  created_by      text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE {PG_SCHEMA}.campaigns REPLICA IDENTITY FULL;

CREATE SEQUENCE IF NOT EXISTS {PG_SCHEMA}.customer_sk_seq START WITH 1000001;
CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.customers (
  customer_sk          integer PRIMARY KEY,
  customer_id          text NOT NULL UNIQUE,
  first_name           text NOT NULL,
  last_name            text NOT NULL,
  email                text NOT NULL UNIQUE,
  residential_location text,
  customer_segment     text,
  created_by           text,
  created_at           timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE {PG_SCHEMA}.customers REPLICA IDENTITY FULL;
"""

GRANTS = f"""
GRANT USAGE ON SCHEMA {PG_SCHEMA} TO "{APP_SP}";
GRANT SELECT, INSERT ON {PG_SCHEMA}.campaigns, {PG_SCHEMA}.customers TO "{APP_SP}";
GRANT USAGE ON SEQUENCE {PG_SCHEMA}.campaign_sk_seq, {PG_SCHEMA}.customer_sk_seq TO "{APP_SP}";
"""

with connect() as conn:
    conn.execute(DDL)
    print("Tables ready in schema", PG_SCHEMA)
    # The app's Postgres role is created when the resource is attached; wait for it if needed.
    for _ in range(30):
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_SP,)).fetchone():
            break
        time.sleep(10)
    else:
        raise RuntimeError(f"Postgres role {APP_SP} not found. Check the app's lakebase resource.")
    conn.execute(GRANTS)
    print("Granted SELECT, INSERT and sequence USAGE to", APP_SP)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Sync the Source Data into Lakebase
# MAGIC
# MAGIC Synced tables copy `dim_campaigns` / `dim_customers` into read-only `source_data` (the database is
# MAGIC registered as a UC catalog first). **SNAPSHOT** needs no change data feed, so it works with the
# MAGIC Lakeflow Connect streaming tables; re-run this cell when the source changes. The app gets `SELECT`
# MAGIC on the business columns of `source_data` only, not on the connector's Drive metadata columns.

# COMMAND ----------

from databricks.sdk.service.postgres import (
    Catalog, CatalogCatalogSpec, NewPipelineSpec, SyncedTable, SyncedTableSyncedTableSpec,
    SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy as Policy,
)

try:
    w.postgres.get_catalog(name=f"catalogs/{LAKEBASE_CATALOG}")
except NotFound:
    w.postgres.create_catalog(catalog_id=LAKEBASE_CATALOG, catalog=Catalog(spec=CatalogCatalogSpec(
        postgres_database="databricks_postgres", branch=BRANCH))).wait()

SOURCES = {"dim_campaigns": "campaign_sk", "dim_customers": "customer_sk"}
for table, key in SOURCES.items():
    synced = f"{LAKEBASE_CATALOG}.{SOURCE_PG_SCHEMA}.{table}"
    try:
        w.postgres.get_synced_table(name=f"synced_tables/{synced}")
    except NotFound:
        w.postgres.create_synced_table(synced_table_id=synced, synced_table=SyncedTable(
            spec=SyncedTableSyncedTableSpec(
                source_table_full_name=f"{CATALOG_NAME}.{SCHEMA_NAME}.{table}",
                primary_key_columns=[key],
                scheduling_policy=Policy.SNAPSHOT,
                branch=BRANCH,
                postgres_database="databricks_postgres",
                create_database_objects_if_missing=True,
                new_pipeline_spec=NewPipelineSpec(storage_catalog=CATALOG_NAME, storage_schema=SCHEMA_NAME),
            )))

# Wait for the first snapshot (100,000 customers take a few minutes).
for table in SOURCES:
    name = f"synced_tables/{LAKEBASE_CATALOG}.{SOURCE_PG_SCHEMA}.{table}"
    for _ in range(90):
        state = str(w.postgres.get_synced_table(name=name).status.detailed_state)
        assert "FAILED" not in state, f"{table}: {state}. Check the sync pipeline in Catalog Explorer."
        if state.endswith(("ONLINE", "ONLINE_NO_PENDING_UPDATE")):
            break
        time.sleep(20)
    print(f"  {table}: {state}")

# Column-level grants: synced tables also carry the connector's _gdrive_metadata / _file_metadata
# columns (uploader name, e-mail, Drive links). The app may read the business columns only.
# Re-run this cell after every snapshot refresh.
APP_COLUMNS = {
    "dim_campaigns": ["campaign_sk", "campaign_id", "campaign_name", "start_date_sk", "end_date_sk",
                      "campaign_budget"],
    "dim_customers": ["customer_sk", "customer_id", "first_name", "last_name", "email",
                      "residential_location", "customer_segment"],
}
with connect() as conn:
    conn.execute(f'GRANT USAGE ON SCHEMA {SOURCE_PG_SCHEMA} TO "{APP_SP}"')
    conn.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA {SOURCE_PG_SCHEMA} REVOKE SELECT ON TABLES FROM "{APP_SP}"')
    for table, cols in APP_COLUMNS.items():
        # REVOKE SELECT, not REVOKE ALL: the synced table is owned by a system role, and REVOKE ALL
        # from a non-owner silently leaves SELECT in place.
        conn.execute(f'REVOKE SELECT ON {SOURCE_PG_SCHEMA}.{table} FROM "{APP_SP}"')
        conn.execute(f'GRANT SELECT ({", ".join(cols)}) ON {SOURCE_PG_SCHEMA}.{table} TO "{APP_SP}"')
print("Granted column-level SELECT on", SOURCE_PG_SCHEMA, "to", APP_SP)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Turn On Lakehouse Sync
# MAGIC
# MAGIC One CDF config covers every current and future table in the Postgres schema. The first sync
# MAGIC snapshots the existing rows, then streams changes.

# COMMAND ----------

from databricks.sdk.service.postgres import CdfConfig


def list_or_empty(fn):
    try:
        return list(fn(parent=DATABASE))
    except NotFound:  # returned when none exist yet
        return []

existing = [c for c in list_or_empty(w.postgres.list_cdf_configs)
            if c.postgres_schema == PG_SCHEMA and c.catalog == CATALOG_NAME and c.schema == SCHEMA_NAME]
if existing:
    print("Lakehouse Sync already on:", existing[0].name)
else:
    print(f"Starting Lakehouse Sync: {PG_SCHEMA} -> {UC} ...")
    w.postgres.create_cdf_config(parent=DATABASE, cdf_config_id=PG_SCHEMA,  # must match [a-z][a-z0-9_]*
                                 cdf_config=CdfConfig(catalog=CATALOG_NAME, schema=SCHEMA_NAME,
                                                      postgres_schema=PG_SCHEMA)).wait()

# Wait for the history tables to appear in Unity Catalog (lb_<table>_history). Checking the
# tables directly works in every workspace, even where the per-table status API is not exposed.
HISTORY = {t: f"{UC}.lb_{t}_history" for t in ("campaigns", "customers")}
deadline = time.time() + 20 * 60
while not all(spark.catalog.tableExists(fqn) for fqn in HISTORY.values()):
    assert time.time() < deadline, "History tables did not appear in 20 minutes; check the sync in the Lakebase UI."
    print("  waiting for", [fqn for fqn in HISTORY.values() if not spark.catalog.tableExists(fqn)])
    time.sleep(30)
print("History tables:", HISTORY)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create the Unified Views
# MAGIC
# MAGIC Each history table has one row per change. The views keep the latest version of each app
# MAGIC record, drop deleted ones, and union them with the source data (same columns and types).

# COMMAND ----------

def current(history_table, key):
    return f"""
    SELECT * FROM (
      SELECT *, row_number() OVER (PARTITION BY {key} ORDER BY _sort_by DESC) AS _rn
      FROM {history_table}
      WHERE _pg_change_type IN ('insert', 'update_postimage', 'delete')
    ) WHERE _rn = 1 AND _pg_change_type <> 'delete'"""

CAMPAIGN_COLS = "campaign_sk, campaign_id, campaign_name, start_date_sk, end_date_sk, campaign_budget"
CUSTOMER_COLS = "customer_sk, customer_id, first_name, last_name, email, residential_location, customer_segment"

spark.sql(f"""
CREATE OR REPLACE VIEW {UC}.dim_campaigns_all
COMMENT 'Campaigns from the source data plus campaigns added in the chat app (Lakebase).'
AS SELECT {CAMPAIGN_COLS}, 'source' AS record_source FROM {UC}.dim_campaigns
UNION ALL
SELECT {CAMPAIGN_COLS}, 'app' AS record_source FROM ({current(HISTORY['campaigns'], 'campaign_sk')})
""")
spark.sql(f"""
CREATE OR REPLACE VIEW {UC}.dim_customers_all
COMMENT 'Customers from the source data plus customers added in the chat app (Lakebase).'
AS SELECT {CUSTOMER_COLS}, 'source' AS record_source FROM {UC}.dim_customers
UNION ALL
SELECT {CUSTOMER_COLS}, 'app' AS record_source FROM ({current(HISTORY['customers'], 'customer_sk')})
""")
display(spark.sql(f"""
  SELECT 'campaigns' AS dim, record_source, count(*) AS n FROM {UC}.dim_campaigns_all GROUP BY ALL
  UNION ALL
  SELECT 'customers', record_source, count(*) FROM {UC}.dim_customers_all GROUP BY ALL
  ORDER BY 1, 2"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Rebuild the Metric View on the Unified Views

# COMMAND ----------

result = dbutils.notebook.run("../1_metric-views/1_CreateMetricView", 600, {
    "CATALOG_NAME": CATALOG_NAME, "SCHEMA_NAME": SCHEMA_NAME,
    "CAMPAIGNS_TABLE": "dim_campaigns_all", "CUSTOMERS_TABLE": "dim_customers_all",
})
print("Metric view rebuilt on dim_campaigns_all and dim_customers_all", result or "")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Add the Views to the Genie Space
# MAGIC
# MAGIC The metric view starts from the sales fact table, so a new campaign or customer only appears
# MAGIC there once it has sales. Adding the views as Genie tables lets Genie list and count every
# MAGIC campaign and customer, including the ones added in the app.

# COMMAND ----------

import json, uuid

spaces, page_token = [], None
while True:
    query = {"page_size": 100, **({"page_token": page_token} if page_token else {})}
    resp = w.api_client.do("GET", "/api/2.0/genie/spaces", query=query)
    spaces.extend(resp.get("spaces", []))
    page_token = resp.get("next_page_token")
    if not page_token:
        break
space = next((s for s in spaces if s.get("title") == GENIE_SPACE_TITLE), None)
assert space, f"No Genie space titled '{GENIE_SPACE_TITLE}'. Run 2_genie/0_CreateGenieSpace first."
SPACE_ID = space["space_id"]

full = w.api_client.do("GET", f"/api/2.0/genie/spaces/{SPACE_ID}", query={"include_serialized_space": "true"})
serialized = json.loads(full["serialized_space"])

tables = serialized.setdefault("data_sources", {}).setdefault("tables", [])
for view in (f"{UC}.dim_campaigns_all", f"{UC}.dim_customers_all"):
    if not any(t.get("identifier") == view for t in tables):
        tables.append({"identifier": view})
tables.sort(key=lambda t: t["identifier"])

NOTE = ("* To list, count, or look up campaigns or customers (including ones with no sales yet, such as "
        "records added in the app), query dim_campaigns_all and dim_customers_all. Use the "
        "sales_relationships metric view for anything involving sales.")
texts = serialized.setdefault("instructions", {}).setdefault("text_instructions", [])
if not any(NOTE in "".join(t.get("content", [])) for t in texts):
    if texts:
        texts[0]["content"] = list(texts[0].get("content", [])) + ["\n" + NOTE]
    else:
        texts.append({"id": uuid.uuid4().hex, "content": [NOTE]})

w.api_client.do("PATCH", f"/api/2.0/genie/spaces/{SPACE_ID}", body={"serialized_space": json.dumps(serialized)})
print("Genie space", SPACE_ID, "now includes:", [t["identifier"] for t in tables])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Verify

# COMMAND ----------

with connect() as conn:
    for schema, table in [(SOURCE_PG_SCHEMA, "dim_campaigns"), (SOURCE_PG_SCHEMA, "dim_customers"),
                          (PG_SCHEMA, "campaigns"), (PG_SCHEMA, "customers")]:
        n = conn.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0]
        print(f"  {schema}.{table}: {n:,} rows")
print(f"\nOpen the app, go to 'Add data', and add a record: {w.apps.get(name=APP_NAME).url}")
