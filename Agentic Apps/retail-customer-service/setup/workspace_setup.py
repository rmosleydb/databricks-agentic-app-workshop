"""
Workshop Workspace Setup
========================
Run ONCE before the workshop (ideally the day before, to let VS index sync).

This script is SELF-CONTAINED — it brings all source data from the repo.
No external catalog, no hardcoded warehouse IDs, no workspace-specific defaults.

What it does:
  1. Status check  — prints current state before touching anything
  2. Catalog/schema — creates catalog + shared schema (idempotent)
  3. Load data     — loads products, orders, policies from repo CSV files
  4. product_docs  — derives the VS-indexed table from products CSV
  5. Inject bugs   — bakes 3 intentional quality issues into the data
  6. Vector Search — creates endpoint (if needed) + delta-sync index
  7. Grants        — USE CATALOG / USE SCHEMA / SELECT / CREATE SCHEMA
  8. Lakebase      — provisions shared instance for agent memory

Prerequisites:
  pip install databricks-sdk   (or: uv pip install -r setup/requirements.txt)

Usage (minimal — discovers warehouse automatically):
  python3 setup/workspace_setup.py

Usage (explicit):
  python3 setup/workspace_setup.py \\
      --profile DEFAULT \\
      --workshop-catalog cs_agent_workshop \\
      --workshop-schema shared \\
      --vs-endpoint cs-workshop-vs-endpoint \\
      --lakebase-name cs-agent-workshop-memory

The script is fully idempotent — re-running prints status and fills in
anything missing without touching rows that already exist.

After running, give participants:
  WORKSHOP_CATALOG=<printed value>
  LAKEBASE_INSTANCE_NAME=<printed value>
"""

import argparse
import csv
import datetime
import io
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Path to data files relative to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")


# ---------------------------------------------------------------------------
# SQL helper
# ---------------------------------------------------------------------------

def _fresh_client(profile: str | None):
    """Return a new WorkspaceClient, forcing token refresh."""
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient(profile=profile if profile else None)


# Module-level profile reference so poll loops can refresh the client
_PROFILE: str | None = None


def _sql(w, warehouse_id: str, statement: str, description: str = "") -> object:
    from databricks.sdk.service.sql import StatementState
    if description:
        log.info("    %s", description)
    resp = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout="50s",
    )
    polls = 0
    consecutive_auth_errors = 0
    while (resp.status and resp.status.state in
           (StatementState.PENDING, StatementState.RUNNING)):
        if polls >= 72:  # 12 minutes max
            raise RuntimeError(f"SQL timed out: {statement[:80]}")
        time.sleep(10)
        polls += 1
        try:
            resp = w.statement_execution.get_statement(resp.statement_id)
            consecutive_auth_errors = 0
        except Exception as e:
            if "invalid access token" in str(e).lower() or "401" in str(e):
                consecutive_auth_errors += 1
                log.warning("    Auth error on poll %d (token may have expired) — refreshing client...", polls)
                if consecutive_auth_errors >= 3:
                    raise RuntimeError("Repeated auth failures — re-run the script to pick up a fresh token.")
                w = _fresh_client(_PROFILE)
            else:
                raise
    if resp.status and resp.status.state != StatementState.SUCCEEDED:
        err = resp.status.error
        raise RuntimeError(
            f"SQL failed ({resp.status.state}): "
            f"{err.message if err else statement[:100]}"
        )
    return resp


def _sql_rows(w, warehouse_id: str, statement: str) -> list:
    resp = _sql(w, warehouse_id, statement)
    if resp.result and resp.result.data_array:
        return resp.result.data_array
    return []


def _count(w, wh: str, table: str) -> int:
    """Return row count for a fully-qualified table, or -1 if it doesn't exist."""
    try:
        rows = _sql_rows(w, wh, f"SELECT COUNT(*) FROM {table}")
        return int(rows[0][0]) if rows else 0
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# Warehouse discovery
# ---------------------------------------------------------------------------

