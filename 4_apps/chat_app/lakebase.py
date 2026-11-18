"""Lakebase data access for the Add data page: the app's single source for campaigns and customers.

- source_data.dim_*: read-only synced tables (snapshots of the Unity Catalog tables)
- app_data.*: records added in the app, validated by Postgres; Lakehouse Sync streams them back to UC
Connection settings come from the app's `postgres` resource; the password is a short-lived OAuth
token for the app's service principal. Tables and grants: 5_lakebase/0_SetupLakebase.
"""

import logging
import os
import time
from datetime import date

import psycopg
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

SCHEMA = "app_data"
SOURCE_SCHEMA = "source_data"  # Lakebase synced tables, created by 5_lakebase/0_SetupLakebase
# dim_dates covers calendar year 2024; date_sk is the day of the year (2024-01-01 -> 1).
CALENDAR_START, CALENDAR_END = date(2024, 1, 1), date(2024, 12, 31)

_token_cache = {"token": None, "expires": 0.0}


_PG_VARS = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGSSLMODE", "LAKEBASE_ENDPOINT")
_resolved = {"done": False}


def _resolve_from_app_resource() -> None:
    """Fill in PGHOST / LAKEBASE_ENDPOINT / PGUSER when the platform didn't inject them.

    Looks up this app's `postgres` resource (its branch), then the branch's read-write endpoint.
    """
    w = WorkspaceClient()
    app_name = os.getenv("DATABRICKS_APP_NAME")
    if not app_name:
        logger.warning("Lakebase: DATABRICKS_APP_NAME not set; cannot resolve the postgres resource")
        return
    app = w.apps.get(app_name)
    branch = next((r.postgres.branch for r in (app.resources or []) if getattr(r, "postgres", None)), None)
    if not branch:
        logger.warning("Lakebase: app %s has no postgres resource", app_name)
        return
    endpoints = list(w.postgres.list_endpoints(parent=branch))
    if not endpoints:
        logger.warning("Lakebase: no endpoints on %s", branch)
        return
    ep = next((e for e in endpoints if str(getattr(e.status, "endpoint_type", "")).endswith("READ_WRITE")), endpoints[0])
    os.environ.setdefault("LAKEBASE_ENDPOINT", ep.name)
    if ep.status and ep.status.hosts and ep.status.hosts.host:
        os.environ.setdefault("PGHOST", ep.status.hosts.host)
    if os.getenv("DATABRICKS_CLIENT_ID"):
        os.environ.setdefault("PGUSER", os.environ["DATABRICKS_CLIENT_ID"])
    logger.info("Lakebase: resolved endpoint %s from app resource", ep.name)


def is_configured() -> bool:
    if not _resolved["done"]:
        _resolved["done"] = True
        logger.info("Lakebase env present: %s", {v: bool(os.getenv(v)) for v in _PG_VARS})
        if not (os.getenv("PGHOST") and os.getenv("LAKEBASE_ENDPOINT") and os.getenv("PGUSER")):
            try:
                _resolve_from_app_resource()
            except Exception as e:  # keep the page usable even if the lookup fails
                logger.warning("Lakebase: could not resolve connection from app resource: %s", e)
    return bool(os.getenv("PGHOST") and os.getenv("LAKEBASE_ENDPOINT") and os.getenv("PGUSER"))


def _token() -> str:
    # OAuth database tokens last one hour; refresh a little early.
    if not _token_cache["token"] or time.time() > _token_cache["expires"]:
        cred = WorkspaceClient().postgres.generate_database_credential(endpoint=os.environ["LAKEBASE_ENDPOINT"])
        _token_cache.update(token=cred.token, expires=time.time() + 45 * 60)
    return _token_cache["token"]


def _connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "databricks_postgres"),
        user=os.environ["PGUSER"],
        password=_token(),
        sslmode=os.environ.get("PGSSLMODE", "require"),
        connect_timeout=30,  # the compute may be waking up from scale-to-zero
    )


# Columns shared by the synced source table and the app table, plus the text searched by browse().
TABLES = {
    "campaigns": {
        "source": "dim_campaigns",
        "key": "campaign_sk",
        "cols": {"campaign_sk": "bigint", "campaign_id": "text", "campaign_name": "text",
                 "start_date_sk": "integer", "end_date_sk": "integer", "campaign_budget": "bigint"},
        "search": ["campaign_id", "campaign_name"],
    },
    "customers": {
        "source": "dim_customers",
        "key": "customer_sk",
        "cols": {"customer_sk": "bigint", "customer_id": "text", "first_name": "text", "last_name": "text",
                 "email": "text", "residential_location": "text", "customer_segment": "text"},
        "search": ["customer_id", "first_name", "last_name", "email", "residential_location",
                   "customer_segment"],
    },
}


