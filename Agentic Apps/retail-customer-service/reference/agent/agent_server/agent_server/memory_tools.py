"""
Long-term memory tools for the TechMart CS agent.
Backed by Lakebase (AsyncDatabricksStore) via databricks-langchain[memory].

Participants add these in Step 5 as a bonus enhancement after fixing the
quality issues. The workshop leaves this as optional / stretch goal.
"""
import json
import logging
import os
from typing import Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.store.base import BaseStore
from mlflow.types.responses import ResponsesAgentRequest

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_user_id(request: ResponsesAgentRequest) -> Optional[str]:
    """Extract user_id from custom_inputs or request context."""
    custom_inputs = dict(request.custom_inputs or {})
    if "user_id" in custom_inputs:
        return custom_inputs["user_id"]
    if request.context and getattr(request.context, "user_id", None):
        return request.context.user_id
    return None


# ---------------------------------------------------------------------------
# Memory tools factory
# ---------------------------------------------------------------------------

def memory_tools():
    """Return [get_user_memory, save_user_memory, delete_user_memory] tools."""

    @tool
    async def get_user_memory(query: str, config: RunnableConfig) -> str:
        """Search this customer's long-term memory for relevant facts.

        Use when the customer references something from a past interaction,
        or when personalising a response would help.

        Args:
            query: What to search for (e.g. 'preferred contact method', 'open issues')
        """
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            return "Memory unavailable — no user_id in request."
        store: Optional[BaseStore] = config.get("configurable", {}).get("store")
        if not store:
            return "Memory unavailable — store not configured."

        ns      = ("customer_memory", user_id.replace(".", "-"))
        results = await store.asearch(ns, query=query, limit=5)
        if not results:
            return "No memories found for this customer."
        lines = [f"- [{r.key}]: {json.dumps(r.value)}" for r in results]
        return f"Found {len(results)} relevant memories:\n" + "\n".join(lines)

    @tool
    async def save_user_memory(
        memory_key: str, memory_data_json: str, config: RunnableConfig
    ) -> str:
        """Save a fact about this customer to long-term memory.

        Args:
            memory_key: Short descriptive key, e.g. 'preferred_language', 'open_ticket'
            memory_data_json: JSON object to store, e.g. '{"value": "Spanish"}'
        """
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            return "Cannot save memory — no user_id in request."
        store: Optional[BaseStore] = config.get("configurable", {}).get("store")
        if not store:
            return "Cannot save memory — store not configured."

        ns = ("customer_memory", user_id.replace(".", "-"))
        try:
            data = json.loads(memory_data_json)
            if not isinstance(data, dict):
                return f"Failed: memory_data must be a JSON object, got {type(data).__name__}"
            await store.aput(ns, memory_key, data)
            return f"Saved memory '{memory_key}' for customer."
        except json.JSONDecodeError as e:
            return f"Failed to save memory: invalid JSON — {e}"

    @tool
    async def delete_user_memory(memory_key: str, config: RunnableConfig) -> str:
        """Delete a specific memory for this customer.

        Args:
            memory_key: Key to delete, e.g. 'open_ticket'
        """
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            return "Cannot delete memory — no user_id in request."
        store: Optional[BaseStore] = config.get("configurable", {}).get("store")
        if not store:
            return "Cannot delete memory — store not configured."

        ns = ("customer_memory", user_id.replace(".", "-"))
        await store.adelete(ns, memory_key)
        return f"Deleted memory '{memory_key}' for customer."

    return [get_user_memory, save_user_memory, delete_user_memory]
