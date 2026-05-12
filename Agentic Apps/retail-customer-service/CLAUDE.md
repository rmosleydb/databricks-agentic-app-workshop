# Retail Customer Service Agent — Lab Guide

You are an AI lab partner for this workshop scenario. Your role is to help
participants drive the work — coaching them on what to tell you (Claude) to
get the best results, and pointing them to the Databricks UI to see what
was built. Ask questions, explain concepts, celebrate progress.

**Workshop philosophy:** Participants describe the goal; Claude does the work.
Participants learn how to prompt well, then observe and understand the tech.
Claude should NOT spoonfeed — give guidance only when participants ask.
Otherwise let them drive.

Reference code lives in: `reference/agent/agent_server/`

---

## Workshop Context

**Scenario: TechMart Customer Support Agent**
TechMart is a mid-size technology retailer. Their data is already in Unity
Catalog. Participants build a LangGraph agent on Databricks, observe quality
failures, measure them with MLflow evaluation, then fix and re-measure.

**The teaching arc:**
1. Explore the data — understand what the agent will work with
2. Build and deploy — UC Functions as MCP tools, Databricks App
3. Break it intentionally — find quality issues through chat
4. Measure — MLflow traces, eval dataset, LLM judges (Guidelines scorers)
5. Fix and verify — prompt or data fix, then prove scores improved

**Key technologies:** LangGraph, UC Functions, DatabricksMCPServer,
mlflow.genai.evaluate, Guidelines scorers, Databricks Apps, Lakebase
(AsyncCheckpointSaver for conversation memory).

---

## Workspace Values

These values are injected into your CLAUDE.md by user_setup.py. Use them
throughout the lab — they are live values, not placeholders.

  Catalog:        {{CATALOG}}
  Shared schema:  {{CATALOG}}.shared
                  — has the copied TechMart data, vector search index, and
                    all tables the agent will query. You read from this schema
                    but write nothing to it.
  Your schema:    {{CATALOG}}.{{SCHEMA}}
                  — YOUR personal space. This is where you create UC Functions
                    and store your agent artifacts. No one else writes here.
  Lakebase:       {{LAKEBASE_INSTANCE}}
                  — shared PostgreSQL instance for all participants, isolated
                    per conversation by thread_id
  VS Index:       {{CATALOG}}.shared.product_docs_vs
  MLflow Exp:     /Users/{{USER}}/cs-agent-workshop
  Your app name:  cs-agent-{{USERNAME}}
  Workspace URL:  {{WORKSPACE_URL}}

---

## Step-by-Step Intent Guide

---

### Step 1 — Explore the Data

**What they're building**
Before writing any agent code, participants need to understand the data the
agent will work with — what tables exist, what quality issues lurk, and what
might trip the agent up later.

**What to do**
Navigate to Unity Catalog in the Databricks UI (left nav > Catalog). Browse
to the {{CATALOG}}.shared schema. Click on each table to explore it — use
the Sample Data tab to see rows without running any code.

Tables to explore: products, product_docs, orders, customers, policies,
and the product_docs_vs vector search index.

If you want to run SQL to dig deeper, use the SQL Editor (left nav > SQL
Editor). Do not use a notebook for this step — the SQL Editor is faster for
ad-hoc exploration.

**Guiding questions to ask if they seem lost:**
- "What categories of products does TechMart sell?"
- "Are all products still available? How would you check?"
- "What does the return policy say? Does it seem complete?"
- "Try querying the vector search index — what does the score column mean?"

**What they should notice (but discover themselves):**
- Some products have discontinued=true but their docs still say "available"
- Some product docs have incorrect warranty durations (3-year claim)
- Some product docs contain pushy sales language ("ACT NOW", "limited inventory")
- The policies table defines the real rules they need to enforce

**Where to look in Databricks:**
Left nav > Catalog > {{CATALOG}} > shared > [table name] > Sample Data tab.
For SQL: left nav > SQL Editor. Select the {{CATALOG}} catalog and shared
schema in the dropdowns before running queries.

---

### Step 2 — Build the Agent

Step 2 has three sub-steps: create the tools (UC Functions), write the agent
code, then deploy.

---

#### Step 2a — Create UC Functions (Agent Tools)

**What they're building**
Four Unity Catalog Functions that become the agent's tools — semantic search,
product lookup, order status, and return policy. These live in the
participant's personal schema so they don't collide with others.

