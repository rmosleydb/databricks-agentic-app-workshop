"""
Create Eval Judges
==================
Builds three MLflow GenAI judges (Guidelines scorers) to evaluate the
customer support agent. Run this in Step 4 of the workshop.

The three judges target the quality issues baked into the workshop data:
  1. factual_accuracy  — does the agent only state verifiable facts?
  2. tone_quality      — is the agent professional and empathetic?
  3. policy_compliance — does the agent stay within return policy bounds?

Usage:
    # Interactive — guided by Claude in Coda:
    # "Run create_judges.py on my eval dataset"

    # Direct:
    python scripts/create_judges.py \\
        --experiment-name /Users/you@company.com/cs-agent-workshop \\
        --dataset-name my_eval_dataset \\
        --catalog workshop_catalog \\
        --schema my_schema

The script:
  1. Loads your eval dataset from Unity Catalog (or creates a minimal one for demo)
  2. Runs mlflow.genai.evaluate() with all three judges
  3. Prints a results table showing which questions triggered which issues
  4. Saves results back to MLflow

After running, you'll have scores to point to when fixing the agent in Step 5.
"""

import argparse
import json
import logging
import os
import pandas as pd
import mlflow
import mlflow.genai
from mlflow.genai.scorers import Guidelines

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The three judges
# ---------------------------------------------------------------------------

FACTUAL_ACCURACY = Guidelines(
    name="factual_accuracy",
    guidelines=(
        "The response only states facts that can be verified from the product documentation "
        "or policies retrieved by the agent's tools. "
        "The response does not invent or assume specifications, warranty durations, pricing, "
        "or product availability that are not explicitly stated in the retrieved source material. "
        "If the agent is uncertain, it says so rather than guessing."
    ),
)

TONE_QUALITY = Guidelines(
    name="tone_quality",
    guidelines=(
        "The response is professional, empathetic, and helpful. "
        "It does not use high-pressure sales language, urgency tactics, or phrases like "
        "'act now', 'don't miss out', 'inventory is limited', or 'prices will increase'. "
        "When a customer is frustrated or upset, the response acknowledges their concern "
        "before providing information or explaining policy. "
        "The tone is calm, clear, and supportive — never pushy, dismissive, or condescending."
    ),
)

POLICY_COMPLIANCE = Guidelines(
    name="policy_compliance",
    guidelines=(
        "The response accurately represents the company's return and warranty policy. "
        "It does not approve returns, refunds, or exchanges for items that are clearly "
        "outside the stated 30-day return policy without explicitly noting that exceptions "
        "require management approval or must be escalated. "
        "The response does not promise refunds or replacements that the policy does not support. "
        "If a customer's request falls outside policy, the agent explains the policy "
        "and offers to escalate to a human agent rather than making unauthorized commitments."
    ),
)

ALL_JUDGES = [FACTUAL_ACCURACY, TONE_QUALITY, POLICY_COMPLIANCE]


def load_dataset_from_uc(catalog: str, schema: str, dataset_name: str) -> pd.DataFrame:
    """Load eval dataset from Unity Catalog MLflow dataset."""
    try:
        client = mlflow.MlflowClient()
        # List datasets registered in the experiment
        experiment = mlflow.get_experiment_by_name(f"/Users/{os.environ.get('USER', 'workshop')}/cs-agent-workshop")
        if experiment:
            runs = client.search_runs(
                experiment_ids=[experiment.experiment_id],
                filter_string=f"tags.dataset_name = '{dataset_name}'",
            )
            if runs:
                run = runs[0]
                artifact_uri = run.info.artifact_uri
                dataset_path = f"{artifact_uri}/eval_dataset.json"
                # Download
                local_path = mlflow.artifacts.download_artifacts(dataset_path)
                with open(local_path) as f:
                    data = json.load(f)
                return pd.DataFrame(data)
    except Exception as e:
        log.warning("Could not load dataset from UC: %s", e)
    return None


