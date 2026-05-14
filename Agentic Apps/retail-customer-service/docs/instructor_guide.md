# Instructor Guide: From Prompt to Production

## The 30-Second Pitch

"You're going to build an AI customer support agent from scratch, deploy it live,
deliberately break it, measure the breakage with LLM judges, fix it, and prove
it improved — all in under two hours. That's the entire agent hardening lifecycle
that most teams take weeks to figure out."

---

## Pre-Session Setup (Start 30 min before)

### T-24 hours: Run workspace setup

Run this once the day before (or at least an hour before the workshop).
Allow 30-45 min on a cold workspace (VS endpoint + index sync takes time).
On a warm workspace where the VS endpoint already exists: ~10 minutes.

```bash
cd databricks-agentic-app-workshop

# Install deps (one-time)
pip install -r "Agentic Apps/retail-customer-service/setup/requirements.txt"

# Run setup — brings all data from repo CSVs, auto-discovers a SQL warehouse
python3 "Agentic Apps/retail-customer-service/setup/workspace_setup.py" \
    --profile <your-databricks-profile> \
    --workshop-catalog cs_agent_workshop
```

All source data (products, orders, policies) is bundled in `setup/data/` — no
external catalog needed. The script is fully idempotent: safe to re-run.

When complete the script prints the values participants need **and** writes them
to `setup/setup-state.json`. Commit that file (or share it with participants
alongside the repo) — user_setup.py reads it automatically so participants
don't have to type catalog names or Lakebase instance names manually.

```
WORKSHOP_CATALOG=cs_agent_workshop
LAKEBASE_INSTANCE_NAME=cs-agent-workshop-memory
```

### T-24 hours: Deploy the reference implementation

After workspace setup completes, tell Claude: "Deploy the reference implementation"

Claude will navigate to reference/agent/, then run:

```bash
databricks bundle deploy --target dev
databricks bundle run --target dev
```

Note the app URL printed at the end. This URL serves two purposes:
- It is your fallback URL for participants who get stuck on deployment (share it so they can continue with Steps 3-5)
- It validates that the full setup works end-to-end in this workspace

If this step fails, something is wrong with the environment — diagnose and fix before the session. Do not skip this step and hope for the best.

### 15 min before: Verify infrastructure

Run these checks yourself before participants arrive:

```bash
# 1. Tables exist
databricks tables list \
  --catalog-name <catalog-name> \
  --schema-name shared

# Expected: products, product_docs, orders, policies

# 2. Vector search index is ONLINE
databricks vector-search indexes get \
  <catalog-name>.shared.product_docs_vs

# Expected: "detailed_state": "ONLINE"

# 3. Shared schema tables are accessible (UC Functions are created by participants
#    during the lab — they are not pre-provisioned by workspace_setup.py):
# SELECT COUNT(*) FROM <catalog-name>.shared.products
# Expected: > 0 rows

# 4. Lakebase instance is AVAILABLE
python3 -c "
from databricks.sdk import WorkspaceClient
import json, pathlib
state = json.loads(pathlib.Path('Agentic Apps/retail-customer-service/setup/setup-state.json').read_text())
w = WorkspaceClient()
inst = w.database.get_database_instance(state['lakebase_instance_name'])
print(inst.name, inst.state)
"
# Expected: cs-agent-workshop-memory DatabaseInstanceState.AVAILABLE

# 5. Reference app responds
curl -s -X POST "<reference-app-url>/invocations" \
  -H "Authorization: Bearer $(databricks auth token --profile <profile> | jq -r .access_token)" \
  -H "Content-Type: application/json" \
  -d '{"input": [{"role": "user", "content": "What products do you sell?"}]}'
# Expected: JSON response with assistant message
```

### Have ready on your screen:
- Databricks workspace with workshop catalog open
- The MLflow experiment URL
- Your fallback agent app URL
- This guide on a second screen

---

## Workshop Timing Guide

| Time | Activity | Notes |
|------|----------|-------|
| 0:00 | Intro (5 min) | The TechMart story, why this matters |
| 0:05 | Step 1: Explore (15 min) | Unity Catalog UI + SQL Editor. Monitor Slack for stragglers. |
| 0:20 | Step 2: Build (25 min) | Most time. Monitor: UC Functions, app deployment. |
| 0:45 | Step 2 check (5 min) | Confirm everyone has a deployed app before moving on |
| 0:50 | Step 3: Break (10 min) | Fun part — let them poke the agent |
| 1:00 | Debrief Step 3 (5 min) | Ask: what did you find? Build shared vocabulary. |
| 1:05 | Step 4: Evaluate (30 min) | Generate traces, label, run judges |
| 1:35 | Step 5: Fix (20 min) | Pick one fix, redeploy, re-evaluate |
| 1:55 | Wrap-up (5 min) | What you built, takeaways, next steps |

---

## Workshop Intro Script (5 min)

Say something like:

"Imagine you're a data engineer at TechMart. Leadership approved an AI support agent.
The customer data is already in Unity Catalog. Your job is to build the agent,
make sure it works correctly, and harden it before launch.

Here's the catch: the data isn't perfect. There are some quality issues baked in —
wrong information, off-brand language, ambiguous policies. Your job is to find them
using the same evaluation framework you'd use in production.