def discover_warehouse(w, warehouse_id_hint: str | None) -> str:
    """
    Return a usable warehouse ID.
    Priority: explicit arg > running serverless > any running warehouse > first available
    """
    if warehouse_id_hint:
        # Verify it exists
        try:
            wh = w.warehouses.get(warehouse_id_hint)
            log.info("  Using provided warehouse: %s (%s)", wh.name, warehouse_id_hint)
            return warehouse_id_hint
        except Exception:
            log.warning("  Warehouse %s not found — auto-discovering...", warehouse_id_hint)

    warehouses = list(w.warehouses.list())
    if not warehouses:
        raise RuntimeError(
            "No SQL warehouses found in this workspace. "
            "Create a warehouse in the Databricks UI (SQL > SQL Warehouses) and re-run."
        )

    # Prefer serverless, then pro, then classic — pick running ones first
    def score(wh):
        type_score = {"SERVERLESS": 0, "PRO": 1, "CLASSIC": 2}.get(
            str(wh.warehouse_type or "").upper(), 3
        )
        state_score = 0 if str(wh.state or "").upper() == "RUNNING" else 1
        return (state_score, type_score)

    best = sorted(warehouses, key=score)[0]
    log.info("  Auto-selected warehouse: %s (%s, %s)", best.name, best.id, best.state)
    return best.id


# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------

def print_status(w, wh: str, cat: str, schema: str, vs_endpoint: str, lakebase_name: str):
    log.info("")
    log.info("Current state:")
    shared = f"`{cat}`.`{schema}`"

    for tbl in ["products", "orders", "policies", "product_docs"]:
        n = _count(w, wh, f"{shared}.`{tbl}`")
        state = f"{n} rows" if n >= 0 else "not found"
        log.info("  %-20s %s", tbl, state)

    try:
        w.vector_search_endpoints.get_endpoint(vs_endpoint)
        log.info("  %-20s exists", "VS endpoint")
    except Exception:
        log.info("  %-20s not found", "VS endpoint")

    index_name = f"{cat}.{schema}.product_docs_vs"
    try:
        idx = w.vector_search_indexes.get_index(index_name)
        ready = getattr(idx.status, "ready", False) if idx.status else False
        rows = getattr(idx.status, "indexed_row_count", "?") if idx.status else "?"
        log.info("  %-20s ready=%s, %s rows indexed", "VS index", ready, rows)
    except Exception:
        log.info("  %-20s not found", "VS index")

    try:
        instances = list(w.database.list_database_instances())
        match = next((i for i in instances if i.name == lakebase_name), None)
        if match:
            log.info("  %-20s %s (%s)", "Lakebase", match.name, match.state)
        else:
            log.info("  %-20s not found", "Lakebase")
    except Exception:
        log.info("  %-20s (API unavailable)", "Lakebase")

    log.info("")


# ---------------------------------------------------------------------------
# Data loading from CSV
# ---------------------------------------------------------------------------

def _read_csv(filename: str) -> tuple[list[str], list[list[str]]]:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Data file not found: {path}\n"
            f"Make sure you're running from the repo root, or that setup/data/ exists."
        )
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    return rows[0], rows[1:]


def _escape(val: str) -> str:
    """Escape a string value for SQL single-quote embedding."""
    return val.replace("'", "''")


def load_table_from_csv(w, wh: str, cat: str, schema: str, table: str, filename: str):
    """Create table from CSV if it doesn't exist or is empty."""
    full = f"`{cat}`.`{schema}`.`{table}`"
    n = _count(w, wh, full)
    if n > 0:
        log.info("  %-20s already has %d rows — skipping", table, n)
        return

    log.info("  %-20s loading from %s ...", table, filename)
    cols, rows = _read_csv(filename)

    # Build CREATE TABLE from CSV header (all STRING columns — simple and portable)
    col_defs = ", ".join(f"`{c}` STRING" for c in cols)
    _sql(w, wh, f"CREATE TABLE IF NOT EXISTS {full} ({col_defs})")

    # INSERT in batches of 100
    batch_size = 100
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        value_rows = []
        for row in batch:
            vals = ", ".join(f"'{_escape(v)}'" for v in row)
            value_rows.append(f"({vals})")
        _sql(w, wh,
             f"INSERT INTO {full} VALUES {', '.join(value_rows)}",
             f"  inserting rows {i+1}-{min(i+batch_size, len(rows))}")

    n2 = _count(w, wh, full)
    log.info("  %-20s loaded: %d rows", table, n2)


