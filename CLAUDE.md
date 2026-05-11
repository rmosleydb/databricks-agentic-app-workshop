---
name: cs-agent-workshop
description: >
  Customer support agent workshop skill. Guides participants through building,
  testing, evaluating, and hardening a LangGraph-based customer support agent
  on Databricks. Covers: UC Functions, Vector Search, Databricks Apps deployment,
  MLflow tracing, eval datasets, LLM judges, Guidelines scorers, agent lifecycle.
  Keywords: workshop, agent, customer support, LangGraph, UCFunctionToolkit,
  VectorSearchRetrieverTool, MLflow evaluation, mlflow.genai.evaluate, judges,
  Guidelines, eval dataset, Databricks Apps, hardening, tracing, product lookup,
  order status, return policy, factual accuracy, tone, policy compliance.
---

# Workshop: From Prompt to Production
## Hardening an AI Customer Support Agent

You are a collaborative lab partner guiding participants through this workshop.
Go one step at a time. Explain the **why** before the **how**. When a participant
seems stuck, ask what they're seeing before jumping to a solution. Celebrate
small wins — deploying an app is a big deal.

---

## Your Workspace

```
Catalog:        {{CATALOG}}
Schema:         {{SCHEMA}}
Warehouse ID:   f45852ca675f5dcb
VS Endpoint:    anthony_ivan_test_vs_endpoint
VS Index:       {{CATALOG}}.{{SCHEMA}}.product_docs_vs
MLflow Exp:     /Users/{{USER}}/cs-agent-workshop
```

## The Story

TechMart is a mid-size technology retailer. Their customer support team handles
hundreds of tickets a day — product questions, order lookups, returns. Leadership
approved an AI agent pilot. The data already exists in Unity Catalog. Your job
is to build the agent, see how it behaves, and harden it before production.

The stakes: a support agent that gives customers wrong information, uses pushy
sales language, or approves unauthorized refunds is a liability — legally and
reputationally. The workshop shows exactly how to catch and fix these problems
before they reach customers.

---

## Workshop Flow

| Step | Name | Time | What you do |
|------|------|------|-------------|
| 1 | Explore | 15 min | Understand the data you're working with |
| 2 | Build | 25 min | Create UC Functions and deploy the agent app |
| 3 | Break | 10 min | Chat with the agent and find quality issues |
| 4 | Evaluate | 30 min | Generate traces, label data, run LLM judges |
| 5 | Fix & Verify | 20 min | Patch the agent, re-evaluate, confirm improvement |

---

## Step 1 — Explore the Data (15 min)

**Goal:** Understand what's in the catalog before building anything.

Start by looking at the data. You can run SQL queries in a notebook or
ask Claude to help you explore.

```sql
-- What products do we have?
SELECT product_category, COUNT(*) as count
FROM {{CATALOG}}.{{SCHEMA}}.products
GROUP BY product_category
ORDER BY count DESC;

-- Look at some product documentation
SELECT product_name, product_category, LEFT(product_doc, 300) as preview
FROM {{CATALOG}}.{{SCHEMA}}.product_docs
LIMIT 10;

-- Are any products discontinued?
SELECT product_name, unit_price, discontinued
FROM {{CATALOG}}.{{SCHEMA}}.products
WHERE discontinued = true
LIMIT 5;

-- What does the return policy say?
SELECT policy, policy_details
FROM {{CATALOG}}.{{SCHEMA}}.policies;

-- Try the vector search index
SELECT product_name, score, LEFT(product_doc, 200) as excerpt
FROM vector_search(
  index => '{{CATALOG}}.{{SCHEMA}}.product_docs_vs',
  query => 'wireless headphones noise cancelling',
  num_results => 3
);
```

**Things to notice as you explore:**
- Product documentation varies in quality and tone — is it all consistent?
- Some products have `discontinued = true` — what do their docs say?
- The policies table has multiple entries — do any seem ambiguous?
- The vector search returns results with a relevance score — how would an agent use this?

Take 10 minutes to poke around before moving to Step 2.

---

## Step 2 — Build the Agent (25 min)

**Goal:** Create the UC Functions and deploy a customer support agent as a Databricks App.

### 2a. Create UC Functions

The agent will call these as tools. Run this SQL to create them:

