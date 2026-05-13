# Databricks Agentic App Workshop

Hands-on labs for building, evaluating, and hardening agentic applications
on the Databricks AI platform.

Each scenario takes participants from raw data in Unity Catalog to a deployed,
production-ready AI application — with full quality measurement along the way.

---

## Repository Structure

```
databricks-agentic-app-workshop/
├── CLAUDE.md                          <- AI assistant router (start here)
├── skills/
│   ├── agentic-app-best-practices.md  <- Universal patterns reference
│   └── mlflow-agent-evaluation-lifecycle.md  <- MLflow eval & tracing patterns
└── Agentic Apps/
    └── retail-customer-service/       <- Scenario 1
        ├── CLAUDE.md                  <- AI lab partner guide (no spoilers)
        ├── lab.yml                    <- Machine-readable lab metadata
        ├── setup/
        │   ├── workspace_setup.py     <- Instructor: run once per cohort
        │   └── user_setup.py          <- Participant: run once at self-onboarding
        ├── reference/
        │   ├── agent/                 <- Complete working implementation
        │   │   ├── agent_server/      <- LangGraph agent + server code
        │   │   ├── pyproject.toml
        │   │   ├── databricks.yml
        │   │   └── app.yaml
        │   └── scripts/
        │       ├── generate_traces.py <- Generate 25 scripted traces
        │       └── create_judges.py   <- MLflow Guidelines scorer definitions
        └── docs/
            └── instructor_guide.md    <- Facilitator notes and timing
```

---

## Available Scenarios

### 1. Retail Customer Service Agent

Build a LangGraph customer support agent for TechMart, a fictional technology
retailer. The agent answers product questions, checks order status, and handles
return requests using Unity Catalog data.

What participants learn:
- Connecting Unity Catalog tables to an agent via UC Functions and MCP
- Deploying a LangGraph agent as a Databricks App using Asset Bundles
- Generating and browsing MLflow traces
- Building an eval dataset from real agent conversations
- Writing LLM judges (Guidelines scorers) for quality dimensions
- Measuring and proving agent improvement

Technologies: LangGraph, UC Functions, DatabricksMCPServer, Databricks Apps,
Databricks Asset Bundles, MLflow tracing, mlflow.genai.evaluate, Guidelines
scorers, Lakebase (AsyncCheckpointSaver), Vector Search.

Duration: ~100 minutes
Difficulty: intermediate

---

## For Instructors

Before the workshop, run workspace_setup.py once to create the shared
Unity Catalog objects, Vector Search index, and MLflow experiment.

user_setup.py is now participant-triggered: each attendee runs it themselves
via Claude Code during self-onboarding. It generates their personal CLAUDE.md
with live workspace values injected (catalog, schema, Lakebase instance, etc.).

See `Agentic Apps/retail-customer-service/docs/instructor_guide.md` for
full facilitation notes, timing guidance, and debrief talking points.

Quick start:

```bash
# 1. Install dependencies (one-time)
pip install -r "Agentic Apps/retail-customer-service/setup/requirements.txt"
# or with uv:
uv pip install -r "Agentic Apps/retail-customer-service/setup/requirements.txt"

# 2. Set up the workspace (once per cohort — brings all data from this repo)
#    No external data dependencies. Discovers your SQL warehouse automatically.
#    Allow 30-45 minutes on a cold workspace (VS endpoint + index sync).
#    On a warm workspace (endpoint already exists): ~10 minutes.
python3 "Agentic Apps/retail-customer-service/setup/workspace_setup.py"

# Optional overrides (see --help for all options):
python3 "Agentic Apps/retail-customer-service/setup/workspace_setup.py" \
  --profile DEFAULT \
  --workshop-catalog cs_agent_workshop

# 3. Onboard a participant
python3 "Agentic Apps/retail-customer-service/setup/user_setup.py" \
  --workspace-url https://adb-xxxx.azuredatabricks.net \
  --user-email alice@company.com \
  --token my_token \
  --catalog cs_agent_workshop
```

---

## For Participants

Open this repo in an environment with Claude Code (or any Claude-backed AI
assistant) and say: "I'm a participant working on the retail customer service
lab." The AI assistant will load the scenario guide and walk you through it
step by step.

If you don't have an AI assistant, the lab guide is at:
`Agentic Apps/retail-customer-service/CLAUDE.md`

---

## AI Assistant Integration

This repo contains CLAUDE.md files that act as context for Claude Code and
similar AI coding assistants:

- Root CLAUDE.md: routes between admin and participant workflows
- Scenario CLAUDE.md: intent-based lab guide (hints, not answers)
- skills/agentic-app-best-practices.md: universal architecture patterns

The scenario CLAUDE.md is designed to guide without giving away answers.
Reference implementations in reference/ are the "spoilers" — participants
should try to build things themselves before consulting them.

---

## Contributing a New Scenario

1. Create `Agentic Apps/{scenario-name}/` following the retail-customer-service
   structure.
2. Write a `CLAUDE.md` using the intent-based guide format (see existing one
   as a template).
3. Write a `lab.yml` declaring steps, technologies, and quality issues planted.
4. Add setup scripts under `setup/`.
5. Put the reference implementation under `reference/`.
6. Update this README's scenario list.
