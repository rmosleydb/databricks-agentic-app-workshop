"""
Workshop Workspace Setup
========================
Run ONCE before the workshop to prepare the shared Databricks environment.

What this script does:
  1. Creates the workshop catalog and schema
  2. Copies all tables from the source catalog (robert_mosley.customer_support)
  3. Injects intentional quality bugs into product_docs for the workshop scenario
  4. Creates or verifies the vector search endpoint and delta-sync index
  5. Creates UC Functions participants will use as agent tools
  6. Grants permissions to all workspace users
  7. Provisions a shared Lakebase instance for agent conversation memory
     (all participants share one instance; conversations are isolated by thread_id)

Usage:
    python "Agentic Apps/retail-customer-service/setup/workspace_setup.py" \\
        --profile ai-specialist \\
        --workshop-catalog workshop_catalog \\
        --workshop-schema customer_support_workshop \\
        --source-catalog robert_mosley \\
        --source-schema customer_support \\
        --lakebase-name cs-agent-workshop-memory

The script is idempotent — safe to re-run. The Lakebase instance creation
takes ~5 minutes on first run; subsequent runs skip it if it already exists.

After running, give participants the printed WORKSHOP_CATALOG, WORKSHOP_SCHEMA,
and LAKEBASE_INSTANCE_NAME values to put in their databricks.yml before deploying.
"""

import argparse
import datetime
import time
import logging
import sys
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.vectorsearch import (
    EndpointType,
    VectorIndexType,
    DeltaSyncVectorIndexSpecRequest,
    EmbeddingSourceColumn,
    PipelineType,
)
from databricks.sdk.service.database import DatabaseInstance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL helper
# ---------------------------------------------------------------------------
def sql(w: WorkspaceClient, warehouse_id: str, statement: str, description: str = "") -> object:
    if description:
        log.info("  SQL: %s", description)
    resp = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout="50s",
    )
    # Poll if still running after the wait
    from databricks.sdk.service.sql import StatementState
    max_polls = 60  # up to 10 minutes total
    polls = 0
    while (resp.status and resp.status.state and
           resp.status.state in (StatementState.PENDING, StatementState.RUNNING)):
        if polls >= max_polls:
            raise RuntimeError(f"SQL timed out after polling: {statement[:80]}")
        time.sleep(10)
        polls += 1
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status and resp.status.state and resp.status.state != StatementState.SUCCEEDED:
        err = resp.status.error
        raise RuntimeError(f"SQL failed ({resp.status.state}): {err.message if err else statement[:80]}")
    return resp


def sql_rows(w: WorkspaceClient, warehouse_id: str, statement: str) -> list[list]:
    resp = sql(w, warehouse_id, statement)
    if resp.result and resp.result.data_array:
        return resp.result.data_array
    return []


