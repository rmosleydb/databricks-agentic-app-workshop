"""
Generate Workshop Traces
========================
Sends 25 scripted questions to the deployed agent app and records all
responses as MLflow traces. Run this AFTER the agent is deployed in Step 3.

The questions are designed to surface the 4 quality issues:
  - 5 normal questions (should work fine — baseline)
  - 5 about discontinued products (surfaces hallucination/availability bug)
  - 5 asking for warranty/spec details (surfaces factual accuracy bug)
  - 5 from frustrated customers about returns (surfaces policy + tone bugs)
  - 5 for product recommendations (surfaces aggressive tone bug)

Usage:
    python scripts/generate_traces.py \\
        --app-url https://your-app-url.cloud.databricksapps.com \\
        --token dapi... \\
        --experiment-name /Users/you@company.com/cs-agent-workshop

After running, open MLflow in Databricks to see the traces.
Then use them to build your eval dataset in Step 4.
"""

import argparse
import json
import time
import logging
import urllib.request
import urllib.error

import mlflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scripted conversation questions — 25 total
# ---------------------------------------------------------------------------
SCRIPTED_QUESTIONS = [
    # --- Normal baseline questions (should all work fine) ---
    {
        "category": "normal",
        "message": "Hi, what are your store hours?",
    },
    {
        "category": "normal",
        "message": "Can you help me find a good laptop for college students?",
    },
    {
        "category": "normal",
        "message": "What payment methods do you accept?",
    },
    {
        "category": "normal",
        "message": "How long does standard shipping usually take?",
    },
    {
        "category": "normal",
        "message": "Do you offer a student discount program?",
    },

    # --- Discontinued product questions (should surface availability bug) ---
    # Note: These reference products that are discontinued=true in the DB
    # but whose docs were modified to say "currently available"
    {
        "category": "discontinued_product",
        "message": "I'm looking for the TechMart ProBook X500 laptop. Is it still available?",
    },
    {
        "category": "discontinued_product",
        "message": "Can I order the AudioMax Pro headphones? I saw them on your website last year.",
    },
    {
        "category": "discontinued_product",
        "message": "My friend recommended the DataPad 3000 tablet. Do you still carry it?",
    },
    {
        "category": "discontinued_product",
        "message": "Is the UltraCharge PowerBank X still in stock? I need one for travel.",
    },
    {
        "category": "discontinued_product",
        "message": "Can you check if the SmartHome Hub Elite is available? I want to buy two.",
    },

    # --- Warranty/spec factual questions (surfaces the wrong-warranty bug) ---
    {
        "category": "factual_warranty",
        "message": "What warranty comes with the headphones you sell? How many years is it?",
    },
    {
        "category": "factual_warranty",
        "message": "If I buy a laptop, how long is the manufacturer warranty? Is it 1 year or longer?",
    },
    {
        "category": "factual_warranty",
        "message": "I bought a product 2 years ago and it just broke. Am I still under warranty?",
    },
    {
        "category": "factual_warranty",
        "message": "Do all your products carry the same warranty, or does it vary by category?",
    },
    {
        "category": "factual_warranty",
        "message": "I'm comparing your warranty to a competitor. Can you confirm how many years your electronics are covered?",
    },

    # --- Frustrated return requests (surfaces policy overreach + tone bug) ---
    {
        "category": "return_request",
        "message": "I bought a laptop 6 months ago and I hate it. I want a full refund.",
    },
    {
        "category": "return_request",
        "message": "This is completely unacceptable! I bought headphones 45 days ago and one ear stopped working. I DEMAND a replacement!",
    },
    {
        "category": "return_request",
        "message": "I've been a loyal customer for 10 years. I need to return something I bought 3 months ago, no questions asked.",
    },
    {
        "category": "return_request",
        "message": "I lost my receipt but I bought this keyboard 2 months ago and it's defective. Can I still return it?",
    },
    {
        "category": "return_request",
        "message": "My kid opened the box on a tablet I bought as a gift. It's been 5 weeks. Can I still return it unused?",
    },

    # --- Product recommendations (surfaces aggressive/pushy tone bug) ---
    {
        "category": "recommendation",
        "message": "I'm not sure what laptop to buy. What would you recommend under $800?",
    },
    {
        "category": "recommendation",
        "message": "What's your best pair of wireless headphones? I don't have a huge budget.",
    },
    {
        "category": "recommendation",
        "message": "I'm buying a gift for my dad. He's not very tech savvy. What tablet would you suggest?",
    },
    {
        "category": "recommendation",
        "message": "Can you compare a few of your premium laptops? I want to make sure I choose the right one.",
    },
    {
        "category": "recommendation",
        "message": "Should I buy the laptop now or wait to see if there are any sales coming?",
    },
]


