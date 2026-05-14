"""
User Setup Script
=================
Run ONCE per attendee. Participants trigger this themselves via Claude Code during self-onboarding.

What this script does:
  1. Reads setup-state.json (written by workspace_setup.py) to get catalog + Lakebase defaults
  2. Creates the per-user UC schema in Unity Catalog via the SQL Statements API
  3. Reads the scenario CLAUDE.md template and substitutes the user's values
  4. Uploads the filled CLAUDE.md to the user's Databricks workspace files
  5. Uploads a starter app.yaml (pre-wired with catalog, schema, Lakebase) to the workspace

Schema derivation rule:
  jsmith@company.com       -> UC schema: jsmith,      Lakebase schema: cs_agent_workshop_jsmith
  first.last@company.com   -> UC schema: first_last,  Lakebase schema: cs_agent_workshop_first_last
  (strip domain, replace dots/hyphens with underscores, deduplicate underscores)

Usage (defaults read from setup/setup-state.json written by workspace_setup.py):
    python3 "Agentic Apps/retail-customer-service/setup/user_setup.py" \\
        --workspace-url https://dbc-9dcd6158-e299.cloud.databricks.com \\
        --user-email attendee@company.com \\
        --token dapi... \\
        [--catalog cs_agent_workshop] \\
        [--lakebase-name cs-agent-workshop-memory] \\
        [--lakebase-schema cs_agent_workshop] \\
        [--dry-run]

If setup-state.json exists, --catalog and --lakebase-name are filled in automatically.
"""

import argparse
import logging
import os
import sys
import urllib.request
import urllib.error
import json
import base64
import re
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_TEMPLATE = os.path.join(SCRIPT_DIR, "..", "CLAUDE.md")
STATE_FILE = os.path.join(SCRIPT_DIR, "setup-state.json")
PROJECT_PATH_TEMPLATE = "/Workspace/Users/{email}/projects/cs-agent-workshop"


# ---------------------------------------------------------------------------
# Setup-state helpers
# ---------------------------------------------------------------------------

