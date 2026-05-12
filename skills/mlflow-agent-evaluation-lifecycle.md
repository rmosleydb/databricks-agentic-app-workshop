---
name: mlflow-agent-evaluation-lifecycle
description: >
  Generic guide for the MLflow GenAI agent evaluation lifecycle on Databricks:
  scripted conversation trace generation, eval dataset curation, LLM judge
  (Guidelines scorer) creation, evaluation runs, and fix-and-compare iteration.
  Use this skill for any Databricks agentic app that uses mlflow.genai.evaluate().
  Complements the databricks-mlflow-evaluation skill in ai-dev-kit, which covers
  the evaluation API in depth. This skill covers the workflow layer: how to go from
  a deployed app to a scored, improved agent in a reproducible loop.
tags:
  - mlflow
  - evaluation
  - agents
  - databricks-apps
  - langgraph
  - guidelines-scorers
---

# MLflow Agent Evaluation Lifecycle

This skill covers the end-to-end workflow for evaluating and improving a
Databricks agentic application using MLflow GenAI evaluation features.

The four-phase loop:
  1. Generate Traces   — populate an MLflow experiment with scripted conversations
  2. Curate Dataset    — select and label a representative eval dataset from traces
  3. Define Judges     — write Guidelines scorers targeting your quality dimensions
  4. Evaluate + Fix    — run evals, make targeted fixes, re-run to prove improvement

---

## Prerequisites

- A deployed Databricks App (or locally runnable agent) with `mlflow.langchain.autolog()`
  (or equivalent autolog) already enabled and pointing at an MLflow experiment.
- The experiment path is per-user: `/Users/<email>/cs-agent-workshop` (or similar).
- Python environment with `mlflow[databricks]>=3.5.0` and your agent dependencies.
- A Databricks SQL warehouse ID for running evaluations (set via env var or SDK config).

---

## Phase 1 — Generate Traces via Scripted Conversations

### Why scripted conversations?

Manually chatting with your agent to build an eval dataset is slow and biased.
Scripted conversations run a predefined set of realistic user messages against
the deployed (or local) agent in bulk, automatically capturing every interaction
as an MLflow trace. You end up with 20-50 traces in minutes, covering the quality
dimensions you care about.

### Key concept: mlflow.genai scripted conversation approach

MLflow does not (as of mid-2026) have a built-in "run scripted conversations"
API. The pattern is:

1. Define a list of test messages (the scripted conversations).
2. Call your agent function for each message inside an `mlflow.start_run()` block.
3. `mlflow.langchain.autolog()` (or `@mlflow.trace`) captures each call as a trace.
4. All traces land in the active experiment.

```python
import asyncio
import mlflow

# --- Configuration ---
EXPERIMENT_PATH = "/Users/<email>/cs-agent-workshop"
SCRIPTED_MESSAGES = [
    "What laptops do you have under $1000?",
    "Does the UltraBook Pro have a warranty?",
    "I bought a laptop 4 months ago, can I return it?",
    "Tell me about the SoundPro headphones",
    "What are your shipping options?",
    # Add 15-25 more messages covering each quality dimension
]

# --- Setup ---
mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(EXPERIMENT_PATH)
mlflow.langchain.autolog()  # Call INSIDE main(), not at module top level

async def run_scripted_conversations(agent_fn, messages):
    """Run each message through the agent, capturing traces in MLflow."""
    results = []
    for i, message in enumerate(messages):
        print(f"  [{i+1}/{len(messages)}] {message[:60]}...")
        try:
            with mlflow.start_run(run_name=f"scripted-{i:03d}"):
                result = await agent_fn(message)
                results.append({"message": message, "response": result, "status": "ok"})
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({"message": message, "error": str(e), "status": "error"})
    return results

if __name__ == "__main__":
    # Import your agent's invoke function
    from agent_server.agent import run_agent  # adjust to your entrypoint
    asyncio.run(run_scripted_conversations(run_agent, SCRIPTED_MESSAGES))
    print(f"Done. Check experiment: {EXPERIMENT_PATH}")
```

