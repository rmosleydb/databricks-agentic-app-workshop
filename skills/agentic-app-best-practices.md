---
name: agentic-app-best-practices
description: >
  Universal best practices for building production-ready agentic applications
  on Databricks. Covers: architecture patterns (ReAct, tool use, memory),
  quality assurance (MLflow tracing, LLM judges, Guidelines scorers, eval
  datasets), deployment (Databricks Apps, Asset Bundles), and the agent
  hardening lifecycle. Applies to any LangGraph agent using UC Functions
  as tools.
  Keywords: LangGraph, agentic app, UC Functions, MCP, DatabricksMCPServer,
  mlflow.genai.evaluate, Guidelines, eval dataset, Databricks Apps, DAB,
  databricks bundle, AsyncCheckpointSaver, Lakebase, tracing, hardening,
  production, quality, judges, ReAct agent, tool calling.
---

# Agentic App Best Practices

A reference guide for building, evaluating, and hardening LangGraph agents
on Databricks. Apply these patterns when building new agents or reviewing
existing ones.

---

## Architecture Patterns

### 1. Tools: UC Functions via MCP (preferred on Databricks)

Expose Unity Catalog functions as agent tools using DatabricksMCPServer.
This pattern keeps business logic in SQL/Python UC functions (versioned,
permissioned, testable in isolation) and away from agent code.

```python
from databricks_langchain import DatabricksMCPServer, DatabricksMultiServerMCPClient

uc_mcp_server = DatabricksMCPServer.from_uc_function(
    catalog=CATALOG, schema=SCHEMA, name="my_tools",
)
uc_mcp_client = DatabricksMultiServerMCPClient([uc_mcp_server])

# At request time:
tools = await uc_mcp_client.get_tools()
agent = create_react_agent(model=model, tools=tools, prompt=SYSTEM_PROMPT)
```

Benefits:
- Tool schemas are auto-derived from UC function signatures and COMMENT fields
- Governance: GRANT EXECUTE controls who/what can call each tool
- The agent SP needs EXECUTE on each UC function individually
- No SDK imports in agent code — tool logic is in the catalog

### 2. Conversation Memory: Lakebase AsyncCheckpointSaver

Use AsyncCheckpointSaver for persistent per-conversation memory. Always
wrap in try/except so the agent runs stateless if Lakebase is unavailable
(e.g. local dev):

```python
from databricks_langchain import AsyncCheckpointSaver

checkpointer = None
config: dict = {}
try:
    checkpointer = await AsyncCheckpointSaver(instance_name=LAKEBASE).__aenter__()
    config = {"configurable": {"thread_id": thread_id}}
except Exception as e:
    log.warning("Lakebase unavailable (%s) — running stateless.", e)

runnable = agent.with_config(checkpointer=checkpointer) if checkpointer else agent
```

thread_id should come from the request context (conversation_id) so each
user session gets its own isolated history.

### 3. Server Pattern: mlflow.genai.start_server

```python
@invoke()
async def non_streaming(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    outputs = [
        event.item async for event in streaming(request)
        if event.type == "response.output_item.done"
    ]
    return ResponsesAgentResponse(output=outputs)

@stream()
async def streaming(request: ResponsesAgentRequest) -> AsyncGenerator[...]:
    messages, context = get_messages_and_context(request)
    thread_id = context.get("conversation_id", "default")
    # ... agent logic here
    async for event in process_agent_astream_events(...):
        yield event
```

mlflow.langchain.autolog() in start_server.main() captures all traces
automatically — no manual mlflow.start_run() needed in agent code.

### 4. Deployment: Databricks Asset Bundles

Always deploy via `databricks bundle deploy`, not manual app creation.
The bundle declares the app, experiment, and Lakebase database as resources
so dependencies are wired automatically:

```yaml
resources:
  experiments:
    my_experiment:
      name: /Users/${workspace.current_user.userName}/my-agent
  apps:
    my_agent_app:
      name: "my-agent-${bundle.target}"
      source_code_path: ./
      config:
        command: ["uv", "run", "start-server"]
        env:
          - name: MLFLOW_EXPERIMENT_ID
            value_from: experiment
          - name: DATABRICKS_HOST
            value: "${workspace.host}"
      resources:
        - name: experiment
          experiment:
            experiment_id: ${resources.experiments.my_experiment.experiment_id}
            permission: CAN_MANAGE
        - name: database
          database:
            instance_name: "${LAKEBASE_INSTANCE}"
            database_name: databricks_postgres
            permission: CAN_CONNECT_AND_CREATE
```

---

## Quality Assurance Lifecycle

The agent hardening loop has four phases. Run this loop every time the
agent code, tools, data, or system prompt changes.

### Phase 1 — Trace Collection

Generate diverse conversations that exercise edge cases, not just happy
paths. The traces become your eval dataset ground truth.

