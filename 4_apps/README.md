# Apps — Marketing Campaign Insights Chat

Stage 4 of [Marketing Campaign Analytics](../README.md). Deploys a production
**Databricks App** — a Streamlit chat UI — pointed at the **Supervisor Agent**
endpoint from stage 3.

<img src="../docs/figures/marketing_campaign_insights_app.png" alt="Marketing Campaign Insights Assistant — Databricks App" width="85%" />

## Prerequisites

- Stage 3 complete — Supervisor Agent endpoint is live.
- Permission to **deploy Databricks Apps** in the workspace.

## Notebook

### 0_DeployChatApp

Binds the Supervisor endpoint as an app resource (`CAN_QUERY`), **grants the
app's service principal access to every underlying resource**, creates the app,
deploys the sibling [`chat_app/`](chat_app/) folder, and prints the app URL.

The notebook auto-resolves the Supervisor's tools and grants the service
principal: `CAN_QUERY` on the Supervisor/embedding endpoints, `CAN_USE` on the
Vector Search index and retriever function, `CAN_RUN` on Genie spaces, `CAN_USE`
on SQL warehouses, `CAN_READ` on the Sales Dashboard, and UC `SELECT` privileges.

**Parameters:** `APP_NAME`, `SUPERVISOR_NAME`, `SERVING_ENDPOINT_NAME` (blank =
resolve from Supervisor name), `CATALOG_NAME` (default `marketing_campaign_analytics`), `SCHEMA_NAME`,
`APP_SOURCE_PATH` (blank = sibling `chat_app/` folder)

## `chat_app/` — the app source

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit chat UI with sidebar branding |
| `model_serving_utils.py` | Endpoint invocation + multi-agent response parsing |
| `app.yaml` | App config (`SERVING_ENDPOINT` via `valueFrom`) |
| `requirements.txt` | Dependencies |
| `style.css` | Custom styling |
| `figures/brand_logo.png` | Sidebar logo (runtime asset) |

## Directory structure

```
4_apps/
├── 0_DeployChatApp.ipynb
├── chat_app/
└── README.md
```

Documentation screenshots live at [`../docs/figures/`](../docs/figures/).