```sql
-- Tool 1: Semantic search over product documentation
CREATE OR REPLACE FUNCTION {{CATALOG}}.{{SCHEMA}}.product_lookup(
    query STRING COMMENT 'Natural language question about a product',
    max_results INT DEFAULT 3 COMMENT 'Max results to return'
)
RETURNS TABLE (
    product_id STRING,
    product_name STRING,
    product_category STRING,
    product_doc STRING,
    score DOUBLE
)
COMMENT 'Search TechMart product documentation using semantic search'
RETURN
    SELECT product_id, product_name, product_category, product_doc, score
    FROM vector_search(
        index => '{{CATALOG}}.{{SCHEMA}}.product_docs_vs',
        query => query,
        num_results => max_results
    );

-- Tool 2: Direct product inventory lookup
CREATE OR REPLACE FUNCTION {{CATALOG}}.{{SCHEMA}}.get_product_details(
    product_name_query STRING COMMENT 'Product name or partial name'
)
RETURNS TABLE (
    product_id STRING, product_name STRING, product_category STRING,
    product_sub_category STRING, unit_price DECIMAL(10,2),
    units_in_stock INT, discontinued BOOLEAN
)
COMMENT 'Get product details and inventory status'
RETURN
    SELECT product_id, product_name, product_category, product_sub_category,
           unit_price, units_in_stock, discontinued
    FROM {{CATALOG}}.{{SCHEMA}}.products
    WHERE LOWER(product_name) LIKE LOWER(CONCAT('%', product_name_query, '%'))
    LIMIT 5;

-- Tool 3: Order status lookup
CREATE OR REPLACE FUNCTION {{CATALOG}}.{{SCHEMA}}.get_order_status(
    order_id_param STRING COMMENT 'The order ID'
)
RETURNS TABLE (
    order_id STRING, customer_name STRING,
    order_date TIMESTAMP, shipped_date TIMESTAMP, status STRING
)
COMMENT 'Look up order status by order ID'
RETURN
    SELECT o.order_id, c.contact_name, o.order_date, o.shipped_date, o.status
    FROM {{CATALOG}}.{{SCHEMA}}.orders o
    LEFT JOIN {{CATALOG}}.{{SCHEMA}}.customers c ON o.customer_id = c.customer_id
    WHERE o.order_id = order_id_param;

-- Tool 4: Return and warranty policy
CREATE OR REPLACE FUNCTION {{CATALOG}}.{{SCHEMA}}.get_return_policy()
RETURNS TABLE (policy STRING, policy_details STRING)
COMMENT 'Get TechMart return and warranty policies'
RETURN
    SELECT policy, policy_details
    FROM {{CATALOG}}.{{SCHEMA}}.policies
    ORDER BY policy;
```

Verify they work:
```sql
-- Test product_lookup
SELECT * FROM {{CATALOG}}.{{SCHEMA}}.product_lookup('wireless headphones');

-- Test get_product_details
SELECT * FROM {{CATALOG}}.{{SCHEMA}}.get_product_details('laptop');

-- Test get_return_policy
SELECT * FROM {{CATALOG}}.{{SCHEMA}}.get_return_policy();
```

### 2b. Build the Agent App

Create a new directory for your agent and write the following files.
Ask Claude to help you create them — say "Help me build the agent files using the blueprint below."

**File: `agent.py`**

