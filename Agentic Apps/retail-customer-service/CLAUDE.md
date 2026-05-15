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
                  — shared PostgreSQL instance for all participants
  Lakebase schema: {{LAKEBASE_SCHEMA}}
                  — YOUR isolated Postgres schema within the instance.
                    Each participant has their own schema so memory tables
                    don't collide. Droppable per-user after the workshop.
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

Tables to explore: products, product_docs, orders, policies, and the
product_docs_vs vector search index. Note: customer info (email, shipping
address) is embedded in the orders table — there is no separate customers table.

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

**Sample prompts for Claude:**
- "Help me understand what's in the shared schema — what tables are there
  and what do they contain?"
- "Some products have discontinued = true. Help me write a query to see
  their product docs side by side."
- "The return policy seems vague about exceptions. What questions might a
  customer ask that this doesn't clearly answer?"

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
product lookup, order status, and return/warranty policy. These live in the
participant's personal schema so they don't collide with others.

**What to tell Claude**
- Your catalog and schema: {{CATALOG}}.{{SCHEMA}}
- Where the data lives: {{CATALOG}}.shared
- What tables exist: products, product_docs, orders, policies
- What each function should do (in plain language — Claude writes the SQL)
  - product_lookup: semantic search over product docs using the vector search index
  - get_product_details: structured lookup for a specific product by name, include discontinued status
  - get_order_status: look up an order (customer email and shipping address are columns in orders)
  - get_return_policy: fetch the return and warranty policies from the policies table

**Sample prompt**
  Create 4 UC Functions in {{CATALOG}}.{{SCHEMA}} as tools for a customer
  service agent. The shared data is in {{CATALOG}}.shared and has these tables:
  products, product_docs, orders, policies. There's also a vector search
  index at {{CATALOG}}.shared.product_docs_vs.

  I need:
  1. product_lookup — semantic search over product docs using the VS index
  2. get_product_details — look up a product by name, include discontinued status
  3. get_order_status — look up an order from the orders table (customer email
     and shipping address are columns in orders)
  4. get_return_policy — fetch the return and warranty policies

  Create all 4 in {{CATALOG}}.{{SCHEMA}}.

**What to look at**
After Claude creates the functions, go to:
Catalog > {{CATALOG}} > {{SCHEMA}} — you should see all 4 functions listed.
Click each function to see its signature and SQL body.

---

#### Step 2b — Write the Agent Code

**What they're building**
A LangGraph customer service agent that uses those UC Functions as MCP tools,
Lakebase for conversation memory, and MLflow for tracing. The agent is
scaffolded from the Databricks agent-langgraph-advanced app template.

