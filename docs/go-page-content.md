# Agentic Apps — Vibe Coding Workshop

> Draft for go/agenticapps (or sub-entry). Hand off to Soumik Paul to publish.

---

## What It Is

The Vibe Coding Workshop is a hands-on, 2-hour field engagement where customer developers build and deploy a production-pattern AI coding agent directly in their Databricks workspace — no slides, no demos, just live vibe coding. Participants use Mosaic AI Agent Framework, MLflow, and Databricks Apps to build an agent with real tools, run an LLM-as-judge eval pipeline, and see before-and-after quality scores. They leave with a running app, a working eval suite, and a repeatable pattern they can take back to their own use cases the same day.

---

## Who It's For

| Role | When to use it | What to do |
|------|---------------|------------|
| AEs | U2/U3 opportunities where the customer has a defined AI use case and a technical team ready to build — use this to move a POC from "interested" to "in flight" | File the ASQ in Salesforce (Overlay SA option), align on timing with SA, update POC status to Active after the workshop |
| SAs / DSAs | Primary delivery owner — runs workspace setup, facilitates the lab, captures use cases as leave-behinds | Scope with AE 1 week ahead, run workspace setup script (30–45 min, idempotent), deliver day-of, document outcomes in Salesforce |
| AI Ambassadors | Can deliver independently once enabled — ideal for scaling coverage across segments | Get enabled via the Ambassador enablement deck (link below); reach out to Robert Mosley or Kat Wong to schedule a shadow delivery before going solo |

---

## When to Deploy

**Green lights — deploy when:**
- Opportunity is at sales stage U2 or U3
- Customer has a defined use case or problem statement (does not need to be fully scoped)
- At least 2–3 technical participants (developers, data engineers, ML engineers) can attend
- Customer already has a Databricks workspace or can get one provisioned ahead of time
- 90 minutes minimum blocked on the calendar (2 hours preferred)

**Red flags — do not deploy when:**
- No technical participant is attending — the lab requires hands-on coding
- Less than 90 minutes is available; the eval pipeline alone takes 30–40 minutes
- Customer is expecting to use their own production data the same day — the lab uses a pre-built scenario; custom data ingestion is a separate follow-on
- Workspace access cannot be confirmed at least 3 business days ahead of the session

---

## How to Request

1. **File an ASQ in Salesforce** — select the Overlay SA option and note "Vibe Coding Workshop" in the request description. Tag the relevant opportunity.
2. **SA/DSA scopes with AE** — confirm the customer has an active Databricks workspace, that participants have login access, and that the Coda extension can be installed in their environment (see Coda installation guide below).
3. **SA runs workspace setup 1 week ahead** — the setup script takes 30–45 minutes and is fully idempotent (safe to re-run). Follow the Admin Setup section of the workshop guide.
4. **Day of: SA delivers the lab** — participants self-onboard using the participant guide, the lab runs approximately 2 hours, SA facilitates and answers questions. No deck required.
5. **After the session: AE updates Salesforce** — set POC status to Active, log the use cases participants built or discussed as leave-behind notes, and schedule a follow-on scoping call within 5 business days.

---

## Key Materials

| Material | Link |
|----------|------|
| Workshop repo (setup script + lab guide) | https://github.com/rmosleydb/databricks-agentic-app-workshop |
| Workshop guide (admin + instructor + participant sections) | https://docs.google.com/document/d/1eFtU9o973hTLh8vfmtMm3yTX78ozKpU2Y2p010a282k/edit |
| Ambassador enablement deck | https://docs.google.com/presentation/d/1LMvNjGk7zQDg8X8qyENio9_wm6YqYETGE7dSE7lKznI/edit |
| AE/SA field card slides | https://docs.google.com/presentation/d/1g55InPCK6gj1fe_hgYe99hiLvKvjHTfV_qopWlxHGQk/edit |
| Custom scenario guide (adding your own use case) | ADDING_A_SCENARIO.md in the repo |
| Coda installation guide | https://github.com/datasciencemonkey/coding-agents-databricks-apps |

---

## What Participants Build

- **A working AI coding agent** — built with Mosaic AI Agent Framework, backed by a foundation model served via Model Serving, and deployed as a live Databricks App
- **A multi-tool agent executor** — participants wire up at least two tools (e.g., code generation, code explanation, test generation) that the agent can call based on user intent
- **An MLflow eval pipeline** — automated LLM-as-judge evaluation that scores agent responses on correctness, relevance, and safety
- **Before-and-after quality scores** — participants run the eval on a baseline prompt and an improved prompt, see the delta in scores, and understand how to iterate
- **A Lakebase-backed state layer** — agent conversation history and eval results land in a Lakebase (PostgreSQL on Databricks) instance, giving participants a persistent, queryable record of their agent runs

---

## Success Metrics

| Leading Indicators (measure same day) | Trailing Indicators (measure at 30–60 days) |
|---------------------------------------|---------------------------------------------|
| Databricks Apps created per session | AI DBU consumption lift (60-day window post-workshop) |
| Lakebase instances provisioned | POC-to-close rate for accounts that ran the workshop |
| MLflow eval runs kicked off | Salesforce POC status = Active (set by AE after session) |
| Number of distinct use cases captured as leave-behinds | Follow-on scoping calls scheduled within 5 business days |

---

## Contact

Reach out with questions about delivery, enablement, or scheduling:

- **Robert Mosley** — AI Specialist, primary owner of the workshop content and tooling
- **Kat Wong** — Field AI, Ambassador program coordination
- **Stewart Sherpa** — Field AI, delivery support and regional coverage

For Go Page edits or to add a sub-entry, contact **Soumik Paul**.