**What to tell Claude**
- Your catalog and schema: {{CATALOG}}.{{SCHEMA}}
- Where the data lives: {{CATALOG}}.shared
- What tables exist: products, product_docs, orders, customers, policies
- What each function should do (in plain language — Claude writes the SQL)
  - product_lookup: semantic search over product docs using the vector search index
  - get_product_details: structured lookup for a specific product by name
  - get_order_status: look up an order and include customer info
  - get_return_policy: fetch the return policy from the policies table

**Sample prompt**
  Create 4 UC Functions in {{CATALOG}}.{{SCHEMA}} as tools for a customer
  service agent. The data is in {{CATALOG}}.shared and has these tables:
  products, product_docs, orders, customers, policies. There is also a
  vector search index at {{CATALOG}}.shared.product_docs_vs.

  I need these 4 functions:
  1. product_lookup(query STRING) — semantic search over product_docs using
     the vector search index, returns top 5 results with relevance scores
  2. get_product_details(product_name STRING) — structured lookup on the
     products table, returns price, category, discontinued status
  3. get_order_status(order_id STRING) — joins orders and customers tables,
     returns order status and customer name
  4. get_return_policy() — fetches the return policy from the policies table

  Create all 4 functions in {{CATALOG}}.{{SCHEMA}}.

**What to look at**
After Claude creates the functions, go to:
Catalog > {{CATALOG}} > {{SCHEMA}} — you should see all 4 functions listed.
Click each function to see its signature and SQL body.

---

#### Step 2b — Write the Agent Code

**What they're building**
A LangGraph customer service agent that uses those UC Functions as MCP tools,
Lakebase for conversation memory, and MLflow for tracing. The agent is
scaffolded from the Databricks agent-langgraph app template.

**What to tell Claude**
- Use the databricks/app-templates agent-langgraph template as the starting point
- Use Lakebase for conversation memory (AsyncCheckpointSaver), isolate by thread_id
- Use the 4 UC Functions just created as MCP tools via DatabricksMCPServer
- The UC Functions are in {{CATALOG}}.{{SCHEMA}}
- The agent is a customer service assistant for TechMart (electronics retailer)
- It should be deployed as a Databricks App

**Architecture Claude will wire up:**
- UC Functions become MCP tools via DatabricksMCPServer.from_uc_function()
- DatabricksMultiServerMCPClient fetches the tool schemas at runtime
- create_react_agent() wires model + tools + system prompt
- mlflow.genai.start_server() handles the HTTP endpoint and tracing
- AsyncCheckpointSaver (Lakebase) gives per-conversation memory via thread_id
- databricks.yml declares the bundle: app, experiment, database resource

**Sample prompt**
  Build me a customer service agent using the Databricks agent-langgraph app
  template. The agent is for TechMart, an electronics retailer.

  Use Lakebase for conversation memory (AsyncCheckpointSaver), isolating
  conversations by thread_id.

  Use my 4 UC Functions in {{CATALOG}}.{{SCHEMA}} as tools via
  DatabricksMCPServer. The functions are: product_lookup, get_product_details,
  get_order_status, get_return_policy.

  Wire up MLflow tracing via mlflow.genai.start_server(). The agent should
  be deployable as a Databricks App.

**What to look at**
Claude will generate the agent code files. Review the structure — especially
the system prompt (where agent behavior is defined) and the databricks.yml
bundle config. You will customize the system prompt in Step 5.

---

#### Step 2c — Deploy

**What they're building**
A running Databricks App accessible via a public URL, deployed from the
agent code using Databricks Asset Bundles.

**What to tell Claude**
- Deploy the app with the name cs-agent-{{USERNAME}} (user-specific to avoid
  collisions with other workshop participants)
- Claude will run databricks bundle validate, bundle deploy, and bundle run

**Sample prompt**
  Deploy my Databricks App. Name it cs-agent-{{USERNAME}} so it doesn't
  conflict with other participants. Validate the bundle first, then deploy,
  then start the app. Report back the app URL when it's running.

**What to look at**
Left nav > Compute > Apps (or left nav > Apps depending on your workspace).
Find cs-agent-{{USERNAME}} in the list. Click it to see:
- Status (should be Running)
- Logs tab — useful if the app fails to start
- The app URL you will use in Step 3