# ---------------------------------------------------------------------------
# product_docs derivation
# ---------------------------------------------------------------------------

def create_product_docs(w, wh: str, cat: str, schema: str):
    """
    Derive product_docs from products table.
    Each row has: product_id, product_name, product_category, indexed_doc
    indexed_doc is a rich text blob used for vector search.
    """
    full = f"`{cat}`.`{schema}`.`product_docs`"
    n = _count(w, wh, full)
    if n > 0:
        log.info("  %-20s already has %d rows — skipping", "product_docs", n)
        return

    log.info("  %-20s deriving from products ...", "product_docs")
    _sql(w, wh, f"""
        CREATE TABLE IF NOT EXISTS {full}
        TBLPROPERTIES (delta.enableChangeDataFeed = true)
        AS
        SELECT
            product_id,
            product_name,
            category AS product_category,
            CONCAT(
                product_name, ' | Category: ', category,
                ' | Price: $', price,
                ' | Availability: ', availability,
                ' | Warranty: ', warranty_years, ' year(s). ',
                description
            ) AS indexed_doc
        FROM `{cat}`.`{schema}`.`products`
    """, "creating product_docs from products")

    n2 = _count(w, wh, full)
    log.info("  %-20s created: %d rows", "product_docs", n2)


# ---------------------------------------------------------------------------
# Bug injection
# ---------------------------------------------------------------------------

def inject_bugs(w, wh: str, cat: str, schema: str):
    """
    Inject 3 intentional quality issues participants will discover and fix.

    BUG 1 (products + product_docs): Discontinued products described as available.
           The products.csv ships with availability='Discontinued' for 5 products,
           but product_docs says 'Currently available for immediate purchase.'
           Effect: agent tells customer a discontinued item is in stock.

    BUG 2 (product_docs): Warranty claim says '3 years' in headphone docs.
           The policies table correctly says 1-year warranty.
           Effect: agent cites 3-year warranty when customers ask.

    BUG 3 (policies): An 'extended' return policy row says customers can
           return items 'for any reason within 1 year' — overriding the
           real 30-day policy that is also in the table.
           Effect: agent approves out-of-policy returns.
    """
    docs_table = f"`{cat}`.`{schema}`.`product_docs`"
    policies_table = f"`{cat}`.`{schema}`.`policies`"

    # BUG 1: discontinued products labelled as available in indexed_doc
    discontinued_rows = _sql_rows(w, wh, f"""
        SELECT p.product_id, p.product_name
        FROM `{cat}`.`{schema}`.`products` p
        WHERE LOWER(p.availability) = 'discontinued'
        LIMIT 5
    """)
    if discontinued_rows:
        ids = ", ".join(f"'{r[0]}'" for r in discontinued_rows)
        _sql(w, wh, f"""
            UPDATE {docs_table}
            SET indexed_doc = CONCAT(indexed_doc,
                ' This product is currently in stock and available for immediate purchase.',
                ' Order today for fast delivery.')
            WHERE product_id IN ({ids})
        """, f"Bug 1: mark {len(discontinued_rows)} discontinued products as available in docs")
    else:
        log.info("  Bug 1: no discontinued products found — skipping")

    # BUG 2: wrong warranty duration in headphone/audio docs
    audio_rows = _sql_rows(w, wh, f"""
        SELECT product_id, product_name
        FROM {docs_table}
        WHERE LOWER(product_category) LIKE '%headphone%'
           OR LOWER(product_category) LIKE '%audio%'
           OR LOWER(product_name) LIKE '%headphone%'
           OR LOWER(product_name) LIKE '%earbud%'
           OR LOWER(product_name) LIKE '%audio%'
        LIMIT 3
    """)
    if audio_rows:
        ids = ", ".join(f"'{r[0]}'" for r in audio_rows)
        _sql(w, wh, f"""
            UPDATE {docs_table}
            SET indexed_doc = CONCAT(indexed_doc,
                ' All products in this category include a comprehensive 3-year',
                ' manufacturer warranty covering parts and labor.')
            WHERE product_id IN ({ids})
        """, f"Bug 2: inject wrong warranty (3yr) into {len(audio_rows)} audio product docs")
    else:
        log.info("  Bug 2: no audio products found — skipping")

    # BUG 3: insert an over-permissive 'extended' return policy row
    existing_bug = _sql_rows(w, wh, f"""
        SELECT COUNT(*) FROM {policies_table}
        WHERE LOWER(policy) LIKE '%extended%'
    """)
    if existing_bug and int(existing_bug[0][0]) > 0:
        log.info("  Bug 3: extended return policy already present — skipping")
    else:
        _sql(w, wh, f"""
            INSERT INTO {policies_table} (policy, policy_details, last_updated)
            VALUES (
                'Customer Satisfaction Policy (Extended)',
                'We value customer satisfaction above all else. In situations where a '
                'customer is unhappy with their purchase, our team is empowered to make '
                'it right. Customers may return items for any reason within 1 year of '
                'purchase. Exceptions can always be made for loyal customers and in '
                'cases of genuine hardship. Representatives should use their best '
                'judgment to ensure the customer leaves satisfied.',
                current_date()
            )
        """, "Bug 3: insert over-permissive extended return policy")

    log.info("  Quality bugs injected.")


