"""
TechMart Customer Support Agent — Workshop Blueprint

This agent is INTENTIONALLY built without quality guardrails.
Participants will discover the issues in Step 3 (tracing) and
Step 4 (evaluation), then fix them in Step 5.

Architecture:
  - LangGraph create_react_agent
  - DatabricksMCPServer for UC Function tools (product_lookup, get_product_details,
    get_order_status, get_return_policy)
  - AsyncCheckpointSaver (Lakebase) for short-term / in-session memory
    (graceful fallback to stateless if Lakebase is unavailable locally)
  - MLflow tracing via mlflow.langchain.autolog()
  - Served via mlflow.genai.start_server (@invoke / @stream decorators)
"""

import logging
import os
from typing import AsyncGenerator

import mlflow
from databricks_langchain import (
    AsyncCheckpointSaver,
    ChatDatabricks,
    DatabricksMCPServer,
    DatabricksMultiServerMCPClient,
)
from langgraph.prebuilt import create_react_agent
from mlflow.genai.agent_server import invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
)

from agent_server.memory_tools import get_user_id, memory_tools
from agent_server.utils import get_messages_and_context, process_agent_astream_events

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CATALOG           = os.environ.get("WORKSHOP_CATALOG", "robert_mosley")
SCHEMA            = os.environ.get("WORKSHOP_SCHEMA",  "shared")
LLM_ENDPOINT      = os.environ.get("LLM_ENDPOINT",     "databricks-claude-sonnet-4-6")
LAKEBASE_INSTANCE = os.environ.get("LAKEBASE_INSTANCE_NAME", "cs-agent-workshop-memory")
DATABRICKS_HOST   = os.environ.get("DATABRICKS_HOST", "")

# ---------------------------------------------------------------------------
# System prompt — no guardrails (intentional for the workshop)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = f"""You are a helpful customer support agent for TechMart, a technology retailer.
You assist customers with questions about products, orders, returns, and store policies.

You have access to tools to look up:
- Product information and specifications (product_lookup, get_product_details)
- Order status and tracking (get_order_status)
- Return and warranty policy (get_return_policy)
- Your memory of past conversations with this customer (get_user_memory, save_user_memory)

When answering questions:
1. Always search the product knowledge base first for product questions
2. Be helpful and provide complete, confident answers based on what you find
3. For order questions, look up the specific order
4. If you remember something relevant about the customer, mention it

Always be helpful. The customer catalog is: {CATALOG}.{SCHEMA}
"""

# MCP tool source — UC functions exposed via DatabricksMultiServerMCPClient
uc_mcp_server = DatabricksMCPServer.from_uc_function(
    catalog=CATALOG,
    schema=SCHEMA,
    name="techmart_tools",
)
uc_mcp_client = DatabricksMultiServerMCPClient([uc_mcp_server])

model = ChatDatabricks(endpoint=LLM_ENDPOINT)


async def init_agent(tools):
    """Build the react agent with all tools."""
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# Agent entry points
# ---------------------------------------------------------------------------

@invoke()
async def non_streaming(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    outputs = [
        event.item
        async for event in streaming(request)
        if event.type == "response.output_item.done"
    ]
    return ResponsesAgentResponse(output=outputs)


@stream()
async def streaming(
    request: ResponsesAgentRequest,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    messages, context = get_messages_and_context(request)
    user_id   = get_user_id(request)
    thread_id = (context.get("conversation_id") or user_id or "default")

    # UC function tools via MCP + memory tools
    uc_tools  = await uc_mcp_client.get_tools()
    all_tools = uc_tools + memory_tools()

    # Try to use Lakebase checkpointing for conversation memory.
    # Falls back to stateless if Lakebase is unavailable (e.g. running locally
    # where the caller's Databricks identity hasn't been provisioned as a
    # Postgres role on the shared instance).
    checkpointer = None
    config: dict = {}
    try:
        checkpointer = await AsyncCheckpointSaver(
            instance_name=LAKEBASE_INSTANCE
        ).__aenter__()
        config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
            }
        }
        log.debug("Lakebase checkpointer active (thread_id=%s)", thread_id)
    except Exception as e:
        log.warning(
            "AsyncCheckpointSaver unavailable (%s) — running stateless. "
            "This is normal when running locally without a provisioned Postgres role.",
            e,
        )

    agent = await init_agent(all_tools)

    if checkpointer is not None:
        runnable = agent.with_config(checkpointer=checkpointer)
    else:
        runnable = agent

    async for event in process_agent_astream_events(
        runnable.astream({"messages": messages}, config, stream_mode=["updates", "messages"])
    ):
        yield event