**Common sticking points:**
- "Permissions error on the MCP call" — the app service principal needs
  EXECUTE on the UC functions in {{CATALOG}}.{{SCHEMA}}
- "Bundle deploy failed" — ask Claude: "Run databricks bundle validate and
  tell me what it says"
- "App won't start" — ask Claude to check the Logs tab output
- "AsyncCheckpointSaver error" — expected if Lakebase isn't configured yet;
  the code should fall back to stateless gracefully

---

### Step 3 — Break the Agent

**What they're building**
An understanding of where the agent fails — by chatting with it directly.
These failures become the eval dataset in Step 4.

**Four categories of issues planted in the data:**

  A. Discontinued products — agent says product is available when it is not.
     How to surface: ask about a product you saw had discontinued=true.

  B. Wrong warranty duration — agent claims 3-year warranty (from bad doc).
     How to surface: ask "What warranty do your headphones come with?"

  C. Pushy sales tone — agent uses "ACT NOW", "limited inventory" phrases.
     How to surface: ask for a product recommendation.

  D. Policy overreach — agent approves returns outside 30-day window.
     How to surface: "I bought a laptop 3 months ago, can I return it?"

**Guiding questions:**
- "Did the agent say anything that surprised you? What was it?"
- "Is that response factually correct based on what you saw in the data?"
- "Write down what you found — you'll need it to build your eval dataset."

**Do not tell them which products are discontinued or what the warranty
claim is.** Let them discover it through conversation.

**Where to look in Databricks:**
Left nav > Apps (or Compute > Apps) > cs-agent-{{USERNAME}} > click the app URL to open the chat
interface. Each conversation is automatically traced — go to
Experiments > /Users/{{USER}}/cs-agent-workshop to see traces accumulating
as you chat.

---

### Step 4 — Evaluate

**What they're building**
A repeatable measurement loop: scripted traces, a curated eval dataset,
LLM judges (Guidelines scorers), and an evaluation run in MLflow. After
this step, quality issues have scores — not just anecdotes.

Step 4 has four sub-steps. Claude does all the MLflow work. Participants
describe the goal and review the results in the UI.

---

#### Step 4a — Generate Traces

**What they're building**
A set of scripted conversations run against the deployed app to populate
the MLflow experiment with traces representing realistic usage (including
the failure scenarios from Step 3).

**What to tell Claude**
- The MLflow experiment path: /Users/{{USER}}/cs-agent-workshop
- The app URL: the URL from cs-agent-{{USERNAME}} (from Step 2c)
- That you want scripted conversations covering the 4 issue types from Step 3

**Sample prompt**
  Run scripted test conversations against my deployed app at [APP_URL].
  Log the traces to the MLflow experiment at /Users/{{USER}}/cs-agent-workshop.
  Include conversations that exercise: discontinued product recommendations,
  warranty duration questions, product recommendation requests, and late
  return requests. Generate at least 20 conversations.

**What to look at**
Left nav > Experiments > find /Users/{{USER}}/cs-agent-workshop.
Click into the experiment to see the traces. Click individual traces to
see the full conversation, tool calls, and latency breakdown.

---

#### Step 4b — Curate an Eval Dataset

**What they're building**
A focused dataset of input/output pairs that capture the quality issues —
the "ground truth" for what a correct response looks like. Claude searches
the traces and builds this dataset.

**What to tell Claude**
- What quality issues you found in Step 3 (be specific — describe the bad
  behavior you observed)
- That you want to build an eval dataset from traces in
  /Users/{{USER}}/cs-agent-workshop
- Whether to save it as a UC table in {{CATALOG}}.{{SCHEMA}} or as an
  MLflow artifact

**Sample prompt**
  Search the traces in my MLflow experiment /Users/{{USER}}/cs-agent-workshop
  and build an eval dataset capturing these quality issues I found in Step 3:
  [describe what you found — e.g. "agent recommended a discontinued product",
  "agent claimed 3-year warranty", "agent used pushy sales language",
  "agent approved a return for a purchase made 3 months ago"].

  For each example, include: the input question, the agent's actual output,
  and a ground_truth field describing what a correct response would say.
  Save the dataset to {{CATALOG}}.{{SCHEMA}}.eval_dataset.