**What to tell Claude**
- Use the Databricks app-templates repo (https://github.com/databricks/app-templates)
  and choose the langgraph-advanced agent template
- Use the latest OpenAI GPT model available in Databricks
- Use my 4 UC Functions as tools via DatabricksMCPServer
- The UC Functions are in {{CATALOG}}.{{SCHEMA}}
- The agent is a customer service assistant for TechMart (electronics retailer)
- Keep the system prompt minimal for now — no guardrails. You want to find
  problems naturally in Step 3.
- It should be deployable as a Databricks App

**Architecture Claude will wire up:**
- UC Functions become MCP tools via DatabricksMCPServer / DatabricksMultiServerMCPClient
- create_react_agent() wires model + tools + system prompt
- LongRunningAgentServer (enable_chat_proxy=True) serves the agent with a built-in
  chat UI at / and the API at /invocations
- lakebase_context() manages the AsyncCheckpointSaver + store for per-conversation
  memory, isolated by thread_id and per-user Lakebase schema
- MLflow tracing via mlflow.langchain.autolog()
- databricks.yml declares the bundle: app, experiment, postgres (Lakebase) resource

**Sample prompt**
  Build me a customer service agent for TechMart, an electronics retailer.
  Use the Databricks app-templates repo (https://github.com/databricks/app-templates)
  and choose the langgraph-advanced agent template.

  Requirements:
  - Use the latest OpenAI GPT model available in Databricks
  - Use my 4 UC Functions in {{CATALOG}}.{{SCHEMA}} as tools via DatabricksMCPServer
  - Use Lakebase for conversation memory, isolating conversations by thread_id
  - Include MLflow tracing, experiment at /Users/{{USER}}/cs-agent-workshop
  - Keep the system prompt minimal for now — no guardrails. I want to find
    problems naturally in Step 3.
  - The app should be deployable as a Databricks App

**What to look at**
Claude will generate the agent code files. Review the structure — especially
the system prompt (where agent behavior is defined) and the databricks.yml
bundle config. You will improve the system prompt in Step 5.

---

#### Step 2c — Deploy

**What they're building**
A running Databricks App accessible via a public URL, deployed from the
agent code using Databricks Asset Bundles.

**Sample prompt**
  Deploy my Databricks App as cs-agent-{{USERNAME}} so it doesn't conflict
  with other participants. Validate the bundle, deploy, start the app, and
  give me the URL when it's running.

**What to look at**
Left nav > Apps. Find cs-agent-{{USERNAME}}. Check that status is Running
and note the app URL — you will use it in Step 3.

**Common sticking points:**

  Problem | What to tell Claude
  --------|--------------------
  Permissions error on MCP tool call | "Grant execute on my UC functions in
    {{CATALOG}}.{{SCHEMA}} to the app service principal"
  Bundle deploy failed | "Run bundle validate and tell me what the errors are"
  App won't start | "Check the app logs in the Logs tab and tell me what
    the error is"
  AsyncCheckpointSaver warning | Expected if Lakebase isn't configured —
    the agent falls back to stateless gracefully

---

### Step 3 — Break the Agent

**What they're building**
An understanding of where the agent fails — by chatting with it directly.
These failures become the eval dataset in Step 4. Write down exact quotes —
you'll use them to build judges.

Open the app URL from Step 2c and start chatting.

**Category A — Normal (should work fine)**
- "Can you help me find a laptop for college use?"
- "What are your shipping options?"

**Category B — Discontinued Products**
- "I'm looking for the TechMart ProBook X500 laptop. Is it still available?"
- "Can I order the AudioMax Pro headphones? I saw them last year."

What to watch for: Does the agent say the product is "available" or "in
stock"? Check whether it's actually discontinued in the data from Step 1.

**Category C — Warranty Questions**
- "What warranty comes with your headphones? How many years is it covered?"
- "I'm comparing your warranty to a competitor — how many years do you cover?"

What to watch for: What warranty duration does the agent claim? How does
that compare to the official policy you saw in Step 1?

**Category D — Recommendation Requests**
- "I'm not sure which laptop to buy. What do you recommend?"
- "What's your best product under $500?"

What to watch for: Does the agent use any phrases that feel pushy or
inappropriate for a support context? Note the exact words.

**Category E — Return Requests**
- "I bought a laptop 3 months ago and I want to return it."
- "I've been a loyal customer for 10 years. Can you make an exception on
  my return?"

What to watch for: Does the agent approve the return, explain the policy,
or offer to escalate? Which is the correct behavior?

**Do not tell participants which products are discontinued or what the
warranty claim is.** Let them discover it through conversation.

**Where to look in Databricks:**
Left nav > Apps > cs-agent-{{USERNAME}} > click the app URL to open the
chat interface. Each conversation is automatically traced — go to
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
A set of scripted conversations covering all 4 issue categories, run against
the deployed app to populate the MLflow experiment with realistic traces.

**Sample prompt**
  I want to generate a baseline set of conversation traces against my deployed
  agent so I can evaluate whether it handles realistic customer scenarios well.
  Use MLflow's ConversationSimulator (mlflow.genai.simulators.ConversationSimulator)
  to drive multi-turn dialogues. Log all traces to my MLflow experiment at
  /Users/{{USER}}/cs-agent-workshop.

  Generate 20 conversations, 5 each, covering four customer-experience categories:

  1. Product availability questions — customers asking about specific products,
     browsing recommendations, asking what's currently for sale, particularly
     concerned with how it handles discontinued products
  2. Product specifications and policies — customers asking warranty length,
     support terms, what's covered
  3. Recommendation requests across price/use-case — customers asking "what
     should I buy" for various budgets and situations, checking for tone,
     pushiness, and user friendliness
  4. Returns and post-purchase support — customers asking to return or exchange
     items at various points after purchase

  For each test case, define:
  - goal — what the simulated customer wants from the conversation
  - persona — who they are and what they care about
  - simulation_guidelines — natural phrasing, when to wrap up (cap at 4 turns)
  - expectations.expected_resolution — what a correct, well-behaved customer
    service interaction would look like here

  Use any of the latest GPT or Anthropic models as the simulator's user_model.
  Tag the run baseline_simulator_v1 so the next step can find the traces.
  Each conversation should use a distinct thread_id so AsyncCheckpointSaver
  keeps multi-turn history per case.

**What to look at**
Left nav > Experiments > /Users/{{USER}}/cs-agent-workshop. Click individual
traces to see the full conversation, tool calls, and latency breakdown.

---

#### Step 4b — Curate an Eval Dataset

**What they're building**
A focused dataset of input/output pairs that capture the quality issues —
the "ground truth" for what a correct response looks like. Claude searches
the traces and builds this dataset.

**Sample prompt**
  Search the traces in my MLflow experiment /Users/{{USER}}/cs-agent-workshop
  and build an eval dataset capturing these quality issues I found in Step 3:
  [describe what you found — e.g. "agent recommended a discontinued product
  and said it was in stock", "agent claimed 3-year warranty", "agent used
  phrases like ACT NOW", "agent approved a return for a purchase made 3
  months ago"].

  Each row should have:
  - case_id
  - category — one of: product_availability, product_specs_policies,
    recommendations, returns_support
  - goal, persona, guidelines
  - expected_resolution — the customer service standard for this scenario
  - first_user_message — what the simulated customer opened with
  - final_agent_response — what the agent actually said by the end
  - full_transcript — the whole conversation as JSON
  - trace_id — for drilling back into the MLflow trace

  Save the dataset to {{CATALOG}}.{{SCHEMA}}.eval_dataset and register it
  as an MLflow eval dataset linked to the experiment.

**What to look at**
Catalog > {{CATALOG}} > {{SCHEMA}} > eval_dataset. Use the Sample Data tab
to verify the examples look right.

---

#### Step 4c — Write the Judges

**What they're building**
Guidelines scorers — LLM-as-judge evaluators that score each example
pass/fail based on a natural-language rule. One judge per issue type.
Claude writes the judge language based on participant description.

**Sample prompt**
  Write Guidelines scorers for the quality issues I found in my TechMart agent:

  1. Discontinued product accuracy — agent should never recommend a product
     that is discontinued. If discontinued, it should say so and suggest
     alternatives.

  2. Warranty duration accuracy — agent should only state warranty durations
     from retrieved product docs. Our standard is 1 year. If uncertain, the
     agent should operate off of the standard.

  3. Tone quality — agent should be professional and helpful, never use
     high-pressure language like "ACT NOW", "limited time", or "limited
     inventory".

  4. Policy compliance — agent must follow the return policy below.
     "Customers may return any product for any reason within 1 year of
     purchase for a full refund or exchange. No receipt required. Items
     must be in original or gently used condition. Contact support to
     initiate a return."
     Fail if the agent violates this in any way.

**A good judge is specific enough that a model can reliably decide pass/fail.**
Too vague: "The response is good."
Better: "The response only states warranty durations found in retrieved docs.
Our standard is 1 year. If uncertain, the agent operates off of the standard."

**What to look at**
Review the scorer definitions Claude shows you. If a judge feels vague, ask
Claude to make it more specific. Judges that pass everything are not strict
enough — you need a failing baseline to improve from.

---

#### Step 4d — Run the Evaluation

**What they're building**
An MLflow evaluation run that scores every example in the dataset against
every judge, producing a pass-rate per judge and per-example reasoning.
This is the baseline to beat in Step 5.

**Sample prompt**
  Run an evaluation using the eval dataset in {{CATALOG}}.{{SCHEMA}}.eval_dataset
  and the judges we defined. Log to my MLflow experiment
  /Users/{{USER}}/cs-agent-workshop. Name the run eval_run_v1_baseline.
  Use mlflow.genai.evaluate().

**What to look at**
Left nav > Experiments > /Users/{{USER}}/cs-agent-workshop > find the run
eval_run_v1_baseline. Open it to see:
- Per-judge pass rates in the Metrics tab
- Per-example scores and judge reasoning in the Artifacts tab
- The goal: at least one judge should be failing. If everything passes,
  the judges are not strict enough — ask Claude to tighten the language.

---

### Step 5 — Fix and Verify

**What they're building**
A targeted improvement that moves the failing eval scores upward. Claude
makes the fix and redeploys; participants run the eval again and compare.

**Option A — System Prompt Guardrails (your path, ~10 min)**
Add explicit rules to the agent system prompt so it knows what correct
behavior looks like. Claude edits the code and redeploys — no data sync
needed.

**Sample prompt**
  Fix the agent by adding guardrails to the system prompt that address
  the issues we found:
  - Before recommending any product, always check discontinued status and
    never recommend discontinued products
  - For any warranty or return question, always call get_return_policy()
    and ground your answer in its result. Treat product descriptions as
    informational only — they may contain marketing language, but the
    policies table is the source of truth for warranty terms and returns.
  - Use professional, empathetic language — never use phrases like "ACT NOW"
    or "limited inventory"
  - For return requests, always look up the return policy first; explain
    the policy and say you can't make exceptions.

  After making the changes, redeploy the app as cs-agent-{{USERNAME}}.

**Option B — Data Fix (instructor demonstration)**
The root cause of several issues is bad data in the product_docs table —
incorrect warranty claims, pushy language, and misleading availability text
for discontinued products. A proper production fix would address the data
at the source, not just work around it in the prompt.

Your instructor will demonstrate this live. Watch for:
- How the SQL UPDATE targets specific patterns rather than rewriting entire docs
- Why the vector search index needs to be re-synced after a data change
- How a data fix and prompt fix together close different failure modes

This is an instructor demonstration — not a step you run yourself — because
all participants share the same underlying data tables.

**After Option A (and after the instructor demo if time allows):**

**Sample prompt**
  Re-run the evaluation using the same dataset and judges. Name this run
  eval_run_v2_after_fix. Log to /Users/{{USER}}/cs-agent-workshop.

**What to look at**
Left nav > Experiments > /Users/{{USER}}/cs-agent-workshop. Select both runs
(eval_run_v1_baseline and eval_run_v2_after_fix) and click Compare. Pass
rates on the affected judges should be higher.

If scores didn't improve: ask Claude to look at the judge reasoning for
still-failing examples. "The warranty judge is still failing — the reasoning
says the agent cited 3 years. What could explain that after the prompt change?"

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

Step 5 is satisfying — seeing scores improve is the payoff. Make sure
every participant gets to see their before/after score comparison before
they close their laptops.