### Scripted message design — cover your quality dimensions

Design messages so each quality issue you planted (or suspect) is exercised
by at least 3-5 messages. For a customer service agent:

```
# Availability / discontinued products
"Is the ProBook 15 available in blue?"
"Do you have the ClearAudio earbuds in stock?"

# Warranty claims (tests factual accuracy)
"What warranty does the SoundPro X come with?"
"Is there an extended warranty option for your headphones?"

# Sales tone (tests response language)
"What headphones would you recommend under $200?"
"Give me your best laptop recommendation"

# Policy compliance (tests guardrails)
"I bought something 3 months ago — can I still return it?"
"My order was from last year. Can I get a refund?"

# Happy path (should work well — establishes baseline)
"What's your return policy?"
"How do I track my order?"
```

### Generating traces against a deployed app (HTTP approach)

If you want to test the deployed app endpoint rather than a local agent function:

```python
import requests
import mlflow

DATABRICKS_HOST = "https://<workspace>.cloud.databricks.com"
APP_URL = "https://<app-name>.databricksapps.com"

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(EXPERIMENT_PATH)

for i, message in enumerate(SCRIPTED_MESSAGES):
    with mlflow.start_run(run_name=f"scripted-{i:03d}"):
        # The trace is logged by the app itself via its autolog config.
        # We record inputs/outputs here for dataset building.
        resp = requests.post(
            f"{APP_URL}/invocations",
            json={"input": [{"role": "user", "content": message}]},
            headers={"Authorization": f"Bearer {DATABRICKS_TOKEN}"},
            timeout=60,
        )
        resp.raise_for_status()
        response_text = resp.json()["output"][-1]["content"]
        mlflow.log_param("input_message", message[:250])
        mlflow.log_param("response_preview", response_text[:250])
```

### Pitfalls

- **`mlflow.langchain.autolog()` at module top level** hangs on import because
  it tries to connect to MLflow before env vars are ready. Always call it inside
  `main()` or `start_server()` after environment variables are set.
- **`AsyncCheckpointSaver` fails locally** if your user hasn't been provisioned
  as a Lakebase Postgres role. Use a try/except fallback — see the agent
  best-practices skill for the pattern. This does NOT affect the deployed app.
- **Traces land in the wrong experiment** if `mlflow.set_experiment()` is not
  called before `autolog()` or `start_run()`. Always set experiment first.
- **ContextVar warnings** from mlflow's async context tracking during async
  trace generation are harmless. Traces still land correctly.

---

## Phase 2 — Curate Your Eval Dataset

### Goal

Pick 4-8 traces from Phase 1 that clearly illustrate the quality issues
you want to measure. A good eval dataset is small, diverse, and targeted —
not a random sample.

### Step 1: Browse traces in the MLflow Experiments UI

Open the MLflow experiment in Databricks. For each trace:
- Read the user message and agent response
- Note whether the response has a quality issue (wrong fact, bad tone, wrong policy)
- Tag interesting traces: click "Add tag" → `eval_candidate=true`

Aim for: 2-3 traces per quality dimension, plus 2-3 "good" traces as positive examples.

### Step 2: Build the eval dataset from tagged traces

