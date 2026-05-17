# Adding a Custom Scenario

This guide is for AI Ambassadors and SAs who want to run the workshop with a different vertical or a customer's real use case. It covers both paths: swapping in a new industry dataset and adapting the lab for customer-owned data.

---

## 1. Two Paths

### Path A: Vertical Variant

Swap in a different industry dataset while keeping the same 5-step lab arc (build tools → build agent → explore → evaluate → fix). The structure, timing, and facilitation notes stay the same. You're replacing the story and the data.

Examples:
- **Manufacturing** — equipment maintenance assistant. Products = equipment models. Orders = service tickets. Policy = maintenance SLAs and warranty terms.
- **Healthcare** — patient support assistant. Products = care programs or medications. Orders = appointments or referrals. Policy = coverage and prior auth rules.
- **Financial services** — account support assistant. Products = financial products. Orders = transactions or cases. Policy = fee schedules and dispute resolution.

### Path B: Customer Scenario

The customer brings their own data and use case. The SA adapts the lab structure to fit the customer's data model and surfaces quality issues that are realistic for their domain. This path takes more pre-work but lands harder with the customer because the agent is built on their actual data.

---

## 2. Minimum Scaffold

Every new scenario lives under `Agentic Apps/<scenario-name>/` and needs the following files.

### Directory layout

```
Agentic Apps/<scenario-name>/
├── CLAUDE.md
├── lab.yml
├── setup/
│   ├── data/
│   │   └── *.csv
│   ├── workspace_setup.py
│   └── user_setup.py
├── reference/
│   └── agent/
│       ├── databricks.yml
│       ├── agent_server/
│       └── scripts/
└── docs/
    └── instructor_guide.md
```

### lab.yml

Required fields:

```yaml
name: <human-readable scenario name>
description: <one sentence>
duration: <e.g. "90 minutes">
difficulty: <beginner|intermediate|advanced>
vertical: <retail|manufacturing|healthcare|financial_services|custom>
owner: <your email>
last_updated: <YYYY-MM-DD>

required_resources:
  catalog: <UC catalog name>
  vector_search_endpoint: <endpoint name>
  lakebase: <postgres instance name>

steps:
  - id: step_1_tools
    name: Build the tools
    quality_issue: none
  - id: step_2_agent
    name: Build the agent
    quality_issue: none
  - id: step_3_explore
    name: Explore failure modes
    quality_issue: stale_availability
  - id: step_4_evaluate
    name: Evaluate with judges
    quality_issue: wrong_factual_claim
  - id: step_5_fix
    name: Fix and re-evaluate
    quality_issue: missing_guardrail
```

The `quality_issue` field on each step documents which defect participants are encountering or fixing at that point. Use the taxonomy from Section 3.

### CLAUDE.md (participant lab guide)

This is what participants open in their AI coding assistant. It must contain:

1. **Workshop philosophy block** — the framing paragraph that sets expectations (exploration over completion, mistakes are the point, etc.). Copy this from the retail scenario and update the domain details.

2. **No-spoilers rule** — explicit instruction that the AI assistant should not reveal quality issue root causes before the participant discovers them through evaluation. This belongs at the top of the file, before any step content.

3. **Workspace values table** — a simple Markdown table with the four values participants need:

   | Value | Setting |
   |---|---|
   | Catalog | `<catalog>` |
   | Schema | `<user-specific, set at login>` |
   | Lakebase endpoint | `<host:port>` |
   | Vector Search endpoint | `<endpoint-name>` |

4. **The story** — two to three paragraphs: who the fictional (or customer) company is, what the agent does, and what went wrong that the participant needs to find and fix. Make the story specific. Vague framing produces vague exploration.

5. **Steps 1–5** — each step needs:
   - What the participant is building or doing
   - Sample prompts they can give the AI assistant to get started
   - UI guidance for any Databricks-specific navigation (where to find VS indexes, how to open the agent playground, how to run an MLflow eval run)
   - A "what you should see" note so participants know when they're done

### setup/data/*.csv

All source data as CSV files. No external catalog dependencies. If it's not in a CSV under `setup/data/`, the scenario does not work in a fresh workspace.

