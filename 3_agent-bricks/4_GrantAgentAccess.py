# Databricks notebook source
# MAGIC %md
# MAGIC # 4 · Grant the Agent Access to Its Tools
# MAGIC
# MAGIC `agentbricks deploy` runs the agent as a Databricks App named `agent-bricks-<name>` with its
# MAGIC own **service principal**. It grants that principal access to the agent's memory and session
# MAGIC stores, but not to the data behind the tools. Both tools are bound with `--auth app`, so this
# MAGIC notebook grants the principal what they need:
# MAGIC
# MAGIC | Tool | Grants |
# MAGIC | --- | --- |
# MAGIC | Genie agent (`sales_analytics`) | `CAN_RUN` on the Genie space, `CAN_USE` on its SQL warehouse, `SELECT` on the tables and metric view |
# MAGIC | `search_contracts` | `EXECUTE` on the function, `SELECT` on the index, `CAN_USE` on the Vector Search endpoint, `CAN_QUERY` on the embedding endpoint |
# MAGIC
# MAGIC Run it after the first `agentbricks deploy`. Re-running is safe.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Define Parameters
# MAGIC
# MAGIC | Widget | Default | What it controls |
# MAGIC | --- | --- | --- |
# MAGIC | `AGENT_APP_NAME` | `agent-bricks-marketing-agent` | App created by `agentbricks deploy` (`agent-bricks-` + `deployment_name` in `agent/agent.toml`). |
# MAGIC | `CATALOG_NAME` | `workspace` | Unity Catalog for demo objects. |
# MAGIC | `SCHEMA_NAME` | `marketing_campaign` | Schema with the tables, index, and function. |
# MAGIC | `INDEX_NAME` | `contract_chunks_index` | Vector Search index from notebook `1`. |
# MAGIC | `FUNCTION_NAME` | `search_contracts` | UC function from notebook `1`. |
# MAGIC | `EMBEDDING_MODEL` | `databricks-gte-large-en` | Embedding endpoint used by the index. |
# MAGIC | `GENIE_SPACE_TITLE` | `Marketing Campaign Analytics — Genie Space` | Title from `2_genie/0`. |

# COMMAND ----------

dbutils.widgets.text("AGENT_APP_NAME", "agent-bricks-marketing-agent", "AGENT_APP_NAME — app created by agentbricks deploy")
dbutils.widgets.text("CATALOG_NAME", "workspace", "CATALOG_NAME — Unity Catalog catalog for demo objects")
dbutils.widgets.text("SCHEMA_NAME", "marketing_campaign", "SCHEMA_NAME — schema inside the catalog")
dbutils.widgets.text("INDEX_NAME", "contract_chunks_index", "INDEX_NAME — Vector Search index (from notebook 1)")
dbutils.widgets.text("FUNCTION_NAME", "search_contracts", "FUNCTION_NAME — UC function from notebook 1")
dbutils.widgets.text("EMBEDDING_MODEL", "databricks-gte-large-en", "EMBEDDING_MODEL — embedding endpoint used by the index")
dbutils.widgets.text("GENIE_SPACE_TITLE", "Marketing Campaign Analytics — Genie Space", "GENIE_SPACE_TITLE — title used in 2_genie/0")

AGENT_APP_NAME = dbutils.widgets.get("AGENT_APP_NAME")
CATALOG_NAME = dbutils.widgets.get("CATALOG_NAME")
SCHEMA_NAME = dbutils.widgets.get("SCHEMA_NAME")
INDEX_FQN = f"{CATALOG_NAME}.{SCHEMA_NAME}.{dbutils.widgets.get('INDEX_NAME')}"
FUNCTION_FQN = f"{CATALOG_NAME}.{SCHEMA_NAME}.{dbutils.widgets.get('FUNCTION_NAME')}"
EMBEDDING_MODEL = dbutils.widgets.get("EMBEDDING_MODEL")
GENIE_SPACE_TITLE = dbutils.widgets.get("GENIE_SPACE_TITLE").strip()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Resolve the Agent's Service Principal and the Genie Space

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