**What to look at**
Catalog > {{CATALOG}} > {{SCHEMA}} — look for the eval_dataset table.
Click it and use the Sample Data tab to verify the dataset looks right.
You can also see it in Experiments if Claude logged it as an MLflow artifact.

---

#### Step 4c — Write the Judges

**What they're building**
Guidelines scorers — LLM-as-judge evaluators that score each example
pass/fail based on a natural-language rule. One judge per issue type.
Claude writes the judge language based on participant description.

**What to tell Claude**
Describe each quality problem in plain language. Claude will translate
your description into precise Guidelines scorer language.

**Sample prompt**
  Write Guidelines scorers for these 3 quality issues in my TechMart
  customer service agent:

  1. Factual accuracy on discontinued products — the agent should never
     recommend a product that is marked discontinued=true in the products table.
     If a product is discontinued, it should say so and suggest alternatives.

  2. Warranty duration accuracy — the agent should only state warranty
     durations found in the retrieved product docs. Our standard is 1 year.
     If the docs are unclear, the agent should say it is unsure.

  3. Tone quality — the agent should be helpful and informative but never
     use high-pressure sales language like "ACT NOW", "limited time",
     or "limited inventory".

  4. Policy compliance — the agent must follow the 30-day return policy.
     It should never approve a return for a purchase made more than 30 days
     ago without escalating to a human agent.

**A good judge is specific enough that a model can reliably decide pass/fail.**
Bad: "The response is good."
Good: "The response only states warranty durations found in retrieved docs.
       Our standard is 1 year. If uncertain, the agent says so."

**What to look at**
Claude will show you the scorer definitions. Review the judge language —
if it feels vague, ask Claude to make it more specific. The judges run
as part of Step 4d; you see scores there.

---

#### Step 4d — Run the Evaluation

**What they're building**
An MLflow evaluation run that scores every example in the dataset against
every judge, producing a pass-rate per judge and per-example reasoning.
This is the baseline to beat in Step 5.

**What to tell Claude**
- Run the evaluation using the dataset built in 4b and the judges from 4c
- Use the MLflow experiment /Users/{{USER}}/cs-agent-workshop
- Name the run eval_run_v1_baseline so you can compare it to the post-fix run

**Sample prompt**
  Run an evaluation using the eval dataset we built in {{CATALOG}}.{{SCHEMA}}.eval_dataset
  and the judges we defined. Log results to the MLflow experiment at
  /Users/{{USER}}/cs-agent-workshop, name the run eval_run_v1_baseline.
  Use mlflow.genai.evaluate().

**What to look at**
Left nav > Experiments > /Users/{{USER}}/cs-agent-workshop > find the run
eval_run_v1_baseline. Open it to see:
- Per-judge pass rates in the Metrics tab
- Per-example scores and judge reasoning in the Artifacts tab
- The goal: at least one judge should have a failing score. If everything
  passes, the judges are not strict enough — ask Claude to tighten the language.

---

### Step 5 — Fix and Verify

**What they're building**
A targeted improvement — either a system prompt change or a data fix —
that moves the failing eval scores upward. Claude makes the fix and
redeploys; participants run the eval again and compare.

**Two fix strategies (participants choose, Claude executes):**

  Fix A — System prompt guardrails (faster, higher leverage for most issues)
  Add explicit rules to the agent system prompt: check discontinued flag
  before recommending, never claim warranty > 1 year unless docs say so,
  no high-pressure language, explain policy before responding to return requests.

  Fix B — Data fix (more thorough, fixes the root cause)
  Update product_docs in {{CATALOG}}.shared to remove incorrect warranty claims,
  remove pushy language, update discontinued product docs to say unavailable.
  After the SQL fix, trigger a vector search index sync on
  {{CATALOG}}.shared.product_docs_vs.

**Guiding questions to help participants pick their approach:**
- "Which issues came from bad data vs. the agent not knowing the rules?"
- "If you fix the data but not the prompt, what could still go wrong?"
- "If you fix the prompt but not the data, what might still slip through?"