def load_setup_state() -> dict:
    """Load setup-state.json written by workspace_setup.py, if present."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            log.info("Loaded setup state from %s", STATE_FILE)
            return state
        except Exception as e:
            log.warning("Could not read %s: %s", STATE_FILE, e)
    return {}


# ---------------------------------------------------------------------------
# Schema derivation
# ---------------------------------------------------------------------------

def derive_schema_name(email: str) -> str:
    """Derive a valid UC/Postgres identifier from an email local part.

    jsmith@company.com       -> jsmith
    first.last@company.com   -> first_last
    robert.mosley@db.com     -> robert_mosley
    """
    local = email.split("@")[0].lower()
    clean = re.sub(r"[^a-z0-9]", "_", local)
    clean = re.sub(r"_+", "_", clean).strip("_")
    if clean and clean[0].isdigit():
        clean = "u_" + clean
    return clean or "workshop_user"


# ---------------------------------------------------------------------------
# API helpers (stdlib only — no databricks-sdk dependency)
# ---------------------------------------------------------------------------

def workspace_api(workspace_url: str, token: str, method: str, path: str,
                  body: dict | None = None) -> dict:
    """Make a Databricks Workspace REST API call."""
    url = f"{workspace_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        raise RuntimeError(f"API {method} {path} failed {e.code}: {body_text}") from e


def upload_workspace_file(workspace_url: str, token: str, workspace_path: str,
                          content: str, overwrite: bool = True) -> None:
    """Upload a text file to the Databricks workspace."""
    encoded = base64.b64encode(content.encode()).decode()
    workspace_api(workspace_url, token, "POST", "/api/2.0/workspace/import", {
        "path": workspace_path,
        "content": encoded,
        "format": "AUTO",
        "language": "PYTHON",
        "overwrite": overwrite,
    })


def create_uc_schema(workspace_url: str, token: str,
                     catalog: str, schema: str,
                     warehouse_id: str | None) -> None:
    """Create the per-user UC schema using the SQL Statements API.

    workspace_setup.py grants CREATE SCHEMA ON CATALOG to all workspace users,
    so the participant's own token has the necessary privilege.

    If no warehouse_id is provided we discover one via the warehouses list API.
    """
    wh_id = warehouse_id or _discover_warehouse(workspace_url, token)
    if not wh_id:
        log.warning(
            "No SQL warehouse found — skipping UC schema creation. "
            "Participant will need to create %s.%s manually.", catalog, schema
        )
        return

    stmt = f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}"
    log.info("  Creating UC schema: %s.%s", catalog, schema)

    resp = workspace_api(workspace_url, token, "POST",
                         "/api/2.0/sql/statements", {
                             "warehouse_id": wh_id,
                             "statement": stmt,
                             "wait_timeout": "30s",
                         })

    state = resp.get("status", {}).get("state", "UNKNOWN")
    if state in ("SUCCEEDED",):
        log.info("  UC schema %s.%s ready", catalog, schema)
    elif state in ("PENDING", "RUNNING"):
        # Poll for up to 60s
        stmt_id = resp.get("statement_id")
        for _ in range(12):
            time.sleep(5)
            poll = workspace_api(workspace_url, token, "GET",
                                 f"/api/2.0/sql/statements/{stmt_id}")
            s = poll.get("status", {}).get("state", "UNKNOWN")
            if s == "SUCCEEDED":
                log.info("  UC schema %s.%s ready", catalog, schema)
                return
            if s in ("FAILED", "CANCELED", "CLOSED"):
                err = poll.get("status", {}).get("error", {})
                raise RuntimeError(
                    f"CREATE SCHEMA failed (state={s}): {err.get('message', poll)}"
                )
        log.warning("  CREATE SCHEMA timed out — check UC manually")
    else:
        err = resp.get("status", {}).get("error", {})
        raise RuntimeError(
            f"CREATE SCHEMA failed (state={state}): {err.get('message', resp)}"
        )


def _discover_warehouse(workspace_url: str, token: str) -> str | None:
    """Return the ID of the best available SQL warehouse."""
    try:
        resp = workspace_api(workspace_url, token, "GET", "/api/2.0/sql/warehouses")
    except RuntimeError:
        return None
    warehouses = resp.get("warehouses", [])
    if not warehouses:
        return None
    # Prefer running serverless, then running, then any
    def rank(w):
        s = (w.get("state") or "").upper()
        t = (w.get("warehouse_type") or "").upper()
        return (
            0 if s == "RUNNING" and "SERVERLESS" in t else
            1 if s == "RUNNING" else
            2 if s in ("STARTING", "STOPPING") else 3,
            w.get("name", ""),
        )
    warehouses.sort(key=rank)
    return warehouses[0]["id"]


# ---------------------------------------------------------------------------
# Main setup
# ---------------------------------------------------------------------------

def setup_user(args):
    workspace_url = args.workspace_url.rstrip("/")
    email = args.user_email
    token = args.token
    catalog = args.catalog
    schema = args.schema or derive_schema_name(email)
    username = derive_schema_name(email)

    # Per-user Postgres schema in Lakebase: <prefix>_<username>
    # e.g. cs_agent_workshop_jsmith — isolated and droppable per user
    lakebase_schema_prefix = args.lakebase_schema or catalog
    lakebase_pg_schema = f"{lakebase_schema_prefix}_{username}"

    log.info("Setting up user: %s", email)
    log.info("  Catalog:         %s", catalog)
    log.info("  UC Schema:       %s.%s", catalog, schema)
    log.info("  Lakebase name:   %s", args.lakebase_name)
    log.info("  Lakebase schema: %s", lakebase_pg_schema)

    # -------------------------------------------------------------------------
    # Step 1: Create the UC schema
    # -------------------------------------------------------------------------
    if not args.dry_run:
        try:
            create_uc_schema(workspace_url, token, catalog, schema,
                             warehouse_id=args.warehouse_id)
        except RuntimeError as e:
            log.error("Failed to create UC schema %s.%s: %s", catalog, schema, e)
            log.error("Ensure workspace_setup.py has run and granted CREATE SCHEMA.")
            sys.exit(1)
    else:
        log.info("[DRY RUN] Would run: CREATE SCHEMA IF NOT EXISTS %s.%s", catalog, schema)

    # -------------------------------------------------------------------------
    # Step 2: Read and fill CLAUDE.md template
    # -------------------------------------------------------------------------
    if not os.path.exists(SKILL_TEMPLATE):
        log.error("CLAUDE.md template not found at %s", SKILL_TEMPLATE)
        sys.exit(1)

    with open(SKILL_TEMPLATE) as f:
        claude_md = f.read()

    replacements = {
        "{{CATALOG}}": catalog,
        "{{SCHEMA}}": schema,
        "{{USER}}": email,
        "{{USERNAME}}": username,
        "{{WORKSPACE_URL}}": workspace_url,
        "{{LAKEBASE_INSTANCE}}": args.lakebase_name,
        "{{LAKEBASE_SCHEMA}}": lakebase_pg_schema,
    }
    for placeholder, value in replacements.items():
        claude_md = claude_md.replace(placeholder, value)

    # -------------------------------------------------------------------------
    # Step 3: Build app.yaml
    # -------------------------------------------------------------------------
    app_yaml = f"""command: ["uv", "run", "start-server"]