agent_app = w.apps.get(name=AGENT_APP_NAME)
SP = agent_app.service_principal_client_id
print("Agent app             :", agent_app.name, agent_app.url)
print("Agent service principal:", SP)

# REST call so this works with any installed databricks-sdk version.
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
GENIE_SPACE_ID = space["space_id"]
WAREHOUSE_ID = w.api_client.do("GET", f"/api/2.0/genie/spaces/{GENIE_SPACE_ID}").get("warehouse_id")
print("Genie space           :", GENIE_SPACE_ID, "| warehouse:", WAREHOUSE_ID)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Apply the Grants

# COMMAND ----------

from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel
from databricks.sdk.service.serving import ServingEndpointAccessControlRequest, ServingEndpointPermissionLevel
from databricks.sdk.service.sql import WarehouseAccessControlRequest, WarehousePermissionLevel

# Genie agent tool
w.permissions.update(request_object_type="genie", request_object_id=GENIE_SPACE_ID,
                     access_control_list=[AccessControlRequest(service_principal_name=SP,
                                                               permission_level=PermissionLevel.CAN_RUN)])
print("  CAN_RUN on Genie space", GENIE_SPACE_ID)
if WAREHOUSE_ID:
    w.warehouses.update_permissions(warehouse_id=WAREHOUSE_ID, access_control_list=[
        WarehouseAccessControlRequest(service_principal_name=SP, permission_level=WarehousePermissionLevel.CAN_USE)])
    print("  CAN_USE on warehouse", WAREHOUSE_ID)

# Unity Catalog: tables, metric view, index (SELECT) and the function (EXECUTE).
# REST call so this works with any installed databricks-sdk version.
def grant(securable_type, full_name, privileges):
    w.api_client.do("PATCH", f"/api/2.1/unity-catalog/permissions/{securable_type}/{full_name}",
                    body={"changes": [{"principal": SP, "add": privileges}]})

grant("catalog", CATALOG_NAME, ["USE_CATALOG"])
grant("schema", f"{CATALOG_NAME}.{SCHEMA_NAME}", ["USE_SCHEMA", "SELECT"])
grant("function", FUNCTION_FQN, ["EXECUTE"])
print(f"  USE CATALOG, USE SCHEMA + SELECT on {CATALOG_NAME}.{SCHEMA_NAME}, EXECUTE on {FUNCTION_FQN}")

# search_contracts: Vector Search endpoint and query-time embeddings
vs_endpoint = w.vector_search_endpoints.get_endpoint(w.vector_search_indexes.get_index(index_name=INDEX_FQN).endpoint_name)
w.api_client.do("PATCH", f"/api/2.0/permissions/vector-search-endpoints/{vs_endpoint.id}",
                body={"access_control_list": [{"service_principal_name": SP, "permission_level": "CAN_USE"}]})
print("  CAN_USE on Vector Search endpoint", vs_endpoint.name)
embedding = w.serving_endpoints.get(EMBEDDING_MODEL)
if embedding.id:
    w.serving_endpoints.update_permissions(
        serving_endpoint_id=embedding.id,
        access_control_list=[ServingEndpointAccessControlRequest(
            service_principal_name=SP, permission_level=ServingEndpointPermissionLevel.CAN_QUERY)])
    print("  CAN_QUERY on", EMBEDDING_MODEL)
else:
    # Databricks-hosted foundation model endpoints have no ACL: every principal can query them.
    print("  No grant needed for", EMBEDDING_MODEL, "(Databricks-hosted foundation model endpoint)")
print("\nDone. Permissions can take about a minute to propagate.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Try the Agent
# MAGIC
# MAGIC Try the agent from the chat app (`4_apps`), or call it from a terminal
# MAGIC in the `agent/` folder:
# MAGIC
# MAGIC ```bash
# MAGIC agentbricks endpoint invoke agent-bricks-marketing-agent --path /api/invocations \
# MAGIC   --json '{"id": "'$(uuidgen)'", "session_id": "'$(uuidgen)'",
# MAGIC            "input": {"messages": [{"role": "user", "content": "What are my top 5 campaigns by total sales?"}]}}'
# MAGIC ```
# MAGIC
# MAGIC Then deploy the Streamlit chat app in `4_apps/`, which calls this agent.
