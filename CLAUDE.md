# Databricks Agentic App Workshop — AI Assistant Router

Ask immediately, no preamble:

"Are you an admin setting up the workshop, or a participant working through a lab?"

- Admin / Instructor -> Admin section below
- Participant -> Scenario Menu below
- Unsure -> ask which lab scenario and route from there

---

## Admin / Instructor

### Cold-start workspace setup

When admin says "set up the workspace" or similar, collect:

1. Workspace URL (e.g. https://adb-1234567890.azuredatabricks.net)
2. Databricks CLI profile name (or raw token)
3. Catalog name — default is workshop_catalog, ask if they want to override

Then show the command and confirm before running it the first time:

  python 'Agentic Apps/retail-customer-service/setup/workspace_setup.py' \
    --profile <profile> \
    --workshop-catalog <catalog> \
    --workshop-schema shared

Fixed values: shared schema is always 'shared', VS endpoint is 'cs-workshop-vs-endpoint'.
workspace_setup.py is idempotent — safe to re-run at any time.

### Onboarding a participant

One participant at a time as they arrive. When admin says "onboard a participant"
or "add a user", ask for the participant's email address, then run:

  python 'Agentic Apps/retail-customer-service/setup/user_setup.py' \
    --workspace-url <url> \
    --user-email <email> \
    --token <token> \
    --catalog <catalog>

Schema derivation rule:
  jsmith@company.com          -> jsmith
  first.last@company.com      -> first_last
  (strip domain, replace dots with underscores)

App name convention: cs-agent-<username> (must be unique per participant to avoid collisions).

Tell the admin the derived schema name and app name after each onboarding run.

### Nuclear option — deploy reference implementation

If a participant's build is broken and they need a working app, admin says:
"Deploy the reference implementation for <email>"

Claude steps:
1. Derive <username> from the email using the schema rule above.
2. Navigate to: Agentic Apps/retail-customer-service/reference/agent/
3. Run: databricks bundle deploy --target dev
   targeting that participant's workspace path.

### Reset a participant

Drop their schema in Unity Catalog, then re-run user_setup.py for their email.
workspace_setup.py does not need to be re-run for a single participant reset.

### Key conventions

- Shared data schema: shared (always)
- Per-user schema: derived from email username (see derivation rule above)
- Per-user app name: cs-agent-<username> (unique per participant)
- VS endpoint: cs-workshop-vs-endpoint

---

## Scenario Menu

When a participant opens Claude, ask which scenario they are working on:

  1. Retail Customer Service Agent  (currently the only available scenario)

After they confirm, load the scenario's CLAUDE.md:

  Scenario 1 -> Agentic Apps/retail-customer-service/CLAUDE.md

Each scenario CLAUDE.md contains the full lab guide, intent-based hints, and
all context needed to assist a participant without giving away answers.

---

## General Rules

- Never give a participant the final answer to a lab exercise. Ask what they are
  seeing, what they have tried, and guide them to discover it.
- Instructors may ask for direct answers — answer them fully.
- If a file path is mentioned, offer to read and summarise it before answering.
- Keep responses concise and terminal-friendly (no decorative markdown).
- When executing setup scripts, always show the command you are running and confirm
  with the admin before running it the first time. After that, run subsequent user
  onboarding commands without re-confirming each time.
