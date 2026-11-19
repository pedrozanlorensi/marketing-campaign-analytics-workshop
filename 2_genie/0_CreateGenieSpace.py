# Databricks notebook source
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
# MAGIC | `WAREHOUSE_ID` | `auto` | SQL warehouse attached to the Genie space. Use `auto` to pick the first running warehouse. |
# MAGIC | `GENIE_SPACE_TITLE` | `Marketing Campaign Analytics — Genie Space` | Title shown in the Genie UI. |

# COMMAND ----------

dbutils.widgets.text("CATALOG_NAME", "workspace", "CATALOG_NAME — Unity Catalog catalog for demo objects")
dbutils.widgets.text("SCHEMA_NAME", "marketing_campaign", "SCHEMA_NAME — schema inside the catalog")
dbutils.widgets.text("WAREHOUSE_ID", "auto", "WAREHOUSE_ID — SQL warehouse for Genie (auto = first running warehouse)")
dbutils.widgets.text("GENIE_SPACE_TITLE", "Marketing Campaign Analytics — Genie Space", "GENIE_SPACE_TITLE — name shown in the Genie UI")

CATALOG_NAME = dbutils.widgets.get("CATALOG_NAME")
SCHEMA_NAME = dbutils.widgets.get("SCHEMA_NAME")
WAREHOUSE_ID = dbutils.widgets.get("WAREHOUSE_ID")
GENIE_SPACE_TITLE = dbutils.widgets.get("GENIE_SPACE_TITLE")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create Genie Space

# COMMAND ----------

# MAGIC %md
# MAGIC UC Business Semantics metric views are natively integrated with AI/BI Genie, leveraging semantic metadata (instructions, synonyms, formatting) to deliver more accurate answers:

# COMMAND ----------

# MAGIC %md
# MAGIC Check out the sample serialized Genie space [./genie_space/genie_space.json](./genie_space/genie_space.json). 
# MAGIC You can use the code snippet below to automatically create it in your workspace, it uses the [Create Genie Space](https://docs.databricks.com/api/workspace/genie/createspace) API.

# COMMAND ----------

import json
from databricks.sdk import WorkspaceClient

# Load the serialized Genie space from the JSON file
with open('./genie_space/genie_space.json', 'r') as f:
    genie_space_json_str = f.read()

# Replace CATALOG_NAME and SCHEMA_NAME placeholders with parameter values
genie_space_json_str = genie_space_json_str.replace("CATALOG_NAME", CATALOG_NAME).replace("SCHEMA_NAME", SCHEMA_NAME)

w = WorkspaceClient()
if not WAREHOUSE_ID or WAREHOUSE_ID.strip().lower() == "auto":
    running = [wh for wh in w.warehouses.list() if wh.state and wh.state.value == "RUNNING"]
    WAREHOUSE_ID = (running[0].id if running else next(iter(w.warehouses.list())).id)
    print("Resolved WAREHOUSE_ID:", WAREHOUSE_ID)

payload = {
    "serialized_space": genie_space_json_str,
    "warehouse_id": WAREHOUSE_ID,
    "title": GENIE_SPACE_TITLE
}

workspace_url = w.config.host
pat_token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()

import requests

headers = {
    "Authorization": f"Bearer {pat_token}",
    "Content-Type": "application/json"
}

# POST to Genie Create Space API
response = requests.post(
    f"{workspace_url}/api/2.0/genie/spaces",
    headers=headers,
    data=json.dumps(payload)
)

response.raise_for_status()
space_info = response.json()
print(f"Created Genie space with ID *{space_info['space_id']}* and name *{space_info['title']}*")

# COMMAND ----------

dbutils.notebook.exit(json.dumps({"space_id": space_info["space_id"], "title": space_info["title"]}))
