# Databricks notebook source
# MAGIC %md
# MAGIC # 3 · Create the AI/BI Dashboard
# MAGIC
# MAGIC AI/BI Dashboards consume UC Business Semantics **metric views** natively. This
# MAGIC notebook takes the sample serialized dashboard
# MAGIC ([./dashboard/dashboard.lvdash.json](./dashboard/dashboard.lvdash.json)), points it
# MAGIC at your catalog / schema, and **creates + publishes** it in your workspace.
# MAGIC
# MAGIC Re-running is safe: if a dashboard with the same display name already exists it is
# MAGIC updated in place rather than duplicated.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Install Dependencies

# COMMAND ----------

# MAGIC %pip install databricks-sdk -U

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Define Parameters
# MAGIC Review the widgets before running. Defaults match the **Marketing Campaign Analytics** layout.
# MAGIC | Widget | Default | What it controls |
# MAGIC | --- | --- | --- |
# MAGIC | `CATALOG_NAME` | `workspace` | Unity Catalog for demo objects. Default `workspace` is pre-provisioned — no catalog creation needed. |
# MAGIC | `SCHEMA_NAME` | `marketing_campaign` | Schema inside the catalog for sales data and contracts. |
# MAGIC | `WAREHOUSE_ID` | `auto` | SQL warehouse for the dashboard. Use `auto` to pick the first running warehouse in the workspace. |
# MAGIC | `DASHBOARD_NAME` | `Marketing Campaign Analytics - Sales Dashboard` | Display name of the published AI/BI dashboard. |

# COMMAND ----------

dbutils.widgets.text("CATALOG_NAME", "workspace", "CATALOG_NAME — Unity Catalog catalog for demo objects")
dbutils.widgets.text("SCHEMA_NAME", "marketing_campaign", "SCHEMA_NAME — schema inside the catalog")
dbutils.widgets.text("WAREHOUSE_ID", "auto", "WAREHOUSE_ID — SQL warehouse (auto = first running warehouse)")
dbutils.widgets.text("DASHBOARD_NAME", "Marketing Campaign Analytics - Sales Dashboard", "DASHBOARD_NAME — display name of the published dashboard")

CATALOG_NAME = dbutils.widgets.get("CATALOG_NAME")
SCHEMA_NAME = dbutils.widgets.get("SCHEMA_NAME")
WAREHOUSE_ID = dbutils.widgets.get("WAREHOUSE_ID")
DASHBOARD_NAME = dbutils.widgets.get("DASHBOARD_NAME")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Parameterize the Dashboard Definition
# MAGIC
# MAGIC The sample `dashboard.lvdash.json` uses `CATALOG_NAME` / `SCHEMA_NAME` placeholders.
# MAGIC We substitute your parameter values into a copy the API can consume.

# COMMAND ----------

with open('./dashboard/dashboard.lvdash.json', 'r') as f:
    serialized_dashboard = f.read()

serialized_dashboard = (
    serialized_dashboard
    .replace('CATALOG_NAME', CATALOG_NAME)
    .replace('SCHEMA_NAME', SCHEMA_NAME)
)
print('Dashboard definition parameterized for', f'{CATALOG_NAME}.{SCHEMA_NAME}')

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create (or Update) and Publish the Dashboard

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.dashboards import Dashboard

w = WorkspaceClient()

if not WAREHOUSE_ID or WAREHOUSE_ID.strip().lower() == "auto":
    running = [wh for wh in w.warehouses.list() if wh.state and wh.state.value == "RUNNING"]
    WAREHOUSE_ID = (running[0].id if running else next(iter(w.warehouses.list())).id)
    print("Resolved WAREHOUSE_ID:", WAREHOUSE_ID)

# Idempotent: reuse an existing dashboard with the same display name
existing = next((d for d in w.lakeview.list() if d.display_name == DASHBOARD_NAME), None)

spec = Dashboard(
    display_name=DASHBOARD_NAME,
    serialized_dashboard=serialized_dashboard,
    warehouse_id=WAREHOUSE_ID,
)

if existing:
    dash = w.lakeview.update(dashboard_id=existing.dashboard_id, dashboard=spec)
    print('Updated existing dashboard:', dash.dashboard_id)
else:
    dash = w.lakeview.create(dashboard=spec)
    print('Created new dashboard:', dash.dashboard_id)

published = w.lakeview.publish(dash.dashboard_id, warehouse_id=WAREHOUSE_ID)
print('Published dashboard:', dash.dashboard_id)
print(f'{w.config.host}/dashboardsv3/{dash.dashboard_id}/published')

# COMMAND ----------

dbutils.notebook.exit(dash.dashboard_id)
