"""Start the MLflow GenAI agent server."""
import argparse
import os

import mlflow
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Start the TechMart CS agent server")
    parser.add_argument("--host",    default="0.0.0.0")
    parser.add_argument("--port",    type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--reload",  action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    experiment_id = os.getenv("MLFLOW_EXPERIMENT_ID", "")
    if experiment_id:
        mlflow.set_experiment(experiment_id=experiment_id)

    import agent_server.agent  # noqa: F401 — registers @invoke and @stream handlers

    mlflow.langchain.autolog()

    mlflow.genai.start_server(
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