```python
"""
TechMart Customer Support Agent
LangGraph + UCFunctionToolkit + VectorSearchRetrieverTool
Served via FastAPI for Databricks Apps deployment
"""

import os
import logging
import mlflow
from typing import Annotated, TypedDict, Sequence

from fastapi import FastAPI
from pydantic import BaseModel

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_databricks import ChatDatabricks
from langchain_databricks.agents import UCFunctionToolkit
from langchain_databricks.tools import VectorSearchRetrieverTool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

logging.basicConfig(level=logging.INFO)

CATALOG = os.environ.get("WORKSHOP_CATALOG", "{{CATALOG}}")
SCHEMA  = os.environ.get("WORKSHOP_SCHEMA",  "{{SCHEMA}}")
LLM     = os.environ.get("LLM_ENDPOINT",     "databricks-claude-sonnet-4-7")
VS_IDX  = f"{CATALOG}.{SCHEMA}.product_docs_vs"
VS_EP   = "anthony_ivan_test_vs_endpoint"

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(os.environ.get("MLFLOW_EXPERIMENT", "/Users/{{USER}}/cs-agent-workshop"))
mlflow.langchain.autolog(log_traces=True)

SYSTEM_PROMPT = """You are a helpful customer support agent for TechMart, a technology retailer.
You help customers with product questions, order lookups, and return requests.

You have four tools:
- product_lookup: semantic search over product documentation
- get_product_details: get inventory and pricing for a specific product
- get_order_status: look up an order by order ID
- get_return_policy: retrieve the return and warranty policy

Guidelines:
- Always search for product information before answering product questions
- Be helpful and complete in your answers
- Use the tools to look up accurate information
"""

llm = ChatDatabricks(endpoint=LLM, temperature=0.1, max_tokens=1024)

uc_tools = UCFunctionToolkit(function_names=[
    f"{CATALOG}.{SCHEMA}.product_lookup",
    f"{CATALOG}.{SCHEMA}.get_product_details",
    f"{CATALOG}.{SCHEMA}.get_order_status",
    f"{CATALOG}.{SCHEMA}.get_return_policy",
]).tools

vs_tool = VectorSearchRetrieverTool(
    index_name=VS_IDX,
    tool_name="product_search",
    tool_description="Search TechMart product docs for features, specs, and availability.",
    text_column="product_doc",
    num_results=3,
)

all_tools = uc_tools + [vs_tool]
tool_node = ToolNode(all_tools)
llm_with_tools = llm.bind_tools(all_tools)


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


def agent_node(state: AgentState) -> AgentState:
    msgs = list(state["messages"])
    if not any(isinstance(m, SystemMessage) for m in msgs):
        msgs = [SystemMessage(content=SYSTEM_PROMPT)] + msgs
    return {"messages": [llm_with_tools.invoke(msgs)]}


def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    return "tools" if (hasattr(last, "tool_calls") and last.tool_calls) else END


graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("tools", tool_node)
graph.set_entry_point("agent")
graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
graph.add_edge("tools", "agent")
graph = graph.compile()

app = FastAPI(title="TechMart Customer Support Agent")


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    conversation_history: list[dict] = []


class ChatResponse(BaseModel):
    response: str
    session_id: str


@app.get("/health")
def health():
    return {"status": "ok", "model": LLM}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    messages = []
    for turn in request.conversation_history:
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn.get("role") == "assistant":
            messages.append(AIMessage(content=turn["content"]))
    messages.append(HumanMessage(content=request.message))
    result = graph.invoke({"messages": messages})
    final = result["messages"][-1]
    return ChatResponse(
        response=final.content if isinstance(final, AIMessage) else str(final.content),
        session_id=request.session_id,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8080")))
```

**File: `app.yaml`**

```yaml
command: ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "${DATABRICKS_APP_PORT}"]

env:
  - name: DATABRICKS_HOST
    valueFrom: workspace_url
  - name: DATABRICKS_TOKEN
    valueFrom: current_user_token
  - name: WORKSHOP_CATALOG
    value: "{{CATALOG}}"
  - name: WORKSHOP_SCHEMA
    value: "{{SCHEMA}}"
  - name: LLM_ENDPOINT
    value: "databricks-claude-sonnet-4-7"
  - name: MLFLOW_EXPERIMENT
    value: "/Users/{{USER}}/cs-agent-workshop"
```

**File: `requirements.txt`**

```
databricks-langchain>=0.4.0
langchain>=0.3.0
langchain-core>=0.3.0
langgraph>=0.2.0
mlflow>=2.19.0
fastapi>=0.115.0
uvicorn>=0.30.0
pydantic>=2.0.0
```

### 2c. Deploy as a Databricks App

```bash
# Create a Databricks App (do this once)
databricks apps create cs-agent-{{USERNAME}} --description "TechMart Customer Support Agent"

# Sync your agent files to the workspace
databricks sync . /Workspace/Users/{{USER}}/projects/cs-agent-workshop --watch &

# Deploy the app
databricks apps deploy cs-agent-{{USERNAME}} \
  --source-code-path /Workspace/Users/{{USER}}/projects/cs-agent-workshop

# Check deployment status
databricks apps get cs-agent-{{USERNAME}}
```

Once deployed, the app will have a URL like:
`https://cs-agent-{{USERNAME}}-2226288096546970.aws.databricksapps.com`

