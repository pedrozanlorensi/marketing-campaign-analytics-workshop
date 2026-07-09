# Metric Views — UC Business Semantics

Stage 1 of [Marketing Campaign Analytics](../README.md). Ingests the marketing campaign star
schema, builds a governed **UC Metric View** (`sales_relationships`) with joins,
dimensions, measures, and window measures, and publishes an **AI/BI dashboard**
on top of it.

## What gets created

| Resource | Name | Description |
| --- | --- | --- |
| Catalog / schema | `<CATALOG_NAME>.<SCHEMA_NAME>` | Unity Catalog objects for the demo |
| Volume | `datasets` | Flat folder holding the Kaggle CSV downloads |
| Tables | 7 Delta tables | `fact_sales_normalized` + `dim_*` dimensions |
| Metric view | `sales_relationships` | Governed semantic layer with `MEASURE()` syntax |
| AI/BI dashboard | `Marketing Campaign Analytics - Sales Dashboard` | Dashboard consuming the metric view |

## Notebooks

Run in order:

| # | Notebook | Purpose |
| --- | --- | --- |
| 0 | [`0_IngestData.ipynb`](0_IngestData.ipynb) | Download Kaggle dataset → `datasets` volume → Delta tables |
| 1 | [`1_CreateMetricView.ipynb`](1_CreateMetricView.ipynb) | Create `sales_relationships` metric view |
| 2 | [`2_QueryMetricView.ipynb`](2_QueryMetricView.ipynb) | Query with `MEASURE()` syntax |
| 3 | [`3_CreateDashboard.ipynb`](3_CreateDashboard.ipynb) | Parameterize, create, and publish the AI/BI dashboard |

**Parameters:** `CATALOG_NAME` (default `marketing_campaign_analytics`), `SCHEMA_NAME`, `WAREHOUSE_ID` (notebook `3`; use `auto` to resolve)

## Templates

| File | Purpose |
| --- | --- |
| [`dashboard/dashboard.lvdash.json`](dashboard/dashboard.lvdash.json) | AI/BI dashboard definition consuming the metric view |

## Next step

Once the metric view and dashboard are live, continue to
[`2_genie/`](../2_genie/) to expose the metric view through a Genie space for
natural-language analytics.
