# From Prompt to Production: Hardening an AI Customer Support Agent

A 2-hour hands-on Databricks workshop where participants build, test, evaluate,
and harden an AI customer support agent using Claude Code in CoDA.

---

## What You'll Build

A fully deployed AI customer support agent for a fictional tech retailer (TechMart)
that answers product questions, checks order status, and handles return requests.

More importantly, you'll discover that the agent has quality issues — and you'll
use MLflow's eval framework to measure them, fix them, and prove the improvement.

**Workshop flow:**
1. Explore the data (15 min)
2. Build and deploy the agent (25 min)
3. Chat with it and find quality issues (10 min)
4. Generate traces, label data, run LLM judges (30 min)
5. Fix the agent and verify improvement (20 min)

---

## What You'll Learn

- How to create UC Functions as agent tools
- How to deploy an agent as a Databricks App using LangGraph
- How MLflow tracing captures what your agent actually does
- How to build an eval dataset from real agent traces
- How to write LLM judges using MLflow Guidelines scorers
- How the evaluate-fix-evaluate loop works in production

---

## Prerequisites

- Access to a Databricks workspace with the workshop catalog pre-populated
- CoDA installed and connected to your workspace (see instructor)
- A Databricks PAT (personal access token)

---

## Pre-Work (Instructor Only)

Run these before the session:

### 1. Install dependencies

```bash
pip install databricks-sdk
```

### 2. Run workspace setup (once per workspace)

```bash
python orchestration/workspace_setup.py \
    --profile ai-specialist \
    --workshop-catalog workshop_catalog \
    --workshop-schema customer_support_workshop \
    --source-catalog robert_mosley \
    --source-schema customer_support

# This takes ~15 minutes (vector search index sync)
```

The setup script:
- Creates `workshop_catalog.customer_support_workshop` with all tables
- Injects quality bugs into product_docs (this is the workshop scenario)
- Creates or verifies the vector search index
- Creates the four UC Functions participants will use as tools
- Grants permissions to all workspace users

### 3. Run user setup for each attendee

```bash
python orchestration/user_setup.py \
    --workspace-url https://your-workspace.cloud.databricks.com \
    --user-email attendee@company.com \
    --token dapi... \
    --catalog workshop_catalog \
    --schema attendee_schema
```

Or run for all attendees:
```bash
while read email; do
    python orchestration/user_setup.py \
        --workspace-url https://your-workspace.cloud.databricks.com \
        --user-email "$email" \
        --token "$DATABRICKS_TOKEN" \
        --catalog workshop_catalog
done < attendees.txt
```

### 4. Pre-flight checklist

Before participants arrive:
- [ ] `workshop_catalog.customer_support_workshop` exists with all 7 tables
- [ ] `product_docs_vs` vector search index is ONLINE
- [ ] `product_lookup` UC Function returns results when tested
- [ ] At least one CoDA instance is running and accessible
- [ ] You have a fallback: a pre-deployed app URL to share if someone can't deploy
- [ ] MLflow experiment at `/Users/robert.mosley@databricks.com/cs-agent-workshop` is accessible

---

## Participant Quick Start

1. Open CoDA in your browser (instructor will give you the URL)
2. In the CoDA terminal, point to this workshop:
   ```
   cd ~/projects
   git clone https://github.com/YOUR_ORG/databricks-cs-agent-workshop.git
   cd databricks-cs-agent-workshop
   ```
3. Open a Claude Code session:
   ```
   claude
   ```
4. Say: "I want to start the workshop. Help me run Step 1."

Claude has the full workshop context in CLAUDE.md and will guide you step by step.

---

## Repository Structure

```
databricks-cs-agent-workshop/
├── CLAUDE.md                    # Workshop skill — Claude's lab guide
├── README.md                    # This file
├── agent/
│   ├── agent.py                 # Agent blueprint (LangGraph + FastAPI)
│   ├── app.yaml                 # Databricks Apps deployment config
│   └── requirements.txt         # Python dependencies
├── orchestration/
│   ├── workspace_setup.py       # Instructor: run once to prep workspace
│   └── user_setup.py            # Instructor: run per attendee
├── scripts/
│   ├── generate_traces.py       # Step 4: generate 25 scripted traces
│   └── create_judges.py         # Step 4: run eval with 3 judges
└── enablement/
    └── instructor_guide.md      # Full instructor guide with timing
```

---

## The Quality Issues (Instructor Reference)

The workspace setup script injects four intentional quality issues.
Participants discover these in Step 3 and fix them in Step 5.

| # | Issue | How it manifests | Judge that catches it |
|---|-------|------------------|----------------------|
| 1 | Discontinued products described as available | Agent recommends products that can't be purchased | factual_accuracy |
| 2 | Wrong warranty info (3 years vs 1 year standard) | Agent tells customers they have a 3-year warranty | factual_accuracy |
| 3 | Pushy sales language in product docs | Agent uses "ACT NOW", "DON'T MISS OUT" in responses | tone_quality |
| 4 | Vague return policy leads to over-promising | Agent approves returns outside the 30-day window | policy_compliance |

---

## Custom Path (Full Day)

For participants with their own data and use case:

1. Steps 1-2 use their own data instead of TechMart
2. Steps 3-5 follow the same evaluation lifecycle
3. The CLAUDE.md scaffold, judge templates, and trace scripts all work with any agent

The instructor can substitute `{{CATALOG}}` and `{{SCHEMA}}` with the customer's
actual catalog/schema when running `user_setup.py`.

---

## Related Resources

- Reference workshop: https://github.com/AnanyaDBJ/databricks-ai-workshops/tree/main/advanced
- CoDA (coding environment): https://github.com/datasciencemonkey/coding-agents-databricks-apps
- MLflow GenAI evaluation docs: https://mlflow.org/docs/latest/llms/llm-evaluate/index.html
- Databricks LangChain docs: https://docs.databricks.com/aws/en/generative-ai/agent-framework/agent-overview

---

*Workshop version: 1.0 | Built for Databricks AI Platform*