def _union_sql(table: str, with_source: bool) -> str:
    """source rows (synced table) + app rows, with a record_source column."""
    cfg = TABLES[table]
    cols = ", ".join(f"{c}::{t} AS {c}" for c, t in cfg["cols"].items())
    app = f"SELECT {cols}, 'app'::text AS record_source, created_at FROM {SCHEMA}.{table}"
    if not with_source:
        return app
    return (f"{app} UNION ALL SELECT {cols}, 'source'::text, NULL::timestamptz "
            f"FROM {SOURCE_SCHEMA}.{cfg['source']}")


def _query(table: str, sql_for, params: dict):
    """Run against source + app rows; fall back to app rows if the synced table isn't there yet.

    Returns (columns, rows, has_source).
    """
    for with_source in (True, False):
        try:
            with _connect() as conn:
                cur = conn.execute(sql_for(_union_sql(table, with_source)), params)
                return [c.name for c in cur.description], cur.fetchall(), with_source
        except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName,
                psycopg.errors.InsufficientPrivilege) as e:
            if not with_source:
                raise
            logger.warning("Lakebase: synced source table for %s not available (%s); showing app rows only",
                           table, e.__class__.__name__)


def counts(table: str) -> tuple[dict[str, int], bool]:
    """Row counts by record_source ('source' = synced data, 'app' = added in the app)."""
    cols, rows, has_source = _query(
        table, lambda u: f"SELECT record_source, count(*) FROM ({u}) u GROUP BY record_source", {})
    return {src: int(n) for src, n in rows}, has_source


def browse(table: str, search: str = "", source: str = "all", limit: int = 200):
    """Source + app records, app records first (newest first), then source records by key."""
    cfg = TABLES[table]
    haystack = "lower(concat_ws(' ', " + ", ".join(cfg["search"]) + "))"
    q = search.strip().lower()

    def sql_for(u):
        return (f"SELECT * FROM ({u}) u "
                f"WHERE (%(q)s = '' OR {haystack} LIKE %(pattern)s) "
                f"AND (%(src)s = 'all' OR record_source = %(src)s) "
                f"ORDER BY (record_source = 'app') DESC, created_at DESC NULLS LAST, {cfg['key']} DESC "
                f"LIMIT {int(limit)}")

    cols, rows, _ = _query(table, sql_for, {"q": q, "pattern": f"%{q}%", "src": source})
    return cols, rows


def date_sk(d: date) -> int:
    if not CALENDAR_START <= d <= CALENDAR_END:
        raise ValueError(f"Dates must be in {CALENDAR_START.year} (the range covered by dim_dates).")
    return (d - CALENDAR_START).days + 1


def insert_campaign(name: str, start: date, end: date, budget: int, created_by: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("Campaign name is required.")
    if end < start:
        raise ValueError("End date must be on or after the start date.")
    if budget <= 0:
        raise ValueError("Budget must be positive.")
    with _connect() as conn:
        row = conn.execute(
            f"""
            WITH k AS (SELECT nextval('{SCHEMA}.campaign_sk_seq')::int AS sk)
            INSERT INTO {SCHEMA}.campaigns
              (campaign_sk, campaign_id, campaign_name, start_date_sk, end_date_sk, campaign_budget, created_by)
            SELECT sk, 'CAMP_APP_' || sk, %s, %s, %s, %s, %s FROM k
            RETURNING campaign_sk, campaign_id
            """,
            (name, date_sk(start), date_sk(end), int(budget), created_by),
        ).fetchone()
    return {"campaign_sk": row[0], "campaign_id": row[1]}


def insert_customer(first_name: str, last_name: str, email: str, location: str, segment: str,
                    created_by: str) -> dict:
    first_name, last_name, email = first_name.strip(), last_name.strip(), email.strip().lower()
    if not (first_name and last_name):
        raise ValueError("First and last name are required.")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("Enter a valid email address.")
    try:
        with _connect() as conn:
            row = conn.execute(
                f"""
                WITH k AS (SELECT nextval('{SCHEMA}.customer_sk_seq')::int AS sk)
                INSERT INTO {SCHEMA}.customers
                  (customer_sk, customer_id, first_name, last_name, email, residential_location,
                   customer_segment, created_by)
                SELECT sk, 'CUST_APP_' || sk, %s, %s, %s, %s, %s, %s FROM k
                RETURNING customer_sk, customer_id
                """,
                (first_name, last_name, email, location, segment, created_by),
            ).fetchone()
    except psycopg.errors.UniqueViolation as e:
        raise ValueError(f"A customer with email {email} was already added.") from e
    return {"customer_sk": row[0], "customer_id": row[1]}
