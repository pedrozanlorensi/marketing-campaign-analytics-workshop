# Run log (2026-11-18)

Output of a measurement script run against the live workspace, using the same SQL, Genie, agent and Lakebase calls as the demo (the Lakebase steps import the app's own `lakebase.py`). Masked: hosts, ids, user e-mails, catalog. Sample e-mails at `example.com` are the anonymized data itself.

## 1. Lakeflow Connect: Google Drive → Delta

Pipeline `marketing_campaign_gdrive_ingestion`: state PipelineState.IDLE, latest update UpdateStateInfoState.COMPLETED

| table | rows |
| --- | --- |
| fact_sales_normalized | 1,000,000 |
| dim_campaigns | 50 |
| dim_customers | 100,000 |
| dim_dates | 366 |
| dim_products | 210 |
| dim_salespersons | 2,000 |
| dim_stores | 500 |
| contract_files | 4 |

Anonymized source data (names are generated pseudonyms, e-mails use `example.com`):

| customers | distinct e-mails | e-mails at example.com |
| --- | --- | --- |
| 100000 | 100000 | 100000 |

| customer_id | first_name | last_name | email |
| --- | --- | --- | --- |
| CUST_00001 | Wesley | Simpson | wesley.simpson.000001@example.com |
| CUST_00002 | Ebony | Goodwin | ebony.goodwin.000002@example.com |
| CUST_00003 | Alice | Day | alice.day.000003@example.com |

## 2. Unity Catalog: metric view and grants

Top 5 campaigns from the metric view `sales_relationships` (3.0s):

| campaign | budget | sales | sales per budget $ |
| --- | --- | --- | --- |
| Winter Clearance Carnival | 640535 | 5.566261217E7 | 86.9 |
| New Arrival Showcase | 191922 | 5.545565457E7 | 288.95 |
| Seasonal Surprise Box | 802394 | 5.542127801E7 | 69.07 |
| Shop & Save Spectacular | 287542 | 5.540764948E7 | 192.69 |
| Autumn Deals Drive | 294276 | 5.538394322E7 | 188.2 |

Schema grants held by the two app service principals (least privilege):

| principal | privilege | object type | object |
| --- | --- | --- | --- |
| agent SP | SELECT | SCHEMA | <catalog>.marketing_analytics |
| agent SP | USE SCHEMA | SCHEMA | <catalog>.marketing_analytics |

## 3. GenAI: contract retrieval and the agent

Contract chunks: ['7', '4'] (chunks, files); chunks naming Zanlorensi Athletics: 7

`search_contracts('payment terms of the Echo podcast agreement')` (2.5s):

| source | score | chunk |
| --- | --- | --- |
| fictional_marketing_services_echo.pdf | 0.624 |  Description of a 'figure': A green rounded square icon featuring the white capital letter |
| fictional_marketing_services_echo.pdf | 0.57 |  governmental order.  7. Assignment & Entire Agreement Neither party may assign this Agree |
| fictional_marketing_services_pulse_digital.pdf | 0.542 |  PD  1200 Riverside Way, Suite 400 · Portland, OR 97209  <table><tr><th>REF NO.</th><td>ZA |

Agent answers (`/api/invocations`), with the tools it called:

| question | tools called | seconds | answer (first 220 chars) |
| --- | --- | --- | --- |
| Which 3 campaigns drove the most sales? | sales_analytics_ask | 41.2 | The **top 3 campaigns that drove the most sales** are:  1. **Winter Clearance Carnival** - $55,662,612.17 2. **New Arrival Showcase** - $55,455,654.57 3. **Seasonal Surprise Box** - $55,421,278.01  These three campaigns  |
| What are the payment terms in the Echo podcast contract? | <catalog>__marketing_analytics__search_contracts | 24.2 | Based on the Echo Podcast & Audio Network contract, the **payment terms are: 50% upfront / Net 30**.  This means: - **50% of the fee is due upfront** (before services begin) - **The remaining 50% is due within 30 days**  |
| Which agency handles digital media for us, and how much did our top campaign sell? | sales_analytics_ask, <catalog>__marketing_analytics__search_contracts | 25.4 | Perfect! I have both pieces of information for you:  ## Digital Media Agency **Pulse Digital Media Group** handles your digital media. According to the contract (fictional_marketing_services_pulse_digital.pdf): - They pl |

## 4. Lakebase: synced tables and the app's write path

- synced table `source_data.dim_campaigns`: SyncedTableState.SYNCED_TABLE_ONLINE_NO_PENDING_UPDATE
- synced table `source_data.dim_customers`: SyncedTableState.SYNCED_TABLE_ONLINE_NO_PENDING_UPDATE

Campaigns readable by the app from Lakebase: {'app': 1, 'source': 50} (3.8s)

App service principal on the synced tables (column-level grants hide the connector's Drive metadata):

| synced table | table-wide SELECT | can read _gdrive_metadata |
| --- | --- | --- |
| dim_campaigns | False | False |
| dim_customers | False | False |

Inserted `CAMP_APP_1000004` in 1.3s and `CUST_APP_1000005` in 1.3s through `lakebase.py`.
Listed by the app's `browse()` right after insert: 1 row (1.3s)

Lakehouse Sync: record visible in `dim_campaigns_all` (Unity Catalog) after **19s**

## 5. Genie: benchmark against ground truth

| question | ground truth | result | seconds |
| --- | --- | --- | --- |
| What were our total sales? | 2.75087459476E9 | pass | 14.3 |
| Which campaign drove the most sales? | Winter Clearance Carnival | pass | 19.2 |
| Which customer segment buys the most? | Online Shopper | pass | 20.1 |
| In which city do our highest-spending customers live? | Mesa | fail | 19.5 |
| Which customer city generates the most total sales? | Mesa | pass | 20.7 |
| Which store type sells the most? | Supermarkets  | pass | 20.3 |
| What is our average sale amount? | 2750.87 | pass | 19.9 |
| Which product category has the highest revenue? | Sports & Outdoors | pass | 19.5 |
| Which campaign returns the most sales per budget dollar? | Green Weekend Deals | pass | 20.6 |
| Is there a campaign named 'Trail Run Launch 164704'? What is its budget? | Trail Run Launch 164704 | pass | 15.5 |

**Genie accuracy: 9/10**

## 6. Databricks App

`marketing-app`: app ApplicationState.RUNNING, compute ComputeState.ACTIVE, resources ['lakebase'], active deployment AppDeploymentState.SUCCEEDED

## 7. Cleanup

Deleted the two run records in Lakebase; the delete reached `dim_campaigns_all` after **18s**.

## Notes

- **The one Genie miss is a wording problem.** "Highest-spending customers" can mean the
  individual top spenders or the city with the most total sales. Genie answered the first; the
  ground truth is the second. The unambiguous version ("which customer city generates the most
  total sales") passes. Both are kept so the score isn't tuned.
- **What a re-run surfaced.** Rebuilding `search_contracts` with `CREATE OR REPLACE` dropped the
  agent's `EXECUTE` grant, and the agent lost the contract tool. `3_agent-bricks/1_CreateContractSearch`
  now re-applies the function's grants after a rebuild; this run is after that fix.