Good trace categories for a customer support agent:
- Normal requests (happy path baseline)
- Requests about discontinued / unavailable products
- Policy questions (warranty, returns)
- Out-of-scope requests (should gracefully redirect)
- Ambiguous requests (should ask for clarification)
- Adversarial / jailbreak attempts

Save traces to an MLflow experiment automatically via autolog.

### Phase 2 — Eval Dataset Curation

Curate a labeled dataset from your traces. Each row needs:
  inputs:       the conversation messages sent to the agent
  outputs:      the agent's actual response
  ground_truth: what a correct response would do (not verbatim text)

```python
eval_data = pd.DataFrame([
    {
        "inputs": {"messages": [{"role": "user", "content": "..."}]},
        "outputs": {"messages": [{"role": "assistant", "content": "..."}]},
        "ground_truth": "Should explain X and offer to do Y.",
    },
    ...
])
```

Aim for 10-20 examples. Include both passing and failing cases.
Persist to Unity Catalog or MLflow artifacts so it survives redeployments.

### Phase 3 — LLM Judges (Guidelines Scorers)

Write one judge per quality dimension you care about. A good judge is:
- Specific: says exactly what behavior is expected
- Falsifiable: an LLM can reliably decide pass/fail
- Scoped: targets one concern, not multiple

```python
from mlflow.genai.scorers import Guidelines

factual_accuracy = Guidelines(
    name="factual_accuracy",
    guidelines=(
        "The response only states facts found in retrieved documents. "
        "It does not invent warranty durations, pricing, or availability. "
        "If uncertain, the agent says so rather than guessing."
    ),
)

tone_quality = Guidelines(
    name="tone_quality",
    guidelines=(
        "The response is professional and empathetic. "
        "It does not use high-pressure phrases like 'act now', 'limited inventory', "
        "or 'don't miss out'. Tone is calm and supportive."
    ),
)

policy_compliance = Guidelines(
    name="policy_compliance",
    guidelines=(
        "The response accurately represents company policy. "
        "It does not approve exceptions outside policy without noting that "
        "a manager must review. If out-of-policy, agent explains and offers to escalate."
    ),
)
```

### Phase 4 — Evaluate and Compare

```python
import mlflow
import mlflow.genai

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment("/Users/{user}/my-agent")

with mlflow.start_run(run_name="eval_v1_baseline"):
    results_v1 = mlflow.genai.evaluate(
        data=eval_data,
        scorers=[factual_accuracy, tone_quality, policy_compliance],
    )

# ... make your fix ...

with mlflow.start_run(run_name="eval_v2_after_fix"):
    results_v2 = mlflow.genai.evaluate(
        data=eval_data,
        scorers=[factual_accuracy, tone_quality, policy_compliance],
    )

print("Before:", results_v1.metrics)
print("After: ", results_v2.metrics)
```

Open both runs in the MLflow UI to compare per-example scores and judge
reasoning. A fix is validated when the targeted judges improve and
unrelated judges do not regress.

---

## Fix Strategies

### Prompt Engineering (fastest, appropriate for behavioral issues)

Add explicit rules to the system prompt for issues caused by the model not
knowing the business rules — not bad data:
- "Always call get_product_details before recommending a product to check
  if discontinued=true. If discontinued, tell the customer and suggest alternatives."
- "Never claim a warranty longer than the official policy states."
- "For return requests outside the standard window, explain the policy and
  offer to escalate. Do not approve returns you are not authorized to approve."

### Data Fix (more thorough, appropriate for bad source data)

When the issue is in the underlying data (wrong claims in product docs,
bad data in policies table), fix the data at the source and trigger a
vector search index refresh:

```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
w.vector_search_indexes.sync_index("{catalog}.{schema}.{index_name}")
```

### Combined Approach (production best practice)

Fix the data AND add prompt rules. Data fixes remove the root cause.
Prompt rules add defense-in-depth so future data quality issues cannot
cause the same class of failure.

---

## Common Pitfalls

UC function permissions:
  The app runs as its own service principal. That SP needs EXECUTE on
  each UC function individually. Databricks SQL does not support
  GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA.

  -- Get the SP client ID:
  databricks apps get {app-name} --output json | jq .service_principal_client_id
  -- Then grant per-function:
  GRANT EXECUTE ON FUNCTION {catalog}.{schema}.{fn} TO `{sp-client-id}`;

Vector search index staleness:
  After updating product_docs, the VS index does not update automatically.
  Always call sync_index() after data changes, then wait for ONLINE status
  before testing.

AsyncCheckpointSaver context manager:
  It must be used as an async context manager (__aenter__ / __aexit__).
  If you create it without entering the context, checkpointing silently
  fails. Always use the try/except fallback pattern shown above.

bundle deploy vs. manual app creation:
  Never create the app manually and also use bundle deploy — they will
  conflict. Pick one and stick to it. Bundle deploy is strongly preferred
  because it manages the experiment and database resource links.

Eval dataset quality:
  If all your judges pass, the judges are probably too lenient. Review
  the judge language and make it more specific. A baseline where nothing
  fails means you have no signal to improve on.
