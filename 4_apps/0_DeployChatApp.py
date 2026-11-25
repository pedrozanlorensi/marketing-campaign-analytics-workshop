# Databricks notebook source
# MAGIC %md
# MAGIC # 0 · Deploy a Custom Chat App for the Agent
# MAGIC
# MAGIC Deploys a **Custom Chat App** on **Databricks Apps**: a production Streamlit interface that
# MAGIC calls the **Agent Bricks agent** deployed in stage 3 (`agentbricks deploy`).
# MAGIC
# MAGIC The app source lives as plain files in the **`chat_app/`** folder next to this notebook
# MAGIC (`app.py`, `agent_client.py`, `app.yaml`, `requirements.txt`). The agent app name is set in
# MAGIC `chat_app/app.yaml` (`AGENT_APP_NAME`).
# MAGIC
# MAGIC **What this notebook does**
# MAGIC 1. Locates the sibling `chat_app/` source folder in the workspace
# MAGIC 2. Creates the App (or reuses it)
# MAGIC 3. Grants the app's service principal `CAN_USE` on the agent app, so it can call
# MAGIC    `<agent-url>/api/invocations`. The agent itself runs its tools with its own service
# MAGIC    principal (granted in `3_agent-bricks/4_GrantAgentAccess`).
# MAGIC 4. Deploys the app and prints its URL

# COMMAND ----------

# MAGIC %md
# MAGIC ### Install Dependencies

# COMMAND ----------

# MAGIC %pip install --upgrade databricks-sdk

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Define Parameters
# MAGIC Review the widgets before running.
# MAGIC | Widget | Default | What it controls |
# MAGIC | --- | --- | --- |
# MAGIC | `APP_NAME` | `marketing-app` | Databricks App name (lowercase, hyphens). |
# MAGIC | `AGENT_APP_NAME` | `agent-bricks-marketing-agent` | Agent app from stage 3. Must match `AGENT_APP_NAME` in `chat_app/app.yaml`. |
# MAGIC | `APP_SOURCE_PATH` | `./chat_app` | Folder with `app.py`, `app.yaml`, and `requirements.txt`. |
# MAGIC | `DASHBOARD_NAME` | `Marketing Campaign Analytics - Sales Dashboard` | Dashboard the sidebar's Insights Portal button opens. |

# COMMAND ----------

dbutils.widgets.text("APP_NAME", "marketing-app", "APP_NAME — Databricks App name (lowercase, hyphens)")
dbutils.widgets.text("AGENT_APP_NAME", "agent-bricks-marketing-agent", "AGENT_APP_NAME — agent app from agentbricks deploy")
dbutils.widgets.text("APP_SOURCE_PATH", "./chat_app", "App source folder (blank = ./chat_app next to this notebook)")
dbutils.widgets.text("DASHBOARD_NAME", "Marketing Campaign Analytics - Sales Dashboard", "DASHBOARD_NAME — dashboard the Insights Portal button opens")

DASHBOARD_NAME = dbutils.widgets.get("DASHBOARD_NAME")
APP_NAME = dbutils.widgets.get("APP_NAME")
AGENT_APP_NAME = dbutils.widgets.get("AGENT_APP_NAME")
APP_SOURCE_PATH = dbutils.widgets.get("APP_SOURCE_PATH")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Initialize Client and Resolve Paths

# COMMAND ----------

import os
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

agent_app = w.apps.get(name=AGENT_APP_NAME)
print("Agent app       :", agent_app.name, agent_app.url)

# Resolve the app source folder to an absolute workspace path.
# The deploy API requires an absolute /Workspace/... path, so a relative value
# like "./chat_app" is resolved against this notebook's directory.
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
nb_dir = os.path.dirname(ctx.notebookPath().get())  # e.g. /Repos/<user>/<repo>/4_apps
if not APP_SOURCE_PATH:
    APP_SOURCE_PATH = f"/Workspace{nb_dir}/chat_app"
elif not APP_SOURCE_PATH.startswith("/"):
    rel = APP_SOURCE_PATH.lstrip("./").strip("/")
    APP_SOURCE_PATH = f"/Workspace{nb_dir}/{rel}"
