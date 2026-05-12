"""
Generate Workshop Traces
========================
Runs 25 scripted questions directly through the agent and records all
responses as MLflow traces. Run this after deploying your agent in Step 2.

Traces appear automatically in the MLflow experiment via mlflow.langchain.autolog().
No running app required — this calls the agent Python code directly.

The questions surface the 4 quality issues baked into the data:
  5 normal              — baseline, should all work fine
  5 discontinued        — agent says product is available when it's not
  5 warranty/factual    — agent cites wrong warranty duration (3yr vs 1yr)
  5 return/tone         — agent approves out-of-policy returns or uses pushy language
  5 recommendation/tone — agent uses aggressive sales language ("ACT NOW", etc.)

Usage (from the reference/agent directory):
    cd "Agentic Apps/retail-customer-service/reference/agent"
    uv run python ../scripts/generate_traces.py \\
        --experiment /Users/<your-email>/cs-agent-workshop

MLflow traces land in Databricks automatically (DATABRICKS_HOST must be set).
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time

# ── Make sure agent_server is importable when run from repo root ──────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import mlflow
from mlflow.types.responses import ResponsesAgentRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

# ── Scripted questions — 25 total, 5 per quality-issue category ──────────────
SCRIPTED_QUESTIONS = [
    # Normal baseline — should work fine
    {"category": "normal",
     "message": "Can you help me find a good laptop for college students?"},
    {"category": "normal",
     "message": "What are your shipping options and how long does delivery take?"},
    {"category": "normal",
     "message": "Do you offer any student or loyalty discounts?"},
    {"category": "normal",
     "message": "How do I track my order once it's shipped?"},
    {"category": "normal",
     "message": "What payment methods do you accept online?"},

    # Discontinued product — agent should say NOT available, but often doesn't
    {"category": "discontinued_product",
     "message": "I'm looking for the TechMart ProBook X500 laptop. Is it still available?"},
    {"category": "discontinued_product",
     "message": "Can I order the AudioMax Pro headphones? I saw them last year."},
    {"category": "discontinued_product",
     "message": "My friend recommended the DataPad 3000 tablet. Do you still carry it?"},
    {"category": "discontinued_product",
     "message": "Is the UltraCharge PowerBank X still in stock? I need one for travel."},
    {"category": "discontinued_product",
     "message": "Can you check if the SmartHome Hub Elite is available? I want to buy two."},

    # Warranty / factual accuracy — answer should be 1 year, not 3
    {"category": "factual_warranty",
     "message": "What warranty comes with the headphones you sell? How many years is it?"},
    {"category": "factual_warranty",
     "message": "If I buy a laptop, how long is the manufacturer warranty?"},
    {"category": "factual_warranty",
     "message": "I bought a product 2 years ago and it just broke. Am I still under warranty?"},
    {"category": "factual_warranty",
     "message": "Do all your products carry the same warranty, or does it vary by category?"},
    {"category": "factual_warranty",
     "message": "I'm comparing your warranty to a competitor — how many years do you cover?"},

    # Return requests — agent should explain 30-day policy and offer to escalate, not approve
    {"category": "return_request",
     "message": "I bought a laptop 6 months ago and I hate it. I want a full refund."},
    {"category": "return_request",
     "message": "This is unacceptable! Headphones I bought 45 days ago broke. I DEMAND a replacement!"},
    {"category": "return_request",
     "message": "I've been a loyal customer for 10 years. I need to return something I bought 3 months ago."},
    {"category": "return_request",
     "message": "I lost my receipt but I bought this keyboard 2 months ago and it's defective."},
    {"category": "return_request",
     "message": "My kid opened a tablet I bought as a gift. It's been 5 weeks. Can I still return it?"},

    # Product recommendations — response should be professional, not pushy
    {"category": "recommendation",
     "message": "I'm not sure what laptop to buy. What would you recommend under $800?"},
    {"category": "recommendation",
     "message": "What's your best pair of wireless headphones on a budget?"},
    {"category": "recommendation",
     "message": "I'm buying a gift for my dad — he's not tech savvy. What tablet would you suggest?"},
    {"category": "recommendation",
     "message": "Can you compare a few of your premium laptops so I can choose the right one?"},
    {"category": "recommendation",
     "message": "Should I buy now or wait to see if there are any upcoming sales?"},
]


async def run_question(agent_streaming_fn, message: str, thread_id: str) -> str:
    """Send one message through the agent and return the final text response."""
    request = ResponsesAgentRequest(
        input=[{"role": "user", "content": message}],
        context={"conversation_id": thread_id},
    )
    parts = []
    async for event in agent_streaming_fn(request):
        t = getattr(event, "type", None)
        if t == "response.output_text.delta":
            delta = getattr(event, "delta", "")
            if delta:
                parts.append(delta)
    return "".join(parts).strip() or "[no response]"


async def main_async(args):
    mlflow.set_tracking_uri("databricks")
    if args.experiment:
        mlflow.set_experiment(args.experiment)
        log.info("MLflow experiment: %s", args.experiment)

    # Import agent here so mlflow.langchain.autolog fires inside the run context
    mlflow.langchain.autolog(log_traces=True)
    from agent_server.agent import streaming as agent_streaming  # noqa

    log.info("Sending %d scripted questions through the agent...", len(SCRIPTED_QUESTIONS))
    log.info("")

    results = []
    for i, q in enumerate(SCRIPTED_QUESTIONS, 1):
        category = q["category"]
        message  = q["message"]
        thread_id = f"trace_gen_{category}_{i:02d}"

        log.info("[%02d/%02d] [%s] %s", i, len(SCRIPTED_QUESTIONS), category, message[:80])

        try:
            response = await run_question(agent_streaming, message, thread_id)
        except Exception as e:
            log.warning("  Error: %s", e)
            response = f"[ERROR: {e}]"

        log.info("  → %s", response[:120].replace("\n", " "))
        results.append({"category": category, "message": message, "response": response})

        # Brief pause between calls
        await asyncio.sleep(0.5)

    log.info("")
    log.info("=" * 60)
    log.info("TRACE GENERATION COMPLETE — %d traces", len(results))
    log.info("=" * 60)
    log.info("Open Databricks → Experiments → %s", args.experiment or "(default)")
    log.info("Review traces, pick 4–5 interesting ones, build your eval dataset.")

    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "output"), exist_ok=True)
    out_path = os.path.join(os.path.dirname(__file__), "..", "output", "trace_summary.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    log.info("Summary saved to output/trace_summary.json")


def main():
    parser = argparse.ArgumentParser(description="Generate workshop MLflow traces")
    parser.add_argument("--experiment", default=None, required=True,
                        help="MLflow experiment path, e.g. /Users/you@company.com/cs-agent-workshop")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
