# Databricks notebook source
# MAGIC %md
# MAGIC The metric view below condenses the joins depicted in this ERD, and adds calculated measures and columns on top of it:  
# MAGIC
# MAGIC <img src="./figures/dimensional_model.png" width="75%" />
# MAGIC
# MAGIC This notebook creates a metric view as part of [UC Business Semantics](https://docs.databricks.com/aws/en/metric-views/). Many advanced settings are explored, such as:
# MAGIC - Using joins (nested and un-nested): https://docs.databricks.com/aws/en/metric-views/data-modeling/joins
# MAGIC - Adding semantic metadata (display names, synonyms, formatting): https://docs.databricks.com/aws/en/metric-views/data-modeling/semantic-metadata
# MAGIC - Using window measures: https://docs.databricks.com/aws/en/metric-views/data-modeling/window-measures
# MAGIC
# MAGIC Defining your semantic models directly in Databricks via UC Business Semantics lets you benefit from Databricks compute for querying your data, while being fully integrated with Unity Catalog for unified governance and optimal performance. These metric views are reusable across BI tools, SQL clients, and AI agents like Genie.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Define Parameters
# MAGIC
# MAGIC Review the widgets before running. Defaults match the **Marketing Campaign Analytics** layout.
# MAGIC
# MAGIC | Widget | Default | What it controls |
# MAGIC | --- | --- | --- |
# MAGIC | `CATALOG_NAME` | `workspace` | Unity Catalog for demo objects. Default `workspace` is pre-provisioned — no catalog creation needed. |
# MAGIC | `SCHEMA_NAME` | `marketing_campaign` | Schema with `fact_sales_normalized`, dimensions, and `sales_relationships`. |
# MAGIC | `CAMPAIGNS_TABLE` | `dim_campaigns` | Campaigns dimension. `5_lakebase/0_SetupLakebase` switches it to `dim_campaigns_all` (source data plus records added in the app). |
# MAGIC | `CUSTOMERS_TABLE` | `dim_customers` | Customers dimension. `5_lakebase/0_SetupLakebase` switches it to `dim_customers_all`. |

# COMMAND ----------

dbutils.widgets.text("CATALOG_NAME", "workspace", "CATALOG_NAME — Unity Catalog catalog for demo objects")
dbutils.widgets.text("SCHEMA_NAME", "marketing_campaign", "SCHEMA_NAME — schema inside the catalog")
CATALOG_NAME = dbutils.widgets.get("CATALOG_NAME")
SCHEMA_NAME = dbutils.widgets.get("SCHEMA_NAME")
dbutils.widgets.text("CAMPAIGNS_TABLE", "dim_campaigns", "CAMPAIGNS_TABLE — campaigns dimension table or view")
dbutils.widgets.text("CUSTOMERS_TABLE", "dim_customers", "CUSTOMERS_TABLE — customers dimension table or view")
CAMPAIGNS_TABLE = dbutils.widgets.get("CAMPAIGNS_TABLE")
CUSTOMERS_TABLE = dbutils.widgets.get("CUSTOMERS_TABLE")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create Metric View (UC Business Semantics)

# COMMAND ----------