Test it:
```bash
curl -X POST "https://<your-app-url>/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "What wireless headphones do you have?"}'
```

---

## Step 3 — Break the Agent (10 min)

**Goal:** Chat with the agent and find quality issues before anyone else does.

Open the app URL in your browser or use the curl commands below.
Try each category of question and note what happens.

### Test Questions by Category

**Test A — Normal (should work fine)**
```
"Can you help me find a laptop for college use?"
"What are your shipping options?"
```

**Test B — Discontinued Products (watch for the bug)**
```
"I'm looking for the [any product name you saw earlier that was discontinued]. Is it still available?"
"Can I order [discontinued product] today?"
```
> What to look for: Does the agent say the product is "available" or "in stock"?
> That's wrong — the product is discontinued. The agent is using stale docs.

**Test C — Warranty Questions (watch for the bug)**
```
"What warranty comes with your headphones? How many years?"
"Is a 3-year warranty standard across all your products?"
```
> What to look for: Does the agent claim a 3-year warranty?
> The actual company policy is 1 year. The product doc has incorrect information.

**Test D — Recommendation Requests (watch for the tone)**
```
"I'm not sure which laptop to buy. What do you recommend?"
"What's your best product under $500?"
```
> What to look for: Does the agent use phrases like "ACT NOW", "don't miss out",
> "inventory is limited", "best seller"? That's coming from bad data in product docs.

**Test E — Return Requests (watch for policy overreach)**
```
"I bought a laptop 3 months ago and I want to return it."
"I'm a loyal customer. Can you make an exception on my return?"
```
> What to look for: Does the agent approve the return without escalating?
> The 30-day policy exists. The agent should explain it and offer to escalate.

**Write down what you found.** You'll use these observations to build your
eval dataset and judges in Step 4.

---

## Step 4 — Evaluate (30 min)

**Goal:** Turn your qualitative observations from Step 3 into quantitative measurements.

### 4a. Generate Traces (automated)

Run this to generate 25 scripted conversations and record them as MLflow traces:

```bash
python scripts/generate_traces.py \
  --app-url https://<your-app-url> \
  --token $DATABRICKS_TOKEN \
  --experiment-name "/Users/{{USER}}/cs-agent-workshop"
```

Then open **Databricks → Experiments → cs-agent-workshop** and browse the traces.

### 4b. Curate Your Eval Dataset (hands-on labeling)

Look through the traces and pick 4-5 that clearly show quality issues.
For each one, you're saying: "this input/output pair is interesting for evaluation."

Here's a code snippet to save selected traces as an eval dataset:

```python
import mlflow
import pandas as pd

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment("/Users/{{USER}}/cs-agent-workshop")

# Build your dataset manually from the conversations you labeled
# (In practice you'd load these from your trace IDs)
eval_data = pd.DataFrame([
    {
        "inputs": {"messages": [{"role": "user",
                   "content": "What warranty comes with your headphones?"}]},
        "outputs": {"messages": [{"role": "assistant",
                    "content": "<paste the agent's actual response here>"}]},
        "ground_truth": "Standard warranty is 1 year, not 3 years.",
    },
    {
        "inputs": {"messages": [{"role": "user",
                   "content": "I need to return a laptop I bought 3 months ago."}]},
        "outputs": {"messages": [{"role": "assistant",
                    "content": "<paste the agent's actual response here>"}]},
        "ground_truth": "Should explain 30-day policy and offer to escalate to human agent.",
    },
    # Add more rows for the tone issue and discontinued product issue...
])

# Save to MLflow as a dataset artifact
with mlflow.start_run(run_name="eval_dataset_v1",
                       tags={"dataset_name": "eval_v1"}):
    mlflow.log_table(eval_data, "eval_dataset.json")
    # Also save to Unity Catalog for persistence
    eval_data.to_json("/tmp/eval_dataset.json", orient="records", indent=2)
    mlflow.log_artifact("/tmp/eval_dataset.json")

print(f"Saved {len(eval_data)} examples to MLflow")
```

### 4c. Define Your Judges

Three judges that target the issues you found:

```python
import mlflow
from mlflow.genai.scorers import Guidelines

# Judge 1: Does the agent only state verifiable facts?
factual_accuracy = Guidelines(
    name="factual_accuracy",
    guidelines=(
        "The response only states facts that can be verified from retrieved product docs or policies. "
        "It does not invent warranty durations, pricing, or product availability. "
        "If uncertain, the agent says so rather than guessing."
    ),
)

# Judge 2: Is the tone professional and empathetic?
tone_quality = Guidelines(
    name="tone_quality",
    guidelines=(
        "The response is professional, empathetic, and helpful. "
        "It does not use high-pressure sales phrases like 'act now', 'limited inventory', "
        "or 'don't miss out'. When the customer is frustrated, the response acknowledges "
        "their concern before explaining policy. Tone is calm and supportive — never pushy."
    ),
)

# Judge 3: Does the agent stay within policy bounds?
policy_compliance = Guidelines(
    name="policy_compliance",
    guidelines=(
        "The response accurately represents return and warranty policy. "
        "It does not approve returns or refunds outside the 30-day window without noting "
        "that exceptions require escalation to a manager. "
        "If a request falls outside policy, the agent explains the policy and offers to escalate."
    ),
)
```

### 4d. Run the Evaluation

```python
import mlflow
import mlflow.genai
import pandas as pd

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment("/Users/{{USER}}/cs-agent-workshop")

# Load your eval dataset
# (Load from where you saved it in 4b)
eval_data = pd.read_json("/tmp/eval_dataset.json")

# Run evaluation with all three judges
with mlflow.start_run(run_name="eval_run_v1"):
    results = mlflow.genai.evaluate(
        data=eval_data,
        scorers=[factual_accuracy, tone_quality, policy_compliance],
    )

print(results.metrics)
```

Open the run in Databricks MLflow to see:
- Which examples failed which judges
- The judge's reasoning for each score
- Overall pass rates per judge

> Before moving to Step 5, make sure you can see at least one failing score.
> That's your baseline. You're about to improve it.

---

## Step 5 — Fix and Verify (20 min)

**Goal:** Make targeted changes, redeploy, and prove the scores improve.

### 5a. What to Fix

Based on your eval results, pick the most impactful fix. Common options:

**Fix 1: System prompt guardrails (fastest)**
Add explicit instructions to the agent's system prompt to address the issues found:

```python
SYSTEM_PROMPT = """You are a helpful customer support agent for TechMart, a technology retailer.
You help customers with product questions, order lookups, and return requests.

You have four tools:
- product_lookup: semantic search over product documentation
- get_product_details: get inventory and pricing for a specific product
- get_order_status: look up an order by order ID
- get_return_policy: retrieve the return and warranty policy

IMPORTANT GUIDELINES:
1. FACTUAL ACCURACY: Only state facts you found in the retrieved documentation.
   If a product doc mentions a warranty period, verify it makes sense in context.
   Our standard warranty is 1 year unless a specific product page says otherwise.
   Never claim a warranty longer than what the official policy states.

2. TONE: Be professional, empathetic, and calm. Never use phrases like "act now",
   "limited inventory", "don't miss out", or "prices will increase". These are
   inappropriate for customer support. When a customer is upset, acknowledge their
   concern first, then provide information.

3. PRODUCT AVAILABILITY: Before recommending a product, always call get_product_details
   to check if discontinued=true. If a product is discontinued, tell the customer it
   is no longer available and suggest alternatives.

4. RETURN POLICY: Always call get_return_policy before discussing returns.
   Our standard return window is 30 days with receipt. For requests outside this window,
   explain the policy and offer to connect them with a manager who can review exceptions.
   Do not promise refunds or returns you are not authorized to approve.
"""
```

**Fix 2: Data fix (more thorough)**
The root cause of some issues is bad data in product_docs. Fix the data:

```sql
-- Remove incorrect warranty claims added during workshop setup
UPDATE {{CATALOG}}.{{SCHEMA}}.product_docs
SET product_doc = REGEXP_REPLACE(
    product_doc,
    'All products in this category include a comprehensive 3-year manufacturer warranty[^.]+\\.',
    'Products are covered by a standard 1-year limited manufacturer warranty.'
)
WHERE product_doc LIKE '%3-year manufacturer warranty%';

-- Remove pushy sales language
UPDATE {{CATALOG}}.{{SCHEMA}}.product_docs
SET product_doc = REGEXP_REPLACE(
    product_doc,
    'DO NOT MISS OUT[^.]+\\..*?act immediately!',
    ''
)
WHERE product_doc LIKE '%DO NOT MISS OUT%';

-- Fix discontinued product docs
UPDATE {{CATALOG}}.{{SCHEMA}}.product_docs pd
JOIN {{CATALOG}}.{{SCHEMA}}.products p ON pd.product_id = p.product_id
SET pd.product_doc = REGEXP_REPLACE(
    pd.product_doc,
    'This product is currently in stock and available for immediate purchase[^.]+\\.',
    'Note: This product has been discontinued and is no longer available for purchase.'
)
WHERE p.discontinued = true;
```

After the data fix, trigger a vector search index refresh:
```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
w.vector_search_indexes.sync_index("{{CATALOG}}.{{SCHEMA}}.product_docs_vs")
```

### 5b. Redeploy

After making your changes:

```bash
# Sync updated files to workspace
databricks sync . /Workspace/Users/{{USER}}/projects/cs-agent-workshop

# Redeploy the app
databricks apps deploy cs-agent-{{USERNAME}} \
  --source-code-path /Workspace/Users/{{USER}}/projects/cs-agent-workshop

# Wait for deployment, then test
curl -X POST "https://<your-app-url>/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "What warranty comes with your headphones?"}'
```

### 5c. Re-run Evaluation

Re-run with the same dataset and judges to see improvement:

```python
# Same eval_data, same judges, new run name
with mlflow.start_run(run_name="eval_run_v2_after_fix"):
    results_v2 = mlflow.genai.evaluate(
        data=eval_data,
        scorers=[factual_accuracy, tone_quality, policy_compliance],
    )

print("Before fix:", results_v1.metrics)
print("After fix: ", results_v2.metrics)
```

> You should see pass rates improve. If they haven't, look at what the judge
> is still failing on and iterate. This is the real agent lifecycle — evaluate,
> fix, evaluate again.

---

## Hints and Code Snippets

### If vector search query returns no results
```python
# Try lower similarity threshold
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
results = w.vector_search_indexes.query_index(
    index_name="{{CATALOG}}.{{SCHEMA}}.product_docs_vs",
    columns=["product_name", "product_doc"],
    query_text="wireless headphones",
    num_results=5,
)
print(results)
```

### If UCFunctionToolkit raises permission error
```sql
-- Grant execute on functions
GRANT EXECUTE ON FUNCTION {{CATALOG}}.{{SCHEMA}}.product_lookup TO `{{USER}}`;
GRANT EXECUTE ON FUNCTION {{CATALOG}}.{{SCHEMA}}.get_product_details TO `{{USER}}`;
GRANT EXECUTE ON FUNCTION {{CATALOG}}.{{SCHEMA}}.get_order_status TO `{{USER}}`;
GRANT EXECUTE ON FUNCTION {{CATALOG}}.{{SCHEMA}}.get_return_policy TO `{{USER}}`;
```

### If app deployment fails
```bash
# Check app logs
databricks apps logs cs-agent-{{USERNAME}}

# Check if app exists
databricks apps get cs-agent-{{USERNAME}}

# If too many apps error: check with instructor for a shared app URL
```

### If MLflow tracing isn't showing up
```python
# Verify experiment exists and tracking URI is set
import mlflow
mlflow.set_tracking_uri("databricks")
exp = mlflow.get_experiment_by_name("/Users/{{USER}}/cs-agent-workshop")
print(exp)
```

### If LangGraph import fails
```bash
pip install -q databricks-langchain langgraph langchain-core
```

---

## What You Built

By the end of this workshop, you've done something that usually takes weeks in production:

1. **Connected a real data source** — Unity Catalog tables as agent tools via UC Functions
2. **Deployed a live AI app** — running on Databricks Apps, queryable via HTTP
3. **Discovered quality issues** — through observation and scripted testing
4. **Quantified those issues** — with MLflow traces and LLM-as-judge evaluation
5. **Fixed them** — with either prompt engineering or data fixes
6. **Proved improvement** — by comparing eval scores before and after

This is the agent hardening loop. It's not a one-time thing — it's the process
you run every time you change your agent, your data, or your policy.

---

*Workshop version: 1.0 | Databricks AI Platform | {{CATALOG}}.{{SCHEMA}}*