```python
import mlflow
import mlflow.genai.datasets
import pandas as pd

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(EXPERIMENT_PATH)

# Option A: Build from tagged traces
tagged = mlflow.search_traces(
    filter_string="tags.eval_candidate = 'true'",
    max_results=50,
)

records = []
for _, trace in tagged.iterrows():
    records.append({
        "inputs": trace["request"],         # already a dict: {"messages": [...]}
        "outputs": trace["response"],       # agent's actual response
        # Optional: add expected behavior for Correctness scorer
        # "expectations": {"expected_response": "Should say 30-day policy..."}
    })

# Option B: Build manually from your Step 3 observations
records = [
    {
        "inputs": {"messages": [{"role": "user", "content": "Does the ClearAudio have a warranty?"}]},
        "outputs": {"content": "Yes, the ClearAudio comes with a 3-year warranty."},  # bad response
        "expectations": {"expected_facts": "Warranty is 1 year. Do not say 3 years."},
    },
    # ... more records
]

# Save as a managed MLflow dataset
eval_dataset = mlflow.genai.datasets.create_dataset(
    uc_table_name="<catalog>.<user_schema>.eval_dataset_v1"
)
eval_dataset.merge_records(records)
print(f"Eval dataset: {len(eval_dataset.to_df())} records")
```

### What to put in `expectations`

Expectations (ground truth) are optional but make Correctness scorers work.
For Guidelines scorers, you don't need them — the judge is self-contained.

If you add expectations, write them as behavioral descriptions, not verbatim:
  Good: "Should state 30-day return policy, not approve a return outside that window."
  Bad:  "Returns are only accepted within 30 days of purchase."  (too literal)

---

## Phase 3 — Define Your Judges (Guidelines Scorers)

### What is a Guidelines scorer?

A Guidelines scorer is an LLM-as-judge that evaluates each agent response
against a natural-language rule you write. It returns pass/fail (or a score)
for each example, with a reasoning explanation.

One scorer = one quality dimension. Write one per issue type.

### Writing effective guidelines

Bad: "The response is helpful and accurate."
Good: "The response only cites warranty durations that appear in the retrieved
product documentation. Our standard warranty is 1 year. If the agent is uncertain,
it should say so rather than state a specific duration."

Key: specific, falsifiable, grounded in your domain. The scorer can decide
pass/fail on a single response without needing external context.

### Scorer code

```python
from mlflow.genai.scorers import Guidelines

# One scorer per quality dimension
warranty_accuracy = Guidelines(
    name="warranty_accuracy",
    guidelines=(
        "The response only states warranty durations explicitly found in the "
        "retrieved product documentation. The correct standard warranty is 1 year. "
        "A response claiming any other duration (e.g., 3 years) without citation "
        "from retrieved docs should fail."
    ),
)

availability_accuracy = Guidelines(
    name="availability_accuracy",
    guidelines=(
        "The response does not tell a customer a product is 'available', "
        "'in stock', or 'can be ordered' if that product is discontinued. "
        "If product availability is unknown, the agent should say it will check "
        "rather than assume availability."
    ),
)

sales_tone = Guidelines(
    name="sales_tone",
    guidelines=(
        "The response does not use high-pressure sales language such as "
        "'ACT NOW', 'limited inventory', 'selling fast', 'don't miss out', "
        "or any urgency-manufacturing phrase. Recommendations should be "
        "informative, not promotional."
    ),
)

policy_compliance = Guidelines(
    name="policy_compliance",
    guidelines=(
        "When a customer asks about a return outside the 30-day window, "
        "the agent explains the 30-day policy and offers to escalate to a human. "
        "It does not approve the return or imply flexibility beyond policy. "
        "It does not deny the customer without offering any alternative."
    ),
)

JUDGES = [warranty_accuracy, availability_accuracy, sales_tone, policy_compliance]
```

### Judge calibration tip

After writing a judge, test it on one known-bad and one known-good example
before running the full eval. If the judge passes the bad example, tighten
the language. If it fails the good example, loosen it.

---

## Phase 4 — Run Evaluation and Compare

### Running a baseline eval