sql_statement = f"""
CREATE OR REPLACE VIEW {CATALOG_NAME}.{SCHEMA_NAME}.sales_relationships WITH METRICS LANGUAGE YAML AS 
$$
version: 1.1

source: {CATALOG_NAME}.{SCHEMA_NAME}.fact_sales_normalized

joins:
  # Star join between fact table and dim_campaigns
  - name: dim_campaigns
    source: {CATALOG_NAME}.{SCHEMA_NAME}.{CAMPAIGNS_TABLE}
    "on": source.campaign_sk = dim_campaigns.campaign_sk
    # Snowflake joins from dim_campaigns to campaign start/end dates
    joins:
      - name: campaign_start_date
        source: {CATALOG_NAME}.{SCHEMA_NAME}.dim_dates
        "on": dim_campaigns.start_date_sk = campaign_start_date.date_sk
      - name: campaign_end_date
        source: {CATALOG_NAME}.{SCHEMA_NAME}.dim_dates
        "on": dim_campaigns.end_date_sk = campaign_end_date.date_sk
  
  # Star join between fact table and dim_customers
  - name: dim_customers
    source: {CATALOG_NAME}.{SCHEMA_NAME}.{CUSTOMERS_TABLE}
    "on": source.customer_sk = dim_customers.customer_sk
  
  # Star join between fact table and dim_dates
  - name: dim_dates
    source: {CATALOG_NAME}.{SCHEMA_NAME}.dim_dates
    "on": date(source.sales_date) = dim_dates.full_date
  
  # Star join between fact table and dim_products
  - name: dim_products
    source: {CATALOG_NAME}.{SCHEMA_NAME}.dim_products
    "on": source.product_sk = dim_products.product_sk
  
  # Star join between fact table and dim_salespersons
  - name: dim_salespersons
    source: {CATALOG_NAME}.{SCHEMA_NAME}.dim_salespersons
    "on": source.salesperson_sk = dim_salespersons.salesperson_sk

  # Star join between fact table and dim_stores
  - name: dim_stores
    source: {CATALOG_NAME}.{SCHEMA_NAME}.dim_stores
    "on": source.store_sk = dim_stores.store_sk
    # Snowflake join from dim_stores to store_manager_salesperson
    joins:
      - name: store_manager_salesperson
        source: {CATALOG_NAME}.{SCHEMA_NAME}.dim_salespersons
        "on": dim_stores.store_manager_sk = store_manager_salesperson.salesperson_sk

comment: "Metric view for analyzing sales relationships across campaigns, customers, dates, products, salespersons, and stores. Includes time-based dimensions and aggregated sales dimensions. Also includes all columns from dimension tables for richer analysis."

dimensions:

  # Columns from fact table
  - name: sales_date
    expr: date(sales_date)
    comment: Sales Date
    display_name: Sales Date
    synonyms: ['date of sale']
  - name: total_amount
    expr: total_amount
    comment: Sales amount
    display_name: Sales amount
    synonyms: ['total amount', 'sale amount']

  # Dimension columns from dim_customers
  - name: first_name
    expr: dim_customers.first_name
    comment: Customer first name
    display_name: First Name
    synonyms: ['customer first', 'given name']
  - name: last_name
    expr: dim_customers.last_name
    comment: Customer last name
    display_name: Last Name
    synonyms: ['customer last', 'surname']
  - name: customer_segment
    expr: dim_customers.customer_segment
    comment: Customer segment
    display_name: Customer Segment
    synonyms: ['segment', 'customer type']
  - name: customer_email
    expr: dim_customers.email
    comment: Customer email
    display_name: Customer Email
    synonyms: ['email', 'contact email']
  - name: customer_residential_location
    expr: dim_customers.residential_location
    comment: Customer residential location
    display_name: Customer Residential Location
    synonyms: ['residence', 'home location']
  # Calculated customer columns
  - name: customer_name
    expr: dim_customers.first_name || ' ' || dim_customers.last_name
    comment: Customer name
    display_name: Customer Name
    synonyms: ['name', 'full name']

  # Dimension columns from dim_stores
  - name: store_name
    expr: dim_stores.store_name
    comment: Store name
    display_name: Store Name
    synonyms: ['location name', 'retail name']
  - name: store_type
    expr: dim_stores.store_type
    comment: Store type
    display_name: Store Type
    synonyms: ['type', 'retail type']
  - name: store_location
    expr: dim_stores.store_location
    comment: Store location
    display_name: Store Location
    synonyms: ['location', 'address']

  # Dimension columns from dim_products
  - name: product_name
    expr: dim_products.product_name
    comment: Product name
    display_name: Product Name
    synonyms: ['item name', 'sku name']
  - name: product_category
    expr: dim_products.category
    comment: Product category
    display_name: Product Category
    synonyms: ['category', 'product type']
  - name: product_brand
    expr: dim_products.brand
    comment: Product brand
    display_name: Brand
    synonyms: ['brand', 'manufacturer']
  - name: product_origin_location
    expr: dim_products.origin_location
    comment: Product origin location
    display_name: Origin Location
    synonyms: ['origin', 'source location']

  # Dimension columns from dim_campaigns
  - name: campaign_name
    expr: dim_campaigns.campaign_name
    comment: Campaign name
    display_name: Campaign Name
    synonyms: ['promotion name', 'marketing name']
  - name: campaign_budget
    expr: dim_campaigns.campaign_budget
    comment: Campaign budget
    display_name: Campaign Budget
    synonyms: ['budget', 'promotion budget']

  # Dimension columns from dim_dates
  - name: full_date
    expr: dim_dates.full_date
    comment: Full date
    display_name: Full Date
    synonyms: ['date', 'transaction date']
  - name: year
    expr: dim_dates.year
    comment: Year
    display_name: Year
    synonyms: ['calendar year', 'fiscal year']
  - name: month
    expr: dim_dates.month
    comment: Month
    display_name: Month
    synonyms: ['calendar month', 'fiscal month']
  - name: day
    expr: dim_dates.day
    comment: Day
    display_name: Day
    synonyms: ['calendar day', 'date day']
  - name: weekday
    expr: dim_dates.weekday
    comment: Weekday
    display_name: Weekday
    synonyms: ['day of week', 'weekday name']
  - name: quarter
    expr: dim_dates.quarter
    comment: Quarter
    display_name: Quarter
    synonyms: ['fiscal quarter', 'calendar quarter']
  # Calculated datetime columns
  - name: week
    expr: "date_trunc('week', sales_date)"
    comment: Week of the sale
    display_name: Week
    format:
      type: date
      date_format: year_week
      leading_zeros: false
    synonyms: ['sales week', 'transaction week']
  - name: dayOfWeek
    expr: dayofweek(sales_date)
    comment: "Day of the week for the sale (1=Sunday, 7=Saturday)"
    display_name: Day of Week
    format:
      type: number
    synonyms: ['weekday number', 'day index']
  - name: YearMonth
    expr: "date_trunc('month', sales_date)"
    comment: Year and month of the sale
    display_name: Year Month
    format:
      type: date
      date_format: locale_number_month
      leading_zeros: false
    synonyms: ['month', 'year and month']

  # Dimension columns from dim_salespersons
  - name: salesperson_name
    expr: dim_salespersons.salesperson_name
    comment: Salesperson name
    display_name: Salesperson Name
    synonyms: ['rep name', 'employee name']
  - name: salesperson_role
    expr: dim_salespersons.salesperson_role
    comment: Salesperson role
    display_name: Salesperson Role
    synonyms: ['role', 'job title']

measures:
  # Calculated measures
  - name: sales_sum
    expr: SUM(source.total_amount)
    comment: Total sales amount
    display_name: Total Sales
    synonyms: ['revenue', 'total sales']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
  - name: sales_avg
    expr: AVG(source.total_amount)
    comment: Average sales amount
    display_name: Average Sales
    synonyms: ['average revenue', 'mean sales']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
  - name: sales_stddev
    expr: STDDEV(source.total_amount)
    comment: Standard deviation of sales amount
    display_name: Sales Standard Deviation
    synonyms: ['sales variability', 'sales stddev']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
  - name: sales_median
    expr: percentile(source.total_amount, 0.5)
    comment: Median sales amount
    display_name: Sales Median
    synonyms: ['median revenue', 'median sales']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
  - name: sales_quartile1
    expr: percentile(source.total_amount, 0.25)
    comment: First quartile (Q1) of sales amount
    display_name: Sales Quartile 1
    synonyms: ['Q1 sales', 'first quartile']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
  - name: sales_quartile2
    expr: percentile(source.total_amount, 0.5)
    comment: Second quartile (Q2/Median) of sales amount
    display_name: Sales Quartile 2 (Median)
    synonyms: ['Q2 sales', 'median']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
  - name: sales_quartile3
    expr: percentile(source.total_amount, 0.75)
    comment: Third quartile (Q3) of sales amount
    display_name: Sales Quartile 3
    synonyms: ['Q3 sales', 'third quartile']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
  - name: sales_quartile4
    expr: percentile(source.total_amount, 1.0)
    comment: Fourth quartile (Q4/Max) of sales amount
    display_name: Sales Quartile 4 (Max)
    synonyms: ['Q4 sales', 'max sales']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
  - name: sales_largest
    expr: MAX(source.total_amount)
    comment: Largest Sale
    display_name: Largest Sale
    synonyms: ['max sale', 'highest sale']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
  - name: sales_smallest
    expr: MIN(source.total_amount)
    comment: Smallest Sale
    display_name: Smallest Sale
    synonyms: ['min sale', 'lowest sale']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact
  - name: sales_mode
    expr: mode(source.total_amount)
    comment: Mode of sales amount
    display_name: Sales Mode
    synonyms: ['most common sale', 'mode']
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
      abbreviation: compact

  # Window measures
  - name: previous_day_sales
    expr: SUM(total_amount)
    comment: Previous Day Sales
    display_name: Previous Day Sales
    synonyms: ['last day sales', 'yesterday sales']
    window:
      - order: sales_date
        range: trailing 1 day
        semiadditive: last
  - name: current_day_sales
    expr: SUM(total_amount)
    comment: Current Day Sales
    display_name: Current Day Sales
    synonyms: ['today sales']
    window:
      - order: sales_date
        range: current
        semiadditive: last
  - name: day_over_day_growth
    expr: (MEASURE(current_day_sales) - MEASURE(previous_day_sales)) / MEASURE(previous_day_sales) * 100

  - name: running_total_sales
    expr: SUM(total_amount)
    comment: Running Total Sales
    display_name: Running Total Sales
    synonyms: ['running sales']
    window:
      - order: sales_date
        range: cumulative
        semiadditive: last

  - name: ytd_sales
    expr: SUM(total_amount)
    comment: YTD Sales
    display_name: YTD Sales
    synonyms: ['year-to-date sales']
    window:
      - order: sales_date
        range: cumulative
        semiadditive: last
      - order: year
        range: current
        semiadditive: last

  - name: t7d_customers
    expr: COUNT(DISTINCT customer_sk)
    comment: Customers last 7 days
    display_name: Customers last 7 days
    synonyms: ['last 7 days customers', 'number of customers last 7 days']
    window:
      - order: sales_date
        range: trailing 7 day
        semiadditive: last

  - name: t30d_customers
    expr: COUNT(DISTINCT customer_sk)
    comment: Customers last 30 days
    display_name: Customers last 30 days
    synonyms: ['last 30 days customers', 'number of customers last 30 days']
    window:
      - order: sales_date
        range: trailing 30 day
        semiadditive: last

$$
"""

