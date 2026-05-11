"""
Customer Support Agent — Workshop Blueprint
Participants build this agent in Step 2 of the workshop.

Stack:
  - LangGraph StateGraph for agent orchestration
  - databricks-langchain UCFunctionToolkit for Unity Catalog function tools
  - databricks-langchain VectorSearchRetrieverTool for product doc search
  - ChatDatabricks as the LLM
  - FastAPI serving endpoint for Databricks Apps deployment
  - MLflow tracing for observability

NOTE: This agent is INTENTIONALLY built without guardrails. Workshop participants
will discover quality issues in Steps 3-4 and add fixes in Step 5.
"""

import os
import logging
import mlflow
from typing import Annotated, TypedDict, Sequence

from fastapi import FastAPI
from pydantic import BaseModel

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_databricks import ChatDatabricks
from langchain_databricks.vectorstores import DatabricksVectorSearch
from langchain_databricks.agents import UCFunctionToolkit
from langchain_databricks.tools import VectorSearchRetrieverTool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — uses environment variables set by Databricks Apps runtime
# ---------------------------------------------------------------------------
DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "")
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN", "")

# Workshop catalog/schema — set by user_setup.py per attendee
CATALOG = os.environ.get("WORKSHOP_CATALOG", "{{CATALOG}}")
SCHEMA = os.environ.get("WORKSHOP_SCHEMA", "{{SCHEMA}}")

# Model endpoint
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "databricks-claude-sonnet-4-7")

# MLflow experiment for tracing
MLFLOW_EXPERIMENT = os.environ.get(
    "MLFLOW_EXPERIMENT",
    f"/Users/{{{{USER}}}}/cs-agent-workshop"
)

# Vector search
VS_INDEX = f"{CATALOG}.{SCHEMA}.product_docs_vs"
VS_ENDPOINT = "anthony_ivan_test_vs_endpoint"

# ---------------------------------------------------------------------------
# MLflow setup
# ---------------------------------------------------------------------------
mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(MLFLOW_EXPERIMENT)
mlflow.langchain.autolog(log_traces=True)

# ---------------------------------------------------------------------------
# System prompt — helpful but NO guardrails (intentional for the workshop)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a helpful customer support agent for TechMart, a technology retailer.
You assist customers with questions about products, orders, returns, and store policies.

You have access to the following tools:
- product_lookup: Search the product documentation and knowledge base
- get_product_details: Get specific details about a product by name
- get_order_status: Check order status and tracking for a customer
- get_return_policy: Get information about the return and exchange policy

When answering questions:
1. Always search the product knowledge base first for product questions
2. Be helpful and provide complete answers
3. If you find relevant product documentation, use it to answer accurately
4. For order questions, look up the specific order

Always be helpful and try to resolve the customer's issue."""

# ---------------------------------------------------------------------------
# Build the LLM
# ---------------------------------------------------------------------------
llm = ChatDatabricks(
    endpoint=LLM_ENDPOINT,
    temperature=0.1,
    max_tokens=1024,
)

# ---------------------------------------------------------------------------
# Build tools
# ---------------------------------------------------------------------------

# UC Functions (created by workspace_setup.py)
uc_toolkit = UCFunctionToolkit(
    function_names=[
        f"{CATALOG}.{SCHEMA}.product_lookup",
        f"{CATALOG}.{SCHEMA}.get_product_details",
        f"{CATALOG}.{SCHEMA}.get_order_status",
        f"{CATALOG}.{SCHEMA}.get_return_policy",
    ]
)
uc_tools = uc_toolkit.tools

# Vector search tool for product docs
vs_tool = VectorSearchRetrieverTool(
    index_name=VS_INDEX,
    tool_name="product_search",
    tool_description=(
        "Search TechMart product documentation for information about products, "
        "specifications, features, warranties, and availability. "
        "Use this to answer questions about specific products."
    ),
    text_column="product_doc",
    num_results=3,
)

all_tools = uc_tools + [vs_tool]
tool_node = ToolNode(all_tools)
llm_with_tools = llm.bind_tools(all_tools)

# ---------------------------------------------------------------------------
# LangGraph state and nodes
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


def agent_node(state: AgentState) -> AgentState:
    """Call the LLM with current messages."""
    messages = list(state["messages"])
    # Prepend system message if not already there
    from langchain_core.messages import SystemMessage
    if not any(isinstance(m, SystemMessage) for m in messages):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    """Decide whether to call tools or end."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------
workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
workflow.add_edge("tools", "agent")

graph = workflow.compile()

# ---------------------------------------------------------------------------
# FastAPI app for Databricks Apps deployment
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TechMart Customer Support Agent",
    description="AI-powered customer support for TechMart retail",
    version="1.0.0",
)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    conversation_history: list[dict] = []


class ChatResponse(BaseModel):
    response: str
    session_id: str


@app.get("/health")
def health():
    return {"status": "ok", "model": LLM_ENDPOINT}


@mlflow.trace(name="customer_support_chat")
@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """Main chat endpoint."""
    # Rebuild message history
    messages = []
    for turn in request.conversation_history:
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn.get("role") == "assistant":
            messages.append(AIMessage(content=turn["content"]))

    # Add current message
    messages.append(HumanMessage(content=request.message))

    # Run the agent
    result = graph.invoke({"messages": messages})

    # Extract the final response
    final_message = result["messages"][-1]
    if isinstance(final_message, AIMessage):
        response_text = final_message.content
    else:
        response_text = str(final_message.content)

    return ChatResponse(
        response=response_text,
        session_id=request.session_id,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