# else: an absolute /Workspace/... (or /Repos/...) path is used as-is
print("App source path :", APP_SOURCE_PATH)

# Sanity-check the source files are present so the deploy can't silently ship an empty app.
required = ["app.py", "agent_client.py", "app.yaml", "requirements.txt"]
present = os.listdir(APP_SOURCE_PATH)
missing = [f for f in required if f not in present]
assert not missing, f"Missing {missing} in {APP_SOURCE_PATH}. Import the chat_app/ folder into the workspace."
yaml_text = open(os.path.join(APP_SOURCE_PATH, "app.yaml")).read()
assert AGENT_APP_NAME in yaml_text, f"Set AGENT_APP_NAME to {AGENT_APP_NAME} in chat_app/app.yaml."
print("Source files    :", present)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create the App

# COMMAND ----------

from databricks.sdk.service.apps import App

existing = next((a for a in w.apps.list() if a.name == APP_NAME), None)
# Keep resources attached later (for example the Lakebase database from 5_lakebase).
app_spec = App(name=APP_NAME, description=f"Custom chat app for the {AGENT_APP_NAME} agent",
               resources=existing.resources if existing else None)
if existing:
    print(f"App '{APP_NAME}' already exists; updating it.")
    app = w.apps.update(name=APP_NAME, app=app_spec)
else:
    print(f"Creating app '{APP_NAME}' (provisioning compute, ~2-4 min)...")
    app = w.apps.create_and_wait(app=app_spec)
print("App service principal:", app.service_principal_name)
print("App status:", app.app_status.state if app.app_status else None)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Grant the App's Service Principal Access to the Agent
# MAGIC
# MAGIC The chat app only calls the agent, so its service principal needs `CAN_USE` on the agent
# MAGIC app, plus `CAN_READ` on the dashboard its sidebar links to. Everything behind the agent
# MAGIC (Genie, the contract search function, the index) is accessed by the agent's own service
# MAGIC principal.

# COMMAND ----------

from databricks.sdk.service.apps import AppAccessControlRequest, AppPermissionLevel

SP = app.service_principal_client_id
w.apps.update_permissions(
    app_name=AGENT_APP_NAME,
    access_control_list=[AppAccessControlRequest(
        service_principal_name=SP, permission_level=AppPermissionLevel.CAN_USE)],
)
print(f"CAN_USE on {AGENT_APP_NAME} granted to {SP}")

# The sidebar's "Insights Portal" button links to the published dashboard. The app finds it by
# display name with its own service principal, so the principal needs to see the dashboard.
dashboard = next((d for d in w.lakeview.list() if d.display_name == DASHBOARD_NAME), None)
if dashboard:
    w.api_client.do("PATCH", f"/api/2.0/permissions/dashboards/{dashboard.dashboard_id}",
                    body={"access_control_list": [{"service_principal_name": SP,
                                                   "permission_level": "CAN_READ"}]})
    print(f"CAN_READ on dashboard '{DASHBOARD_NAME}' granted to {SP}")
else:
    print(f"No dashboard named '{DASHBOARD_NAME}'; the app will hide the Insights Portal button. "
          "Run 1_metric-views/3_CreateDashboard, then re-run this cell.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Deploy the App

# COMMAND ----------

from databricks.sdk.service.apps import AppDeployment

print("Deploying app source from", APP_SOURCE_PATH, "...")
deployment = w.apps.deploy_and_wait(
    app_name=APP_NAME,
    app_deployment=AppDeployment(source_code_path=APP_SOURCE_PATH),
)
print("Deployment state:", deployment.status.state if deployment.status else None)
if deployment.status and deployment.status.message:
    print("Message:", deployment.status.message)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Result

# COMMAND ----------

app = w.apps.get(name=APP_NAME)
print("App URL   :", app.url)
print("App logs  :", (app.url.rstrip('/') + "/logz") if app.url else None)
print("Agent     :", AGENT_APP_NAME)
print("\nOpen the App URL to chat with the agent.")