Typical tables for a customer service scenario:
- `products.csv` (or `equipment.csv`, `programs.csv`, etc.) — the knowledge base that feeds Vector Search
- `orders.csv` (or `tickets.csv`, `cases.csv`) — structured lookup for order/case status
- `policies.csv` — unstructured policy text, also ingested into Vector Search

Column names should match what the UC Functions in `reference/agent/` expect. Check the function signatures before naming your columns.

### setup/workspace_setup.py

Runs once per workspace before the lab. It must:
- Load all CSVs into UC tables in the shared catalog
- Create the Vector Search endpoint and index, and wait for the index to sync
- Provision the Lakebase instance and create the schema
- Write `setup-state.json` to a known path so `user_setup.py` can read connection strings without hardcoding them

Add a `--dry-run` flag that validates prerequisites (cluster policy, node types, UC permissions) without creating resources. Instructors use this the day before.

### setup/user_setup.py

Runs once per participant at the start of the lab. It must:
- Create a per-user UC schema under the shared catalog (`<catalog>.<username>_workshop`)
- Render the CLAUDE.md template with the user's actual workspace values (catalog, schema, Lakebase host, VS endpoint name)
- Upload the rendered CLAUDE.md and a starter `app.yaml` to the user's workspace files or repo

Do not put any logic here that requires instructor-level permissions. This script runs as the participant.

### docs/instructor_guide.md

At minimum:
- Timing table (what happens in each 15-minute block)
- Facilitation notes for each step (what participants get stuck on, what to say)
- Failure modes table: what breaks, why it breaks, how to fix it during a live session

### reference/agent/

A working implementation that participants can consult after the lab or that instructors can use to demo fixes. It must:
- Deploy cleanly with `databricks bundle deploy` from the `reference/agent/` directory
- Include all four UC Functions wired up to the scenario's tables
- Be complete enough that a participant who gets stuck can diff their code against it

---

## 3. Designing the Quality Issues

The lab works because participants discover real defects through evaluation, not because they're told what's wrong. The defects need to be systematic and visible in eval scores.

### The 4-issue taxonomy

| Issue | Type | Root cause | Visible in eval? |
|---|---|---|---|
| Stale availability | data | Product/item records have incorrect availability status | Yes — availability judge scores drop for a whole category |
| Wrong factual claim | data | A field in the knowledge base has an incorrect value (price, spec, date) | Yes — factual accuracy judge flags the affected records |
| Toxic tone | data | Some records contain language that produces aggressive agent responses | Yes — tone/safety judge scores drop for those topics |
| Missing guardrail | prompt | System prompt doesn't constrain a known failure mode (e.g., agent gives medical/legal advice, makes promises it can't keep) | Yes — a custom judge checks for the constraint violation |

For each issue you include, document:
- `root_cause`: `data`, `prompt`, or `both`
- `fix_strategy`: what the participant or instructor does to fix it
- `judge`: what the MLflow eval judge is checking and what a passing score looks like

### Systematic vs. single-record bugs

A single wrong value in one row is too easy to miss and too hard to notice in aggregate scores. Design issues that affect an entire category:

- Bad: one product has the wrong price
- Good: all products in the "refurbished" category have stale availability flags

The eval dashboard needs to show a clearly lower score for the affected segment so participants can see the pattern without being told where to look.

### Option A vs. Option B

Every quality issue needs two fix paths:

- **Option A (prompt fix)** — the participant adds a clarification, constraint, or reformulation to the system prompt. This is always the participant path. It's achievable in 10 minutes and doesn't require modifying shared data.
- **Option B (data fix)** — the instructor corrects the underlying data in the shared catalog and re-syncs the VS index. This is instructor-demo-only because all participants share the same schema. Walking through it as a demo shows the full picture without breaking anyone's workspace.

Document both options in `docs/instructor_guide.md`. Put only Option A instructions in `CLAUDE.md`.

---

## 4. Adapting for a Customer's Own Data

### SA pre-work

Before the session:
1. Get a data sample from the customer — even 50–100 rows per table is enough.
2. Map the customer's data model to the 4-function template (see below).
3. Identify 2–3 natural quality issues in the real data. These are almost always present. Common ones: stale status fields, inconsistent category labels, missing policy coverage for common questions.
4. Build synthetic/anonymized CSVs that reproduce the structure and quality issues without containing real customer data.
5. Run `workspace_setup.py --dry-run` in the customer's workspace at least 24 hours before the session.