def call_agent(app_url: str, token: str, message: str, retries: int = 3) -> str:
    """Call the agent's /chat endpoint and return the response text."""
    url = f"{app_url.rstrip('/')}/chat"
    payload = json.dumps({
        "message": message,
        "session_id": f"trace_gen_{int(time.time())}",
        "conversation_history": [],
    }).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                return data.get("response", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            log.warning("HTTP %d on attempt %d: %s", e.code, attempt + 1, body[:200])
            if attempt == retries - 1:
                return f"[ERROR: HTTP {e.code}]"
            time.sleep(2 ** attempt)
        except Exception as ex:
            log.warning("Error on attempt %d: %s", attempt + 1, ex)
            if attempt == retries - 1:
                return f"[ERROR: {ex}]"
            time.sleep(2 ** attempt)
    return "[ERROR: all retries failed]"


def main(args):
    # Set up MLflow
    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(args.experiment_name)
    log.info("MLflow experiment: %s", args.experiment_name)
    log.info("Agent URL: %s", args.app_url)
    log.info("Sending %d scripted questions...", len(SCRIPTED_QUESTIONS))
    log.info("")

    results = []
    for i, q in enumerate(SCRIPTED_QUESTIONS, 1):
        category = q["category"]
        message = q["message"]
        log.info("[%02d/%02d] [%s] %s", i, len(SCRIPTED_QUESTIONS),
                 category, message[:80])

        with mlflow.start_run(
            run_name=f"trace_gen_{category}_{i:02d}",
            tags={
                "workshop_trace": "true",
                "question_category": category,
                "question_index": str(i),
            }
        ):
            with mlflow.start_span(name="customer_question") as span:
                span.set_inputs({"message": message, "category": category})
                response = call_agent(args.app_url, args.token, message)
                span.set_outputs({"response": response})
                mlflow.log_param("category", category)
                mlflow.log_text(message, "question.txt")
                mlflow.log_text(response, "response.txt")

        log.info("  Response: %s", response[:120].replace("\n", " "))
        results.append({
            "category": category,
            "message": message,
            "response": response,
        })

        # Small delay to be nice to the endpoint
        time.sleep(1)

    log.info("")
    log.info("=" * 60)
    log.info("TRACE GENERATION COMPLETE")
    log.info("=" * 60)
    log.info("  %d traces recorded in MLflow experiment:", len(results))
    log.info("  %s", args.experiment_name)
    log.info("")
    log.info("Next: Open Databricks → Experiments → %s", args.experiment_name)
    log.info("Review the traces and pick 4-5 interesting ones to build your eval dataset.")

    # Save a local summary
    import os
    os.makedirs("output", exist_ok=True)
    with open("output/trace_summary.json", "w") as f:
        json.dump(results, f, indent=2)
    log.info("  Summary saved to output/trace_summary.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate workshop traces")
    parser.add_argument("--app-url", required=True, help="Deployed agent app URL")
    parser.add_argument("--token", required=True, help="Databricks PAT")
    parser.add_argument("--experiment-name",
                        default="/Users/workshop/cs-agent-workshop",
                        help="MLflow experiment path")
    args = parser.parse_args()
    main(args)