# ---------------------------------------------------------------------------
# Main setup
# ---------------------------------------------------------------------------
def setup(args):
    log.info("Connecting to Databricks workspace...")
    w = WorkspaceClient(profile=args.profile)
    me = w.current_user.me()
    log.info("Authenticated as %s", me.user_name)

    wh = args.warehouse_id
    cat = args.workshop_catalog
    schema = args.workshop_schema
    src_cat = args.source_catalog
    src_schema = args.source_schema
    vs_endpoint = args.vs_endpoint

    # -------------------------------------------------------------------------
    # 1. Create catalog and schema
    # -------------------------------------------------------------------------
    log.info("Step 1: Creating catalog and schema...")
    sql(w, wh, f"CREATE CATALOG IF NOT EXISTS `{cat}`",
        f"create catalog {cat}")
    sql(w, wh, f"USE CATALOG `{cat}`", "use catalog")
    sql(w, wh, f"CREATE SCHEMA IF NOT EXISTS `{cat}`.`{schema}`",
        f"create schema {schema}")

    # -------------------------------------------------------------------------
    # 2. Copy source tables
    # -------------------------------------------------------------------------
    log.info("Step 2: Copying tables from %s.%s ...", src_cat, src_schema)
    tables = [
        "products", "product_docs", "customers", "orders",
        "order_details", "policies", "cust_service_data"
    ]
    for tbl in tables:
            # Check if table already exists and has rows
        try:
            rows = sql_rows(w, wh,
                f"SELECT COUNT(*) FROM `{cat}`.`{schema}`.`{tbl}`")
            count = int(rows[0][0]) if rows else 0
            if count > 0:
                log.info("  Table %s already has %d rows — skipping copy", tbl, count)
                continue
        except Exception:
            pass

        log.info("  Copying %s ...", tbl)
        sql(w, wh,
            f"CREATE OR REPLACE TABLE `{cat}`.`{schema}`.`{tbl}` "
            f"AS SELECT * FROM `{src_cat}`.`{src_schema}`.`{tbl}`",
            f"copy {tbl}")

    # -------------------------------------------------------------------------
    # 3. Inject workshop quality bugs into product_docs
    # -------------------------------------------------------------------------
    log.info("Step 3: Injecting workshop quality bugs into product_docs...")

    # Enable Change Data Feed (needed for delta-sync vector index)
    sql(w, wh,
        f"ALTER TABLE `{cat}`.`{schema}`.`product_docs` "
        f"SET TBLPROPERTIES (delta.enableChangeDataFeed = true)",
        "enable CDF on product_docs")

    # BUG 1: Discontinued products still described as "available"
    # Find up to 5 discontinued products and update their docs to sound active
    discontinued = sql_rows(w, wh, f"""
        SELECT p.product_id, p.product_name, pd.product_doc
        FROM `{cat}`.`{schema}`.`products` p
        JOIN `{cat}`.`{schema}`.`product_docs` pd ON p.product_id = pd.product_id
        WHERE p.discontinued = true
        LIMIT 5
    """)
    for row in discontinued:
        pid, pname, _ = row[0], row[1], row[2]
        log.info("  Bug 1: Marking discontinued product '%s' as available in docs", pname)
        sql(w, wh, f"""
            UPDATE `{cat}`.`{schema}`.`product_docs`
            SET product_doc = product_doc ||
                ' This product is currently in stock and available for immediate purchase. '
                'Order today for fast delivery.'
            WHERE product_id = '{pid}'
        """, f"bug1 - {pname}")

    # BUG 2: Wrong warranty info in one popular product doc
    # Find a product in Electronics / Headphones category
    warranty_target = sql_rows(w, wh, f"""
        SELECT product_id, product_name
        FROM `{cat}`.`{schema}`.`product_docs`
        WHERE LOWER(product_category) LIKE '%electronics%'
           OR LOWER(product_sub_category) LIKE '%headphone%'
           OR LOWER(product_sub_category) LIKE '%audio%'
        LIMIT 1
    """)
    if warranty_target:
        wpid, wpname = warranty_target[0][0], warranty_target[0][1]
        log.info("  Bug 2: Adding wrong warranty claim (3 years) to '%s'", wpname)
        sql(w, wh, f"""
            UPDATE `{cat}`.`{schema}`.`product_docs`
            SET product_doc = product_doc ||
                ' All products in this category include a comprehensive 3-year manufacturer warranty '
                'covering parts and labor.'
            WHERE product_id = '{wpid}'
        """, f"bug2 - {wpname}")

    # BUG 3: Aggressive/pushy tone in 3-5 product docs
    # Find products in a premium sub-category
    pushy_targets = sql_rows(w, wh, f"""
        SELECT product_id, product_name
        FROM `{cat}`.`{schema}`.`product_docs`
        WHERE LOWER(product_sub_category) LIKE '%laptop%'
           OR LOWER(product_sub_category) LIKE '%computer%'
           OR LOWER(product_sub_category) LIKE '%premium%'
        LIMIT 4
    """)
    for row in pushy_targets:
        ppid, ppname = row[0], row[1]
        log.info("  Bug 3: Adding pushy sales language to '%s'", ppname)
        sql(w, wh, f"""
            UPDATE `{cat}`.`{schema}`.`product_docs`
            SET product_doc = product_doc ||
                ' DO NOT MISS OUT! This is our BEST SELLER and inventory is extremely limited. '
                'Customers who hesitate lose out. Buy NOW before prices increase. '
                'This deal will not last — act immediately!'
            WHERE product_id = '{ppid}'
        """, f"bug3 - {ppname}")

    # BUG 4: Vague return policy that leads to policy overreach
    # The policies table has columns: policy, policy_details, last_updated
    policy_rows = sql_rows(w, wh, f"""
        SELECT policy
        FROM `{cat}`.`{schema}`.`policies`
        WHERE LOWER(policy) LIKE '%return%'
           OR LOWER(policy) LIKE '%refund%'
           OR LOWER(policy) LIKE '%exchange%'
        LIMIT 1
    """)
    if policy_rows:
        log.info("  Bug 4: Policies table found — adding ambiguous 'extended' policy...")
        sql(w, wh, f"""
            INSERT INTO `{cat}`.`{schema}`.`policies`
            (policy, policy_details, last_updated)
            VALUES (
                'Customer Satisfaction Policy (Extended)',
                'We value customer satisfaction above all else. In situations where a customer '
                'is unhappy with their purchase, our team is empowered to make it right. '
                'Exceptions can be made for loyal customers and in cases of genuine hardship. '
                'Customer service representatives should use their best judgment to ensure '
                'the customer leaves satisfied, even if a return is outside the standard window.',
                current_date()
            )
        """, "bug4 - vague return policy")
    else:
        log.info("  Bug 4: No return policy found — creating policies table with vague policy...")
        sql(w, wh, f"""
            CREATE TABLE IF NOT EXISTS `{cat}`.`{schema}`.`policies` (
                policy STRING,
                policy_details STRING,
                last_updated DATE
            )
        """, "create policies table")
        sql(w, wh, f"""
            INSERT INTO `{cat}`.`{schema}`.`policies` VALUES
            ('Standard Return Policy',
             'Products may be returned within 30 days of purchase in original condition with receipt.',
             current_date()),
            ('Warranty Policy',
             'All products carry a 1-year limited manufacturer warranty against defects.',
             current_date()),
            ('Customer Satisfaction Policy (Extended)',
             'We value customer satisfaction above all else. In situations where a customer '
             'is unhappy with their purchase, our team is empowered to make it right. '
             'Exceptions can be made for loyal customers and in cases of genuine hardship. '
             'Customer service representatives should use their best judgment to ensure '
             'the customer leaves satisfied, even if a return is outside the standard window.',
             current_date())
        """, "insert vague policy")

    log.info("  Quality bugs injected successfully.")

    # -------------------------------------------------------------------------
    # 4. Vector Search endpoint + index
    # -------------------------------------------------------------------------
    log.info("Step 4: Setting up Vector Search...")

    # Check if endpoint exists
    try:
        ep = w.vector_search_endpoints.get_endpoint(vs_endpoint)
        log.info("  VS endpoint '%s' found (state: %s)", vs_endpoint, ep.endpoint_status.state if ep.endpoint_status else "unknown")
    except Exception:
        log.info("  Creating VS endpoint '%s'...", vs_endpoint)
        w.vector_search_endpoints.create_endpoint_and_wait(
            name=vs_endpoint,
            endpoint_type=EndpointType.STANDARD,
            timeout=datetime.timedelta(minutes=30),
        )
        log.info("  VS endpoint created.")

    # Create delta-sync index on product_docs
    index_name = f"{cat}.{schema}.product_docs_vs"
    source_table = f"{cat}.{schema}.product_docs"
    index_exists = False
    try:
        idx = w.vector_search_indexes.get_index(index_name)
        # Index exists — check status via .ready attribute (SDK quirk)
        is_ready = getattr(idx.status, "ready", False) if idx.status else False
        log.info("  VS index '%s' exists (ready=%s, rows=%s)", index_name,
                 is_ready, getattr(idx.status, "indexed_row_count", "?"))
        index_exists = True
    except Exception as e:
        err_str = str(e).lower()
        if "does not exist" in err_str or "resourcedoesnotexist" in type(e).__name__.lower():
            log.info("  VS index not found — will create it.")
        elif "detailed_state" in str(e):
            # SDK attribute mismatch — index exists but status object differs
            log.info("  VS index appears to exist (SDK attribute mismatch) — skipping create.")
            index_exists = True
        else:
            log.warning("  Unexpected error checking VS index: %s", e)

    if not index_exists:
        log.info("  Creating delta-sync VS index '%s'...", index_name)
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
        # Wait for index to be ready (up to 20 min)
        log.info("  Waiting for VS index to become ready (this can take ~10 minutes)...")
        for _ in range(40):
            time.sleep(30)
            try:
                idx = w.vector_search_indexes.get_index(index_name)
                # SDK returns status.ready (bool) or status.message
                if idx.status and getattr(idx.status, "ready", False):
                    log.info("    Index is ready! indexed_row_count=%s",
                             getattr(idx.status, "indexed_row_count", "?"))
                    break
                msg = getattr(idx.status, "message", "no message") if idx.status else "no status"
                log.info("    Index status: %s", msg)
            except Exception as e:
                log.warning("    Could not check index state: %s", e)
        log.info("  VS index ready.")

    # -------------------------------------------------------------------------
    # 5. Create UC Functions
    # -------------------------------------------------------------------------
    log.info("Step 5: Creating UC Functions...")

    # product_lookup — calls the vector search index
    # Note: vector_search() requires num_results to be a constant literal
    # The result column is search_score (not score)
    sql(w, wh, f"""
        CREATE OR REPLACE FUNCTION `{cat}`.`{schema}`.`product_lookup`(
            query STRING COMMENT 'Natural language search query about a product'
        )
        RETURNS TABLE (
            product_id STRING,
            product_name STRING,
            product_category STRING,
            product_doc STRING,
            search_score DOUBLE
        )
        COMMENT 'Search TechMart product documentation using semantic search'
        RETURN
            SELECT
                product_id,
                product_name,
                product_category,
                product_doc,
                search_score
            FROM vector_search(
                index => '{index_name}',
                query => query,
                num_results => 3
            )
    """, "create product_lookup function")

    # get_product_details — direct lookup by name
    sql(w, wh, f"""
        CREATE OR REPLACE FUNCTION `{cat}`.`{schema}`.`get_product_details`(
            product_name_query STRING COMMENT 'Product name or partial name to look up'
        )
        RETURNS TABLE (
            product_id STRING,
            product_name STRING,
            product_category STRING,
            product_sub_category STRING,
            unit_price DECIMAL(10,2),
            units_in_stock INT,
            discontinued BOOLEAN,
            last_restocked_at TIMESTAMP
        )
        COMMENT 'Get product inventory details by name'
        RETURN
            SELECT
                product_id,
                product_name,
                product_category,
                product_sub_category,
                unit_price,
                units_in_stock,
                discontinued,
                last_restocked_at
            FROM `{cat}`.`{schema}`.`products`
            WHERE LOWER(product_name) LIKE LOWER(CONCAT('%', product_name_query, '%'))
            LIMIT 5
    """, "create get_product_details function")

    # get_order_status — join orders + customers
    sql(w, wh, f"""
        CREATE OR REPLACE FUNCTION `{cat}`.`{schema}`.`get_order_status`(
            order_id_param STRING COMMENT 'The order ID to look up'
        )
        RETURNS TABLE (
            order_id STRING,
            customer_name STRING,
            order_date TIMESTAMP,
            shipped_date TIMESTAMP,
            status STRING,
            ship_via STRING
        )
        COMMENT 'Get order status and shipping information by order ID'
        RETURN
            SELECT
                o.order_id,
                c.contact_name as customer_name,
                o.order_date,
                o.shipped_date,
                o.status,
                o.ship_via
            FROM `{cat}`.`{schema}`.`orders` o
            LEFT JOIN `{cat}`.`{schema}`.`customers` c ON o.customer_id = c.customer_id
            WHERE o.order_id = order_id_param
    """, "create get_order_status function")

    # get_return_policy — returns policy table content
    sql(w, wh, f"""
        CREATE OR REPLACE FUNCTION `{cat}`.`{schema}`.`get_return_policy`()
        RETURNS TABLE (policy STRING, policy_details STRING)
        COMMENT 'Get TechMart return and warranty policy information'
        RETURN
            SELECT policy, policy_details
            FROM `{cat}`.`{schema}`.`policies`
            ORDER BY policy
    """, "create get_return_policy function")

    log.info("  UC Functions created.")

    # -------------------------------------------------------------------------
    # 6. Grant permissions
    # -------------------------------------------------------------------------
    log.info("Step 6: Granting permissions to workspace users...")
    grant_stmts = [
        f"GRANT USE CATALOG ON CATALOG `{cat}` TO `account users`",
        f"GRANT USE SCHEMA ON SCHEMA `{cat}`.`{schema}` TO `account users`",
        f"GRANT SELECT ON SCHEMA `{cat}`.`{schema}` TO `account users`",
        f"GRANT CREATE TABLE ON SCHEMA `{cat}`.`{schema}` TO `account users`",
        f"GRANT CREATE FUNCTION ON SCHEMA `{cat}`.`{schema}` TO `account users`",
    ]
    for stmt in grant_stmts:
        try:
            sql(w, wh, stmt)
        except Exception as e:
            log.warning("  Grant skipped (non-fatal): %s — %s", stmt[:60], e)
    log.info("  Permissions granted.")

    # -------------------------------------------------------------------------
    # 7. Provision shared Lakebase instance (for agent conversation memory)
    # -------------------------------------------------------------------------
    log.info("Step 7: Provisioning shared Lakebase instance for agent memory...")
    lakebase_name = args.lakebase_name

    lakebase_instance = None
    try:
        existing = list(w.database.list_database_instances())
        for inst in existing:
            if inst.name == lakebase_name:
                lakebase_instance = inst
                log.info("  Lakebase instance '%s' already exists (state: %s)",
                         lakebase_name, inst.state)
                break
    except Exception as e:
        log.warning("  Could not list Lakebase instances: %s", e)

    if lakebase_instance is None:
        log.info("  Creating Lakebase instance '%s' (CU_1) — this takes ~5 minutes...", lakebase_name)
        try:
            waiter = w.database.create_database_instance(
                DatabaseInstance(name=lakebase_name, capacity="CU_1")
            )
            lakebase_instance = waiter.result(timeout=datetime.timedelta(minutes=15))
            log.info("  Lakebase instance '%s' is ready.", lakebase_name)
        except Exception as e:
            log.error("  Failed to create Lakebase instance: %s", e)
            log.error("  You can create it manually in the Databricks UI under Compute > Lakebase")
            log.error("  Then re-run this script or set --lakebase-name to an existing instance.")
            lakebase_instance = None

    # -------------------------------------------------------------------------
    # Done
    # -------------------------------------------------------------------------
    log.info("")
    log.info("=" * 60)
    log.info("WORKSPACE SETUP COMPLETE")
    log.info("=" * 60)
    log.info("  Catalog:        %s", cat)
    log.info("  Schema:         %s", schema)
    log.info("  VS Endpoint:    %s", vs_endpoint)
    log.info("  VS Index:       %s", index_name)
    log.info("  UC Functions:   product_lookup, get_product_details,")
    log.info("                  get_order_status, get_return_policy")
    log.info("  Lakebase:       %s  (shared by all participants)", lakebase_name)
    log.info("")
    log.info("Give participants these values for their databricks.yml:")
    log.info("  WORKSHOP_CATALOG=%s", cat)
    log.info("  WORKSHOP_SCHEMA=%s", schema)
    log.info("  LAKEBASE_INSTANCE_NAME=%s", lakebase_name)
    log.info("")
    log.info("Next steps:")
    log.info("  1. Share the GitHub repo link with participants")
    log.info("  2. Participants run: databricks bundle deploy && databricks bundle run")
    log.info("  3. Verify preflight checklist in enablement/instructor_guide.md")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import datetime
    parser = argparse.ArgumentParser(
        description="Set up the workshop Databricks workspace"
    )
    parser.add_argument("--profile", default="ai-specialist",
                        help="Databricks CLI profile to use")
    parser.add_argument("--warehouse-id", default="f45852ca675f5dcb",
                        help="SQL warehouse ID for DDL/DML")
    parser.add_argument("--workshop-catalog", default="workshop_catalog",
                        help="Target catalog to create for the workshop")
    parser.add_argument("--workshop-schema", default="customer_support_workshop",
                        help="Target schema to create for the workshop")
    parser.add_argument("--source-catalog", default="robert_mosley",
                        help="Source catalog with the original data")
    parser.add_argument("--source-schema", default="customer_support",
                        help="Source schema with the original data")
    parser.add_argument("--vs-endpoint", default="anthony_ivan_test_vs_endpoint",
                        help="Vector search endpoint name")
    parser.add_argument("--lakebase-name", default="cs-agent-workshop-memory",
                        help="Name for the shared Lakebase instance (created if it doesn't exist)")
    args = parser.parse_args()
    setup(args)