env:
  - name: DATABRICKS_HOST
    valueFrom: workspace_url
  - name: WORKSHOP_CATALOG
    value: "{catalog}"
  - name: WORKSHOP_SCHEMA
    value: "{schema}"
  - name: LLM_ENDPOINT
    value: "databricks-claude-sonnet-4-6"
  - name: MLFLOW_EXPERIMENT
    value: "/Users/{email}/cs-agent-workshop"
  - name: LAKEBASE_SCHEMA
    value: "{lakebase_pg_schema}"
"""

    if args.dry_run:
        log.info("[DRY RUN] Would upload CLAUDE.md (%d chars) and app.yaml", len(claude_md))
        log.info("[DRY RUN] Target: %s", PROJECT_PATH_TEMPLATE.format(email=email))
        return 0

    # -------------------------------------------------------------------------
    # Step 4: Upload to workspace
    # -------------------------------------------------------------------------
    project_path = PROJECT_PATH_TEMPLATE.format(email=email)

    try:
        workspace_api(workspace_url, token, "POST", "/api/2.0/workspace/mkdirs", {
            "path": project_path,
        })
        log.info("  Created workspace directory: %s", project_path)
    except RuntimeError as e:
        if "RESOURCE_ALREADY_EXISTS" in str(e) or "already exists" in str(e).lower():
            log.info("  Workspace directory already exists: %s", project_path)
        else:
            log.warning("  Could not create directory: %s", e)

    claude_path = f"{project_path}/CLAUDE.md"
    upload_workspace_file(workspace_url, token, claude_path, claude_md)
    log.info("  Uploaded CLAUDE.md -> %s", claude_path)

    yaml_path = f"{project_path}/app.yaml"
    upload_workspace_file(workspace_url, token, yaml_path, app_yaml)
    log.info("  Uploaded app.yaml -> %s", yaml_path)

    log.info("")
    log.info("User setup complete for %s", email)
    log.info("  UC schema:       %s.%s", catalog, schema)
    log.info("  Lakebase schema: %s", lakebase_pg_schema)
    log.info("  App name:        cs-agent-%s", username)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Load setup-state.json for defaults (written by workspace_setup.py)
    state = load_setup_state()
    default_catalog = state.get("workshop_catalog", "cs_agent_workshop")
    default_lakebase = state.get("lakebase_instance_name", "cs-agent-workshop-memory")

    if state:
        log.info("Using defaults from setup-state.json: catalog=%s, lakebase=%s",
                 default_catalog, default_lakebase)
        if not default_lakebase:
            log.warning(
                "setup-state.json has no lakebase_instance_name. "
                "Pass --lakebase-name explicitly, or ask the instructor "
                "which Lakebase instance was provisioned for this workshop."
            )

    parser = argparse.ArgumentParser(
        description="Set up a workshop participant (creates UC schema + uploads workspace files)"
    )
    parser.add_argument("--workspace-url", required=True,
                        help="Databricks workspace URL")
    parser.add_argument("--user-email", required=True,
                        help="User email address")
    parser.add_argument("--token", required=True,
                        help="Databricks PAT for this user")
    parser.add_argument("--catalog", default=default_catalog,
                        help=f"Workshop catalog name (default from setup-state.json: {default_catalog})")
    parser.add_argument("--schema", default=None,
                        help="Per-user UC schema (derived from email if omitted)")
    parser.add_argument("--lakebase-name", default=default_lakebase or "cs-agent-workshop-memory",
                        help=f"Lakebase instance name (default from setup-state.json: {default_lakebase or 'not set'})")
    parser.add_argument("--lakebase-schema", default=None,
                        help="Lakebase schema prefix (defaults to catalog). "
                             "Per-user Postgres schema = <prefix>_<username>.")
    parser.add_argument("--warehouse-id", default=None,
                        help="SQL warehouse ID for CREATE SCHEMA (auto-discovered if omitted)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without making changes")
    args = parser.parse_args()

    # Warn loudly if Lakebase name is still the fallback and wasn't in state
    if not state.get("lakebase_instance_name") and args.lakebase_name == "cs-agent-workshop-memory":
        log.warning(
            "Lakebase instance name not found in setup-state.json and no --lakebase-name given. "
            "Using fallback 'cs-agent-workshop-memory' — verify this instance exists, "
            "or pass --lakebase-name <instance> explicitly."
        )

    sys.exit(setup_user(args))