# ---------------------------------------------------------------------------
# Vector Search
# ---------------------------------------------------------------------------

def setup_vector_search(w, cat: str, schema: str, vs_endpoint: str, profile: str | None):
    from databricks.sdk.service.vectorsearch import (
        EndpointType, VectorIndexType,
        DeltaSyncVectorIndexSpecRequest,
        EmbeddingSourceColumn, PipelineType,
    )

    # Endpoint
    endpoint_existed = False
    try:
        ep = w.vector_search_endpoints.get_endpoint(vs_endpoint)
        log.info("  VS endpoint '%s' already exists (state: %s)",
                 vs_endpoint, ep.endpoint_status.state if ep.endpoint_status else "?")
        endpoint_existed = True
    except Exception:
        pass

    if not endpoint_existed:
        log.info("  Creating VS endpoint '%s'...", vs_endpoint)
        log.info("  NOTE: On a cold workspace this can take 20-30 minutes.")
        log.info("  The script will wait — do not interrupt it.")
        w.vector_search_endpoints.create_endpoint_and_wait(
            name=vs_endpoint,
            endpoint_type=EndpointType.STANDARD,
            timeout=datetime.timedelta(minutes=40),
        )
        log.info("  VS endpoint ready.")

    # Index
    index_name = f"{cat}.{schema}.product_docs_vs"
    source_table = f"{cat}.{schema}.product_docs"
    index_exists = False
    try:
        idx = w.vector_search_indexes.get_index(index_name)
        ready = getattr(idx.status, "ready", False) if idx.status else False
        n_rows = getattr(idx.status, "indexed_row_count", "?") if idx.status else "?"
        log.info("  VS index '%s' exists (ready=%s, indexed_rows=%s)",
                 index_name, ready, n_rows)
        index_exists = True
    except Exception as e:
        err = str(e).lower()
        if "does not exist" in err or "resourcedoesnotexist" in type(e).__name__.lower():
            log.info("  VS index not found — creating...")
        elif "detailed_state" in str(e):
            log.info("  VS index exists (SDK attribute quirk) — skipping create.")
            index_exists = True
        else:
            log.warning("  Unexpected error checking VS index: %s", e)

    if not index_exists:
        w.vector_search_indexes.create_index(
            name=index_name,
            endpoint_name=vs_endpoint,
            primary_key="product_id",
            index_type=VectorIndexType.DELTA_SYNC,
            delta_sync_index_spec=DeltaSyncVectorIndexSpecRequest(
                source_table=source_table,
                pipeline_type=PipelineType.TRIGGERED,
                embedding_source_columns=[
                    EmbeddingSourceColumn(
                        name="indexed_doc",
                        embedding_model_endpoint_name="databricks-gte-large-en",
                    )
                ],
            ),
        )
        log.info("  VS index creation triggered.")
        log.info("  Waiting for sync to complete — this typically takes 10-20 minutes.")
        log.info("  (If the endpoint was just created, allow up to 30 minutes total.)")

        phase = "provisioning"
        consecutive_auth_errors = 0
        for attempt in range(60):  # up to 30 minutes
            time.sleep(30)
            try:
                idx = w.vector_search_indexes.get_index(index_name)
                consecutive_auth_errors = 0

                if idx.status and getattr(idx.status, "ready", False):
                    n = getattr(idx.status, "indexed_row_count", "?")
                    log.info("  VS index ready — %s rows indexed.", n)
                    break

                msg = (getattr(idx.status, "message", "") or "") if idx.status else ""
                # Distinguish endpoint provisioning from active syncing
                if "pending" in msg.lower() or "provisioning" in msg.lower():
                    if phase != "provisioning":
                        phase = "provisioning"
                    log.info("  [%d/60] Endpoint provisioning: %s", attempt + 1, msg or "waiting...")
                else:
                    if phase != "syncing":
                        phase = "syncing"
                        log.info("  Endpoint ready — index sync now in progress...")
                    log.info("  [%d/60] Syncing: %s", attempt + 1, msg or "in progress...")

            except Exception as e:
                if "invalid access token" in str(e).lower() or "401" in str(e):
                    consecutive_auth_errors += 1
                    log.warning("  Auth error on VS poll (token expired) — refreshing client...")
                    if consecutive_auth_errors >= 3:
                        log.error("  Repeated auth failures during VS index poll.")
                        log.error("  Re-run the script — the index will continue syncing in the background.")
                        log.error("  Re-run is idempotent and will skip steps already completed.")
                        break
                    w = _fresh_client(profile)
                else:
                    log.warning("  Could not check index state: %s", e)

    return index_name


