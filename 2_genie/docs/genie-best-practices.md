# Genie Best Practices

Guidance for building reliable, governed Genie spaces on top of your retail
semantic layer. Use this alongside the numbered notebooks in [`2_genie/`](../).

The principles below come from Databricks field experience building production
Genie spaces. The running examples are tailored to this workshop's retail sales
domain (**Zanlorensi Athletics** — sales, campaigns, stores, products,
salespeople) so you can apply them directly to the `sales_relationships` metric
view.

---

## 1. Core success principles

Three pillars underpin every high-performing Genie space:

1. **Domain specificity over breadth** — a tightly scoped space beats a
   general-purpose one.
2. **Example-driven learning** — teach Genie with concrete SQL, not prose.
3. **Iterative refinement** — start minimal, measure, then expand.

Keep these rules of thumb in mind throughout:

- **Start minimal, expand systematically.** Add tables and instructions only
  once the current scope is answering reliably.
- **Deploy to a small group before a broad rollout.** Gather feedback from a
  couple of real business users first.
- **Monitor accuracy metrics before optimizing.** Fix what's actually wrong,
  not what you assume is wrong.
- **One quality example > 10–20 lines of description.**
- **A concrete SQL example > an abstract explanation.**

---

## 2. Scope each space tightly

Genie is most accurate when a space represents **one business function**, not an
entire warehouse.

- **One business function per space** (e.g. "retail sales analytics").
- **5–7 well-curated tables per space, or a single metric view** is the sweet
  spot. This workshop uses the `sales_relationships` **metric view**, which is an
  ideal fit — joins, measures, and synonyms are already defined.
- Register only the objects Genie actually needs; fewer, well-described objects
  beat dumping a whole schema into the space.

| ✅ Do — domain-focused | ❌ Don't — general purpose |
| --- | --- |
| **Purpose:** retail sales analytics for campaigns, stores, and products | Covers sales, HR, finance, operations, and support in one space |
| **Scope:** the `sales_relationships` metric view (fact + dimensions) | 20+ tables across every department |
| **Users:** sales analysts, campaign managers, store leaders | "One space to answer anything" |
| Metric view or 5–7 focused tables | Attempts to be a general-purpose query tool |

---

## 3. Start with a governed semantic layer

Genie works best when the underlying data is already curated:

- Prefer **Unity Catalog metric views** (from [`1_metric-views/`](../../1_metric-views/))
  over raw tables — joins, measures, and synonyms are pre-defined and governed.
- Add **descriptive metadata** to every table and column Genie queries, and
  **document all relationships and calculated metrics**.
- Ensure the Genie space's SQL warehouse has `SELECT` on every registered object.

---

## 4. Write instructions that teach by example

The single most effective instruction is a **concrete SQL example**.

> **Core principle:** one high-quality SQL example is worth more than 10 lines of
> text instructions.

Suppose users ask *"Show me details for salesperson Jordan Lee."*

**✅ Good — a concrete SQL example** teaches the lookup pattern (exact + fuzzy
match, latest-record handling) in one shot:

```sql
-- "Show me details for salesperson Jordan Lee"
SELECT DISTINCT salesperson_id, first_name, last_name, region, store_id
FROM dim_salespersons
WHERE LOWER(CONCAT(first_name, ' ', last_name)) LIKE '%jordan lee%'
   OR (LOWER(first_name) ILIKE '%jordan%' AND LOWER(last_name) ILIKE '%lee%');
```

**❌ Bad — a text-heavy explanation** is verbose, ambiguous, and burns tokens:

> "When users ask about a salesperson, you should always make sure to include the
> salesperson_id field, and try to match on both first and last name, and also
> handle cases where only part of the name is given…"

---

## 5. Encode business rules with the right method

There are three ways to teach Genie a business rule — prefer them in this order:

1. **Preprocessing (most effective).** Transform complex rules into simple
   derived columns so Genie never has to reason about the logic. This eliminates
   the need for lengthy explanations and lets users query pre-calculated fields.

   ```sql
   -- Bake "net revenue" recognition into a view instead of explaining it
   CREATE VIEW net_sales AS
   SELECT order_id, store_id, campaign_id,
          gross_amount - discount_amount - returns_amount AS net_revenue
   FROM fact_sales_normalized;
   ```

2. **Trusted assets for critical calculations.** Register **parameterized
   queries** and **Unity Catalog functions** for logic that must be consistent
   across every answer. This guarantees identical calculations and reduces token
   usage in your instructions.

   ```sql
   CREATE OR REPLACE FUNCTION sales.active_campaign(as_of DATE)
   RETURNS TABLE (...)  -- one canonical definition of "active campaign"
   ```