### Handling sensitive data

Never put PII or confidential business data in `setup/data/`. This includes customer names, account numbers, employee data, pricing that isn't public, and anything under NDA.

Use one of these approaches:
- **Synthetic data** — generate rows that have the same schema and quality issue patterns as the real data, but with fake values
- **Anonymized subset** — replace identifiers with codes, generalize specific values to ranges, remove free-text fields that might contain PII

The customer will understand. Explain that the lab uses representative synthetic data so the SA can commit it to the repo without data governance concerns.

### Mapping customer concepts to the 4 UC Functions

The retail scenario has four UC Functions. Map your customer's domain into these four slots:

| Function | Retail | Manufacturing | Healthcare | Financial |
|---|---|---|---|---|
| `product_lookup` (VS) | Product search by description | Equipment model search | Care program search | Product/plan search |
| `product_details` (structured) | Product specs by SKU | Equipment specs by asset ID | Program details by code | Plan details by ID |
| `order_status` (structured) | Order status by order ID | Service ticket status by ticket ID | Appointment status by referral ID | Case/transaction status by case ID |
| `policy_lookup` (VS) | Return/shipping policy | Maintenance SLA and warranty | Coverage and prior auth rules | Fee schedule and dispute policy |

If the customer's domain doesn't map cleanly — for example, they have 6 relevant entity types — consolidate. The 4-function structure is the workshop constraint, not a representation of the customer's full data model. Participants can't meaningfully explore more than 4 tools in 90 minutes.

### Rewriting CLAUDE.md for the customer's domain

The story section is where most of the rewrite effort goes. Replace:
- The company name and description
- What the agent is supposed to do
- The customer persona the agent serves
- The specific quality issues embedded in the story (without revealing root causes)

Keep:
- The workshop philosophy block (verbatim or near-verbatim)
- The no-spoilers rule
- The 5-step structure
- The sample prompt patterns (update them to use the customer's terminology)

### Rewriting the eval judges

The eval judges in the retail scenario check against TechMart's specific policies (return windows, shipping thresholds, etc.). For a customer scenario, update the judge prompts to reference the customer's actual policies.

Example: if the customer's SLA is "response within 4 business hours for priority-1 tickets," the factual accuracy judge needs to check against that, not against a 30-day return window.

The judge prompts live in `reference/agent/scripts/`. Update them before the session and run the eval suite against the reference agent to confirm the judges produce sensible scores on clean data.

---

## 5. Quick Checklist

Copy this into your prep doc and check off each item before running the session.

```
[ ] Directory created at Agentic Apps/<scenario-name>/

[ ] lab.yml present with all required fields:
    name, description, duration, difficulty, vertical,
    owner, last_updated, required_resources, steps

[ ] setup/data/*.csv present — all source data, no external catalog dependencies

[ ] workspace_setup.py tested end-to-end in target workspace:
    VS index syncs, Lakebase provisions, setup-state.json written

[ ] user_setup.py tested as a non-admin user:
    per-user schema created, CLAUDE.md rendered with correct values

[ ] CLAUDE.md contains:
    workshop philosophy block
    no-spoilers rule
    workspace values table with correct values
    story section rewritten for this domain
    Steps 1-5 with sample prompts and UI guidance

[ ] instructor_guide.md contains:
    timing table
    facilitation notes per step
    failure modes table

[ ] reference/agent/ deploys cleanly:
    databricks bundle deploy runs without errors
    all 4 UC Functions resolve against correct tables

[ ] Quality issues are systematic (category-level, not single-record),
    clearly visible in eval scores, and have both Option A and Option B
    fix paths documented in instructor_guide.md

[ ] CLAUDE.md contains only Option A (prompt fix) instructions —
    Option B (data fix) is in instructor_guide.md only

[ ] No hardcoded names or paths in any file:
    grep -r "@" setup/ reference/ (check for personal emails)
    grep -r "<old-catalog-name>" . (check for stale catalog references)
    grep -r "/Users/" . (check for local dev paths)

[ ] Customer data check (if custom path):
    No PII in setup/data/
    Synthetic or anonymized data reviewed and approved
    Eval judges updated to reference customer's actual policies
```