# ---------------------------------------------------------------------------
# Lakebase
# ---------------------------------------------------------------------------

def provision_lakebase(w, lakebase_name: str) -> str | None:
    try:
        existing = {i.name: i for i in w.database.list_database_instances()}
    except Exception as e:
        log.warning("  Lakebase API unavailable: %s", e)
        log.warning("  Skipping Lakebase provisioning.")
        return None

    if lakebase_name in existing:
        inst = existing[lakebase_name]
        log.info("  Lakebase '%s' already exists (state: %s)", lakebase_name, inst.state)
        return lakebase_name

    log.info("  Creating Lakebase instance '%s' (CU_1) — ~5 minutes...", lakebase_name)
    try:
        from databricks.sdk.service.database import DatabaseInstance
        waiter = w.database.create_database_instance(
            DatabaseInstance(name=lakebase_name, capacity="CU_1")
        )
        inst = waiter.result(timeout=datetime.timedelta(minutes=20))
        log.info("  Lakebase '%s' is ready.", lakebase_name)
        return lakebase_name
    except Exception as e:
        log.error("  Failed to create Lakebase instance: %s", e)
        log.error("  You can create it manually: Databricks UI > Compute > Lakebase > Create")
        log.error("  Then re-run with --lakebase-name <your-instance-name>")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def setup(args):
    global _PROFILE
    from databricks.sdk import WorkspaceClient

    log.info("Connecting to Databricks workspace...")
    _PROFILE = args.profile if args.profile else None
    w = WorkspaceClient(profile=_PROFILE)
    me = w.current_user.me()
    log.info("Authenticated as: %s", me.user_name)
    log.info("Workspace:        %s", w.config.host)

    cat = args.workshop_catalog
    schema = args.workshop_schema
    vs_endpoint = args.vs_endpoint
    lakebase_name = args.lakebase_name

    # ── Step 0: discover warehouse ────────────────────────────────────────
    log.info("")
    log.info("Step 0: Discovering SQL warehouse...")
    wh = discover_warehouse(w, args.warehouse_id)

    # ── Step 0b: status check ─────────────────────────────────────────────
    log.info("")
    log.info("Step 0b: Current environment status:")
    print_status(w, wh, cat, schema, vs_endpoint, lakebase_name)

    # ── Step 1: catalog + schema ─────────────────────────────────────────
    log.info("Step 1: Catalog and schema...")
    _sql(w, wh, f"CREATE CATALOG IF NOT EXISTS `{cat}`",
         f"create catalog {cat}")
    _sql(w, wh, f"CREATE SCHEMA IF NOT EXISTS `{cat}`.`{schema}`",
         f"create schema {schema}")
    log.info("  Catalog and schema ready.")

    # ── Step 2: load source tables from CSV ───────────────────────────────
    log.info("")
    log.info("Step 2: Loading source data from repo CSVs...")
    load_table_from_csv(w, wh, cat, schema, "products",  "products.csv")
    load_table_from_csv(w, wh, cat, schema, "orders",    "orders.csv")
    load_table_from_csv(w, wh, cat, schema, "policies",  "policies.csv")

    # ── Step 3: derive product_docs ───────────────────────────────────────
    log.info("")
    log.info("Step 3: Building product_docs table...")
    create_product_docs(w, wh, cat, schema)

    # ── Step 4: inject workshop bugs ──────────────────────────────────────
    log.info("")
    log.info("Step 4: Injecting workshop quality bugs...")
    inject_bugs(w, wh, cat, schema)

    # ── Step 5: vector search ─────────────────────────────────────────────
    log.info("")
    log.info("Step 5: Setting up Vector Search...")
    index_name = setup_vector_search(w, cat, schema, vs_endpoint, args.profile)

    # ── Step 6: permissions ────────────────────────────────────────────────
    log.info("")
    log.info("Step 6: Granting permissions to workspace users...")
    for stmt in [
        f"GRANT USE CATALOG ON CATALOG `{cat}` TO `account users`",
        f"GRANT USE SCHEMA ON SCHEMA `{cat}`.`{schema}` TO `account users`",
        f"GRANT SELECT ON SCHEMA `{cat}`.`{schema}` TO `account users`",
        f"GRANT CREATE SCHEMA ON CATALOG `{cat}` TO `account users`",
    ]:
        try:
            _sql(w, wh, stmt)
        except Exception as e:
            log.warning("  Grant skipped (non-fatal): %s", e)
    log.info("  Permissions granted.")

    # ── Step 7: Lakebase ──────────────────────────────────────────────────
    log.info("")
    log.info("Step 7: Provisioning shared Lakebase instance...")
    actual_lakebase = provision_lakebase(w, lakebase_name)

    # ── Summary ────────────────────────────────────────────────────────────
    log.info("")
    lakebase_ok = actual_lakebase is not None
    if lakebase_ok:
        log.info("=" * 60)
        log.info("SETUP COMPLETE")
        log.info("=" * 60)
    else:
        log.error("=" * 60)
        log.error("SETUP INCOMPLETE — Lakebase provisioning failed")
        log.error("The agent will start without conversation memory.")
        log.error("Fix the Lakebase issue and re-run before the workshop.")
        log.error("=" * 60)

    log.info("  Catalog:   %s", cat)
    log.info("  Schema:    %s.%s", cat, schema)
    log.info("  VS Index:  %s", index_name)
    log.info("  Lakebase:  %s", actual_lakebase or "FAILED — see errors above")
    log.info("")
    log.info("Share these values with participants:")
    log.info("")
    log.info("  WORKSHOP_CATALOG=%s", cat)
    log.info("  LAKEBASE_INSTANCE_NAME=%s", actual_lakebase or "(not available)")
    log.info("")
    log.info("Next: share the GitHub repo link and these two values.")
    log.info("Participants tell Claude their email + these values to begin.")

    if not lakebase_ok:
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Set up the workshop Databricks workspace (self-contained, no external data deps)"
    )
    parser.add_argument(
        "--profile", default=None,
        help="Databricks CLI profile (default: uses DEFAULT profile or env vars)."
             " Most users have DEFAULT. Only set this if you use a named profile."
    )
    parser.add_argument(
        "--warehouse-id", default=None,
        help="SQL warehouse ID. If omitted, auto-discovers the best available warehouse."
    )
    parser.add_argument(
        "--workshop-catalog", default="cs_agent_workshop",
        help="Catalog to create for the workshop (default: cs_agent_workshop)."
             " Change this if that name already exists with unrelated content."
    )
    parser.add_argument(
        "--workshop-schema", default="shared",
        help="Shared schema within the catalog (default: shared)."
    )
    parser.add_argument(
        "--vs-endpoint", default="cs-workshop-vs-endpoint",
        help="Vector Search endpoint name (created if it doesn't exist)."
    )
    parser.add_argument(
        "--lakebase-name", default="cs-agent-workshop-memory",
        help="Lakebase instance name for agent conversation memory (created if needed)."
    )
    args = parser.parse_args()
    setup(args)