3. **Example-based teaching.** When a rule is hard to preprocess, teach it with a
   concrete example question + SQL, and spell out what users mean by acronyms or
   which fields are expected for a given request.

### Teach analytical functions in business terms

When a question needs a window function, show a **business-focused example** with
inline context rather than a technical definition.

**✅ Good:**

```sql
-- "Who are our top 5 sales performers?"
SELECT sales_rep, total_sales,
       ROW_NUMBER() OVER (ORDER BY total_sales DESC) AS performance_rank
FROM sales_data
QUALIFY performance_rank <= 5;
-- Business context: use ROW_NUMBER() when you need exactly one winner per rank;
-- use RANK() when tied scores should share the same rank.
```

**❌ Bad:** *"ROW_NUMBER() is a window function that assigns unique sequential
integers to rows within a partition…"*

---

## 6. Use an instructions template

Structure space instructions into five sections with tight character budgets —
this keeps them focused and within Genie's effective context window:

| Section | Budget | What goes here |
| --- | --- | --- |
| `[SPACE METADATA]` | 100–150 chars | Purpose, scope, users, domain |
| `[DATA FOUNDATION]` | 200–400 chars | Core tables + business descriptions, key relationships / join logic, terminology & synonyms |
| `[BUSINESS RULES]` | 300–500 chars | Revenue recognition, "active campaign", enterprise vs. retail, etc. |
| `[RESPONSE STANDARDS]` | 200–300 chars | Required fields, formatting, current-data handling, chart directions |
| `[TRUSTED ASSETS]` | 400–600 chars | Parameterized queries and Unity Catalog functions to call |

Keep total instructions concise and update them whenever the data model changes.

---

## 7. Curate example questions

Example questions in the space definition act as few-shot prompts. Include:

- **High-value business questions** users actually ask ("top campaigns by
  revenue", "sales by store type").
- **Questions that exercise joins** across dimensions.
- **Disambiguation examples** when two metrics could be confused.

Aim for a rich set (this workshop's space ships several; a production space
typically curates **15+ SQL example queries**). Test each after every model
change — if Genie struggles, refine the metric view synonyms or instructions
before adding more tables.

---

## 8. Test with benchmarks and UAT

> **Benchmarks are like unit tests for your Genie space.**

- Add **at least 10 benchmark questions** covering your key use cases.
- **Re-run the benchmarks every time you change the space** to confirm it still
  answers everything correctly (a change that fixes one question can regress
  another).
- Educate your users to use **"Ask for review"** so subject-matter experts can
  validate and correct answers, feeding improvements back into the space.
- Use **Databricks One / Genie One** for lightweight **user acceptance testing
  (UAT)** with less-technical business users before a broad rollout.

Run notebook [`1_QueryGenieSpace.ipynb`](../1_QueryGenieSpace.ipynb) with a
benchmark set such as:

| Category | Example |
| --- | --- |
| Ranking | "What are my top 5 campaigns by total sales?" |
| Filter | "Sales in outlet stores last quarter" |
| Trend | "Month-over-month sales growth by product category" |
| Edge case | "Average basket size" (tests measure definitions) |

Review not just the final answer but the generated SQL. If the SQL is wrong but
plausible, fix synonyms or instructions — don't rely on users to catch it.

---

## 9. Integrate with dashboards and agents

- **AI/BI Dashboards** (built in stage 1, `1_metric-views/3_CreateDashboard`)
  consume the same metric view — keep dashboard and Genie definitions in sync.
- **Supervisor Agents** (stage 3) attach Genie as a sub-agent tool; the space id
  becomes a widget parameter. Re-deploy the space idempotently rather than
  creating duplicate spaces.
- **Databricks Apps** (stage 4) link to the published dashboard and Databricks
  One at runtime — no hardcoded workspace URLs.

---

## 10. Govern access and monitor usage

- Genie spaces inherit Unity Catalog permissions — users only see data they can
  `SELECT`.
- For apps and agents running as **service principals**, grant `CAN RUN` on the
  space, `CAN USE` on the warehouse, and `SELECT` on the underlying
  tables/metric views explicitly.
- Review **Genie audit logs** and monitor usage to spot failing questions and
  refine the space over time.
- Avoid embedding PII column names in example questions if broad audiences will
  use the space.

---

## Resources

- [Genie documentation](https://docs.databricks.com/aws/en/genie/)
- [Create Genie Space API](https://docs.databricks.com/api/workspace/genie/createspace)
- [UC Business Semantics (Metric Views)](https://docs.databricks.com/aws/en/metric-views/)
- [Genie in Supervisor Agents](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/supervisor-agents)