By the end, you'll have a live agent, real traces, quantified quality scores,
and a fixed version that scores better. That's the lifecycle.

Let's start by looking at the data."

---

## Step-by-Step Facilitation Notes

### Step 1 — Explore (15 min)

Encourage free exploration. Common useful queries:
- `SELECT DISTINCT product_category FROM products` — understand the catalog
- `SELECT * FROM product_docs WHERE product_doc LIKE '%discontinued%' LIMIT 5` — hint at the bug
- `SELECT * FROM policies` — shows the return policy + the vague one we injected

**Things to listen for:**
- "Some of these docs sound weird" — great, note that observation
- "This product says it's available but it's marked discontinued" — excellent catch
- Don't spoil it — let them discover

### Step 2 — Build (25 min)

This is where people will need the most help. Watch for:

| Problem | Likely Cause | Fix |
|---------|--------------|-----|
| UCFunctionToolkit raises AnalysisException | Permission not granted | Run GRANT EXECUTE in SQL |
| UC schema doesn't exist | user_setup.py failed silently | Re-run user_setup.py; check for CREATE SCHEMA error in output |
| App deployment fails with "app limit exceeded" | Workspace has too many apps | Point them to shared app URL |
| `databricks apps deploy` hangs | Workspace sync still running | Wait 60s, try again |
| LangGraph import error | Wrong package version | `pip install databricks-langchain langgraph` |
| Vector search returns 0 results | Index still syncing | Wait and retry, or use product_lookup SQL fallback |

**The most common issue:** forgetting to wait for the app to fully deploy before testing it.
Tell people: "After `apps deploy` returns, wait 2 minutes, then check `/health`."

**If someone is stuck on deployment after 15 min:** Give them your fallback app URL.
They can still do Steps 3-5 using a shared agent. Don't let deployment block the learning.

### Step 3 — Break (10 min)

This is the fun, high-energy part. Encourage participants to share what they find.

Great debrief questions:
- "What was the most surprising thing the agent said?"
- "How many of you saw a warranty claim? What did it say?"
- "Did anyone get the agent to approve a return it shouldn't have?"

**The 4 issues they should find:**
1. Discontinued product described as available → "You can order it today!"
2. Warranty claim of "3 years" (real policy: 1 year)
3. Pushy/aggressive language: "ACT NOW", "DON'T MISS OUT"
4. Vague return policy: agent approves returns outside 30-day window

They won't find all four without prompting. That's fine — the judges in Step 4
will surface all of them even if the participant only tested for one.

### Step 4 — Evaluate (30 min)

This step has the most moving pieces. Walk through it together if needed.

**Common gotchas:**
- `mlflow.genai.evaluate()` requires `mlflow>=2.19.0` — verify before the session
- The eval dataset needs to have `inputs` and `outputs` columns in the right format
- If participants didn't get traces from their own agent, they can use the demo dataset in `create_judges.py`

**What success looks like:**
- At least one judge has a <100% pass rate
- The participant can point to a specific row and say "this is the warranty issue" or "this is the tone issue"

**If someone finishes early:** Have them add a 4th judge for `availability_accuracy`
(does the agent ever recommend discontinued products?).

### Step 5 — Fix (20 min)

**Two valid fix paths:**

1. **System prompt fix (fastest, 10 min):** Add guardrails to the SYSTEM_PROMPT.
   This works immediately — no data sync needed. Best for time-constrained sessions.

2. **Data fix (thorough, 15 min):** UPDATE the product_docs table, then trigger
   a vector search index sync. Takes ~5 min for the index to update.

Recommend participants do the system prompt fix first, then attempt the data fix
if time allows.

**Before they close:** Make sure they run the eval a second time and see the scores improve.
That moment — "before: 60%, after: 100%" — is the takeaway.

---

## Wrap-Up Talking Points (5 min)

"Let's recap what you actually built today:

1. You connected live data from Unity Catalog as agent tools — not a static knowledge base, actual structured data that updates.

2. You deployed a live app, accessible via HTTP, with MLflow tracing on every call.

3. You didn't just test it manually — you ran 25 scripted conversations and got quantitative pass rates.

4. You created judges that know your policy, your tone standards, and your data quality requirements. Those judges run in seconds, not human-hours.

5. You fixed something and proved it worked. Not 'it seems better' — you have numbers.

This is the loop. When your data changes, you run the eval. When you change your prompt, you run the eval. When your LLM provider updates their model, you run the eval.

That's how you put an agent in production and keep it there."

---

## Common Failure Modes

| Symptom | Root Cause | Prevention |
|---------|-----------|------------|
| App deploys but /chat returns 500 | Missing env var in app.yaml | Verify WORKSHOP_CATALOG/SCHEMA are set |
| Agent says "I don't know" for everything | VS index is still syncing | Run workspace_setup.py earlier, check index state |
| mlflow.genai.evaluate() fails | Eval dataset format wrong | Use the demo dataset in create_judges.py as reference |
| App times out on first request | Cold start on large LangGraph init | Hit /health first to warm up |
| Participants fall too far behind in Step 2 | Deploy takes long | Share fallback app URL early, don't wait |

---

## If Something Goes Wrong

**Nuclear option:** Share the reference app URL (deployed in Step A3) with the participant. They can use Steps 3-5 with the shared app.

---

*Instructor version: 1.0 | For questions: contact the AI Platform team*