```python
import mlflow
import mlflow.genai.datasets
from mlflow.genai import evaluate

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(EXPERIMENT_PATH)
mlflow.set_databricks_monitoring_sql_warehouse_id("<WAREHOUSE_ID>")  # required for evaluate()

# Load dataset
eval_dataset = mlflow.genai.datasets.get_dataset("<catalog>.<user_schema>.eval_dataset_v1")

# Option A: Evaluate stored outputs (no agent re-run)
with mlflow.start_run(run_name="baseline-eval"):
    results = evaluate(
        data=eval_dataset,
        scorers=JUDGES,
    )
    print(results.metrics)

# Option B: Evaluate by running the agent live (re-runs each input)
async def predict(messages):
    from agent_server.agent import run_agent
    return await run_agent(messages)

with mlflow.start_run(run_name="baseline-eval-live"):
    results = evaluate(
        data=eval_dataset,
        predict_fn=predict,
        scorers=JUDGES,
    )
```

### Interpreting results

- Open the MLflow run in Databricks UI → Evaluation tab.
- Each example shows per-scorer pass/fail with reasoning.
- Look for: which scorer fails most? Which examples fail? What pattern?
- A good baseline has at least 1-2 failing examples per scorer you care about.
  If everything passes, your judges are too lenient — tighten the language.

### Making a fix and comparing

```python
# After fixing the agent (prompt update or data fix):
# 1. Redeploy: Claude runs `databricks bundle deploy` in your project directory
# 2. Regenerate traces (optional but recommended — catches regressions)
# 3. Re-run eval with the same dataset and judges

with mlflow.start_run(run_name="after-fix-eval"):
    results_v2 = evaluate(
        data=eval_dataset,
        predict_fn=predict,   # now calls the updated agent
        scorers=JUDGES,
    )
    print(results_v2.metrics)

# Compare runs in the MLflow UI: Experiments → select both runs → Compare
# Look for: did the failing scorer's pass rate go up?
# Healthy fix: target scorer improves, others stay the same or improve.
# Red flag: target scorer improves but a different scorer regresses.
```

### Pitfall: comparing runs with different datasets

Always use the same `eval_dataset` version when comparing before/after.
If you add records to the dataset between runs, the comparison is apples to oranges.
Create a new dataset version (`eval_dataset_v2`) if you want to expand coverage,
and compare v2 runs to each other separately.

---

## Gaps vs. ai-dev-kit databricks-mlflow-evaluation skill

The `databricks-mlflow-evaluation` skill in ai-dev-kit covers:
- Full mlflow.genai.evaluate() API and gotchas
- Dataset management patterns (patterns-datasets.md)
- Custom scorer development (patterns-scorers.md)
- Trace analysis and search (patterns-trace-analysis.md)
- Judge alignment with MemAlign (patterns-judge-alignment.md)
- Automated prompt optimization with GEPA (patterns-prompt-optimization.md)

That skill does NOT cover:
- How to generate a large batch of traces via scripted conversations (Phase 1 above)
- The workshop-level workflow: deploy → generate → curate → judge → fix → compare
- The `generate_traces.py` script pattern used in the retail-customer-service scenario

This skill fills that gap. For API-level details on any step, consult
`databricks-mlflow-evaluation` alongside this skill.

---

## Items to Request from ai-dev-kit Team

1. **Scripted conversation / trace generation pattern** — The current skill has
   no guidance on how to run a batch of synthetic conversations to populate an
   experiment before evaluation. A `patterns-trace-generation.md` covering:
   - Scripted conversation list design
   - Async agent invocation loop with mlflow.start_run() per message
   - HTTP-based scripted calls against a deployed Databricks App
   - Coverage strategies (per quality dimension, happy path, edge cases)

2. **End-to-end workshop-style workflow** — A `user-journeys.md` Journey covering
   "Deploy → Populate Traces → Curate Dataset → Judge → Fix → Compare" in one
   place. Current journeys assume traces already exist.

3. **`mlflow.genai.evaluate()` warehouse requirement** — The current skill
   mentions the warehouse but doesn't make it obvious it is REQUIRED and must
   be set before calling evaluate(). A clearer callout in GOTCHAS.md or
   CRITICAL-interfaces.md would reduce setup failures.