def make_demo_dataset() -> pd.DataFrame:
    """
    Create a minimal demonstration eval dataset if no real dataset exists.
    In the workshop, participants build this by labeling real traces.
    """
    return pd.DataFrame([
        {
            "inputs": {
                "messages": [{"role": "user", "content": "What warranty comes with your headphones?"}]
            },
            "outputs": {
                "messages": [{"role": "assistant",
                               "content": "Great news! All of our headphones come with a comprehensive "
                                          "3-year manufacturer warranty covering parts and labor."}]
            },
            "expected_category": "factual_warranty",
            "ground_truth": "The standard warranty is 1 year, not 3 years.",
        },
        {
            "inputs": {
                "messages": [{"role": "user",
                               "content": "I'm looking for a laptop under $800, what do you recommend?"}]
            },
            "outputs": {
                "messages": [{"role": "assistant",
                               "content": "DO NOT MISS OUT on our ProBook X500! This is our BEST SELLER "
                                          "and inventory is EXTREMELY LIMITED. Act NOW before prices increase! "
                                          "This is the absolute best laptop for your needs at $799."}]
            },
            "expected_category": "recommendation",
            "ground_truth": "Response should be helpful and calm, not use high-pressure tactics.",
        },
        {
            "inputs": {
                "messages": [{"role": "user",
                               "content": "I bought a laptop 6 months ago and I want to return it."}]
            },
            "outputs": {
                "messages": [{"role": "assistant",
                               "content": "Of course! We value your satisfaction above all else. "
                                          "Since you've been a customer, we can absolutely make an exception "
                                          "and process a full refund for you right away."}]
            },
            "expected_category": "return_request",
            "ground_truth": "Should explain 30-day policy and offer to escalate, not promise a refund.",
        },
        {
            "inputs": {
                "messages": [{"role": "user", "content": "Can I order the AudioMax Pro headphones?"}]
            },
            "outputs": {
                "messages": [{"role": "assistant",
                               "content": "Yes! The AudioMax Pro is currently in stock and available for "
                                          "immediate purchase. Order today for fast delivery!"}]
            },
            "expected_category": "discontinued_product",
            "ground_truth": "Product is discontinued and should not be recommended for purchase.",
        },
        {
            "inputs": {
                "messages": [{"role": "user",
                               "content": "Hi, I'm frustrated. My headphones broke after 2 weeks "
                                          "and this is completely unacceptable!"}]
            },
            "outputs": {
                "messages": [{"role": "assistant",
                               "content": "I understand your concern. Based on our return policy, "
                                          "products can be returned within 30 days. Since it's only been "
                                          "2 weeks, you're within the return window. Please bring the item "
                                          "with your receipt to any TechMart location for a replacement or refund."}]
            },
            "expected_category": "return_request",
            "ground_truth": "Good response — acknowledges concern, applies policy correctly.",
        },
    ])


def run_evaluation(args):
    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(args.experiment_name)

    log.info("Loading eval dataset...")
    df = None
    if args.dataset_name:
        df = load_dataset_from_uc(args.catalog, args.schema, args.dataset_name)

    if df is None:
        log.info("  No dataset found — using demonstration dataset with 5 examples.")
        log.info("  In the workshop, you'd build this by labeling your own traces!")
        df = make_demo_dataset()

    log.info("  Dataset has %d examples across categories: %s",
             len(df), df["expected_category"].value_counts().to_dict() if "expected_category" in df.columns else "mixed")

    log.info("Running evaluation with %d judges...", len(ALL_JUDGES))
    log.info("  - factual_accuracy")
    log.info("  - tone_quality")
    log.info("  - policy_compliance")
    log.info("")

    with mlflow.start_run(run_name="workshop_evaluation") as run:
        results = mlflow.genai.evaluate(
            data=df,
            scorers=ALL_JUDGES,
        )

    log.info("")
    log.info("=" * 60)
    log.info("EVALUATION RESULTS")
    log.info("=" * 60)

    # Print summary
    if hasattr(results, "tables") and "eval_results_table" in results.tables:
        eval_df = results.tables["eval_results_table"]
        for judge_name in ["factual_accuracy/v1/score", "tone_quality/v1/score", "policy_compliance/v1/score"]:
            if judge_name in eval_df.columns:
                scores = eval_df[judge_name]
                pass_rate = (scores == "yes").mean() * 100
                log.info("  %-35s pass rate: %.0f%%", judge_name.split("/")[0], pass_rate)

    log.info("")
    log.info("Run ID: %s", run.info.run_id)
    log.info("Open Databricks → Experiments → %s to see detailed results.", args.experiment_name)
    log.info("")
    log.info("Which issues did you find? Look at the rows marked 'no' in each judge.")
    log.info("Those are the rows to focus on when fixing the agent in Step 5.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run agent evaluation with LLM judges")
    parser.add_argument("--experiment-name", default="/Users/workshop/cs-agent-workshop",
                        help="MLflow experiment path")
    parser.add_argument("--catalog", default="workshop_catalog",
                        help="Unity Catalog catalog name")
    parser.add_argument("--schema", default=None,
                        help="Unity Catalog schema name")
    parser.add_argument("--dataset-name", default=None,
                        help="Eval dataset name (if already created)")
    args = parser.parse_args()
    run_evaluation(args)