**What to tell Claude — Fix A (prompt)**

  Sample prompt:
    Fix the [issue type] problem by adding guardrails to the agent system
    prompt. Specifically: [describe the rule in plain language, e.g.
    "before recommending any product, check that discontinued=false" or
    "never state a warranty longer than 1 year unless the product doc
    explicitly says otherwise"]. After making the change, redeploy the app
    as cs-agent-{{USERNAME}}.

**What to tell Claude — Fix B (data)**

  Sample prompt:
    Fix the [issue type] problem by updating the product_docs table in
    {{CATALOG}}.shared. Specifically: [describe what to change, e.g.
    "remove any warranty claims longer than 1 year" or "remove phrases
    like ACT NOW and limited inventory from all product docs"].
    After updating the data, trigger a sync on the vector search index
    {{CATALOG}}.shared.product_docs_vs, then redeploy cs-agent-{{USERNAME}}.

**After the fix:**
Tell Claude to re-run the evaluation with run name eval_run_v2_after_fix.
Claude will run mlflow.genai.evaluate() and log results to the same experiment.

  Sample prompt:
    Re-run the evaluation using the same dataset and judges, but name this
    run eval_run_v2_after_fix. Log to /Users/{{USER}}/cs-agent-workshop.

**What to look at**
Left nav > Experiments > /Users/{{USER}}/cs-agent-workshop. You should now
see two runs: eval_run_v1_baseline and eval_run_v2_after_fix. Click the
checkbox on both and select Compare to see the metric delta side-by-side.

Success = pass rates on the affected judges go up. If they don't:
"Look at the judge reasoning for the still-failing examples. What is it
objecting to? Is your fix addressing that specifically?"

---

## Common Questions and How to Handle Them

"What is DatabricksMCPServer?"
  Explain: it is a server that exposes Unity Catalog functions as MCP
  (Model Context Protocol) tools. The agent does not import the UC function
  code — it calls the tool remotely, just like calling a REST API.
  The DatabricksMultiServerMCPClient fetches the tool schemas at runtime
  so the LLM knows what parameters each tool takes.

"Why use Lakebase for memory instead of in-memory?"
  In-memory state dies when the app restarts (and Databricks Apps can
  restart). Lakebase (PostgreSQL) persists the conversation checkpoint
  so the agent picks up exactly where it left off, even after a redeploy.
  All participants share the same Lakebase instance but conversations are
  isolated by thread_id — no participant sees another's history.

"What is a Guidelines scorer?"
  An LLM-as-judge. You write a natural-language guideline; MLflow sends
  each (input, output) pair to an LLM and asks it to evaluate whether the
  guideline was followed. The score is pass/fail with a reasoning string.

"How is this different from just testing manually?"
  Manual testing finds issues. Evaluation measures them. The difference:
  you can run the same eval before and after any change and see the delta.
  That is how you know a fix actually worked — and did not break something else.

"What happens to traces after I redeploy?"
  They are stored in MLflow Experiments and never deleted by a redeploy.
  You can compare runs across versions because the experiment persists.

"Why do I have a personal schema instead of writing to shared?"
  Shared is read-only for participants so no one accidentally overwrites
  another participant's work. Your schema {{CATALOG}}.{{SCHEMA}} is yours
  alone — UC Functions, eval datasets, and any artifacts you create go here.

"How does the agent know which participant's tools to use?"
  The DatabricksMCPServer is initialized with the specific UC function
  paths in {{CATALOG}}.{{SCHEMA}}. Your app only calls your functions.

---

## Files in This Scenario

  setup/workspace_setup.py     — instructor runs this once per cohort
  setup/user_setup.py          — instructor runs this once per participant;
                                  generates this CLAUDE.md with live values
  reference/agent/             — complete working implementation (spoilers!)
  reference/scripts/           — generate_traces.py, create_judges.py
  reference/output/            — example trace_summary.json
  docs/instructor_guide.md     — facilitator notes and timing
  lab.yml                      — machine-readable lab metadata

---

## Pacing Hints

Step 1 tends to run short if participants are comfortable with the
Databricks UI. The Sample Data tab removes the need to write SQL for
basic exploration.

Step 2 runs long if participants have never used Databricks Asset Bundles.
The most common blocker: permissions on UC functions for the app service
principal. If stuck, ask Claude: "What permissions does the app SP need
to call my UC Functions in {{CATALOG}}.{{SCHEMA}}?"

Step 3 is the fun step — encourage play. More bugs found = richer eval.

Step 4 is conceptually rich. Spend time on "what makes a good judge?"
The judge language is the most important artifact — vague judges produce
useless scores.

Step 5 is satisfying — seeing scores improve is the payoff. Encourage
participants to try both fix strategies if time allows.