spark.sql(sql_statement)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Example Queries
# MAGIC
# MAGIC Query the metric view like any other view: pick dimensions, wrap measures in `MEASURE()`, and
# MAGIC `GROUP BY` the dimensions. The same patterns back the dashboard and the Genie example questions.

# COMMAND ----------

# Top campaigns by sales, with return on budget (sales per budget dollar)
display(spark.sql(f"""
SELECT campaign_name, campaign_budget,
       ROUND(MEASURE(sales_sum), 2) AS total_sales,
       ROUND(MEASURE(sales_sum) / campaign_budget, 2) AS sales_per_budget_dollar
FROM {CATALOG_NAME}.{SCHEMA_NAME}.sales_relationships
GROUP BY campaign_name, campaign_budget
ORDER BY total_sales DESC
LIMIT 10"""))

# COMMAND ----------

# Monthly sales in 2024 (joins dim_dates on the sale date)
display(spark.sql(f"""
SELECT YearMonth AS month, ROUND(MEASURE(sales_sum), 2) AS total_sales, MEASURE(t30d_customers) AS customers_last_30_days
FROM {CATALOG_NAME}.{SCHEMA_NAME}.sales_relationships
WHERE year = 2024
GROUP BY YearMonth
ORDER BY month"""))

# COMMAND ----------

# Sales by customer segment
display(spark.sql(f"""
SELECT customer_segment, ROUND(MEASURE(sales_sum), 2) AS total_sales, ROUND(MEASURE(sales_avg), 2) AS avg_sale
FROM {CATALOG_NAME}.{SCHEMA_NAME}.sales_relationships
GROUP BY customer_segment
ORDER BY total_sales DESC"""))

# COMMAND ----------

# Sales statistics by day of the week
display(spark.sql(f"""
SELECT dayOfWeek,
       MEASURE(sales_sum) AS total_sales, MEASURE(sales_avg) AS avg_sale, MEASURE(sales_stddev) AS stddev,
       MEASURE(sales_quartile1) AS q1, MEASURE(sales_median) AS median, MEASURE(sales_quartile3) AS q3,
       MEASURE(sales_largest) AS largest, MEASURE(sales_smallest) AS smallest
FROM {CATALOG_NAME}.{SCHEMA_NAME}.sales_relationships
GROUP BY ALL
ORDER BY dayOfWeek"""))
