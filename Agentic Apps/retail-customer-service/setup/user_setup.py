"""
User Setup Script
=================
Run ONCE per attendee. Participants trigger this themselves via Claude Code during self-onboarding.

What this script does:
  1. Creates a per-user schema under the workshop catalog
  2. Reads CLAUDE.md and substitutes template variables with the user's values
  3. Uploads modified CLAUDE.md to the user's Databricks workspace files
  4. Creates starter app.yaml in the user's workspace (includes LAKEBASE_SCHEMA)

Usage:
    python3 "Agentic Apps/retail-customer-service/setup/user_setup.py" \\
        --workspace-url https://dbc-9dcd6158-e299.cloud.databricks.com \\
        --user-email attendee@company.com \\
        --token dapi... \\
        --catalog cs_agent_workshop \\
        [--lakebase-name cs-agent-workshop-memory] \\
        [--lakebase-schema cs_agent_workshop] \\
        [--dry-run]

Schema derivation rule:
  jsmith@company.com       -> UC schema: jsmith,      Lakebase schema: cs_agent_workshop_jsmith
  first.last@company.com   -> UC schema: first_last,  Lakebase schema: cs_agent_workshop_first_last

Each user gets an isolated Postgres schema in Lakebase so checkpoint tables
don't collide across participants or workshops.
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SKILL_TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "CLAUDE.md")
PROJECT_PATH_TEMPLATE = "/Workspace/Users/{email}/projects/cs-agent-workshop"


def derive_schema_name(email: str) -> str:
    """Derive a valid schema name from an email address."""
    local = email.split("@")[0].lower()
    # Replace non-alphanumeric with underscores, remove consecutive underscores
    clean = re.sub(r"[^a-z0-9]", "_", local)
    clean = re.sub(r"_+", "_", clean).strip("_")
    # Prefix to avoid starting with a digit
    if clean and clean[0].isdigit():
        clean = "u_" + clean
    return clean or "workshop_user"


def workspace_api(workspace_url: str, token: str, method: str, path: str,
                  body: dict | None = None) -> dict:
    """Make a Databricks Workspace API call."""
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


def setup_user(args):
    workspace_url = args.workspace_url.rstrip("/")
    email = args.user_email
    token = args.token
    catalog = args.catalog
    schema = args.schema or derive_schema_name(email)
    username = derive_schema_name(email)  # same derivation as schema

    # Per-user Postgres schema in Lakebase:
    # <lakebase_schema_prefix>_<username>
    # e.g. cs_agent_workshop_jsmith
    # This namespaces each user's checkpoint tables so they're isolated and droppable.
    lakebase_schema_prefix = args.lakebase_schema or catalog
    lakebase_pg_schema = f"{lakebase_schema_prefix}_{username}"

    log.info("Setting up user: %s", email)
    log.info("  Catalog:         %s", catalog)
    log.info("  UC Schema:       %s", schema)
    log.info("  Lakebase schema: %s (Postgres schema for memory isolation)", lakebase_pg_schema)

    # -------------------------------------------------------------------------
    # Read and fill CLAUDE.md template
    # -------------------------------------------------------------------------
    if not os.path.exists(SKILL_TEMPLATE):
        log.error("CLAUDE.md template not found at %s", SKILL_TEMPLATE)
        sys.exit(1)

    with open(SKILL_TEMPLATE) as f:
        claude_md = f.read()

    # Substitute template variables
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
    # Build app.yaml for the user
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
        log.info("[DRY RUN] Would upload CLAUDE.md (%d chars) and app.yaml to workspace", len(claude_md))
        log.info("[DRY RUN] Target path: %s", PROJECT_PATH_TEMPLATE.format(email=email))
        return 0

    # -------------------------------------------------------------------------
    # Upload to workspace
    # -------------------------------------------------------------------------
    project_path = PROJECT_PATH_TEMPLATE.format(email=email)

    try:
        # Create directory
        workspace_api(workspace_url, token, "POST", "/api/2.0/workspace/mkdirs", {
            "path": project_path,
        })
        log.info("  Created workspace directory: %s", project_path)
    except RuntimeError as e:
        if "RESOURCE_ALREADY_EXISTS" in str(e) or "already exists" in str(e).lower():
            log.info("  Workspace directory already exists: %s", project_path)
        else:
            log.warning("  Could not create directory (may already exist): %s", e)

    # Upload CLAUDE.md
    claude_path = f"{project_path}/CLAUDE.md"
    upload_workspace_file(workspace_url, token, claude_path, claude_md)
    log.info("  Uploaded CLAUDE.md to %s", claude_path)

    # Upload app.yaml
    yaml_path = f"{project_path}/app.yaml"
    upload_workspace_file(workspace_url, token, yaml_path, app_yaml)
    log.info("  Uploaded app.yaml to %s", yaml_path)

    log.info("User setup complete for %s", email)
    log.info("  UC schema:       %s.%s", catalog, schema)
    log.info("  Lakebase schema: %s", lakebase_pg_schema)
    log.info("  App name:        cs-agent-%s", username)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Set up a workshop user")
    parser.add_argument("--workspace-url", required=True,
                        help="Databricks workspace URL")
    parser.add_argument("--user-email", required=True,
                        help="User email address")
    parser.add_argument("--token", required=True,
                        help="Databricks PAT for this user")
    parser.add_argument("--catalog", default="cs_agent_workshop",
                        help="Workshop catalog name")
    parser.add_argument("--schema", default=None,
                        help="Workshop schema name (derived from email if not set)")
    parser.add_argument("--lakebase-name", default="cs-agent-workshop-memory",
                        help="Lakebase instance name for conversation memory")
    parser.add_argument("--lakebase-schema", default=None,
                        help="Lakebase schema prefix (defaults to catalog name). "
                             "Per-user schema will be <prefix>_<username>.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without making changes")
    args = parser.parse_args()
    sys.exit(setup_user(args))
