"""
Utility functions for the TechMart CS agent.
Adapted from the official agent-langgraph template utils.py.
"""
import logging
from typing import Any, AsyncGenerator, AsyncIterator, Optional

from langchain_core.messages import AIMessageChunk, ToolMessage
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentStreamEvent,
    create_text_delta,
    output_to_responses_items_stream,
)
import json

log = logging.getLogger(__name__)


def get_messages_and_context(request: ResponsesAgentRequest):
    """Extract LangChain messages and context dict from a ResponsesAgentRequest."""
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

    messages = []
    for item in request.input or []:
        role    = getattr(item, "role", None)
        content = getattr(item, "content", "")
        if isinstance(content, list):
            # Extract text from content blocks
            text_parts = [
                c.get("text", "") if isinstance(c, dict) else getattr(c, "text", "")
                for c in content
            ]
            content = " ".join(p for p in text_parts if p)
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
        elif role == "system":
            messages.append(SystemMessage(content=content))

    context = {}
    if request.context:
        context["conversation_id"] = getattr(request.context, "conversation_id", None)
        context["user_id"]         = getattr(request.context, "user_id", None)

    return messages, context


async def process_agent_astream_events(
    async_stream: AsyncIterator[Any],
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    """Process LangGraph astream events into ResponsesAgentStreamEvent objects."""
    async for event in async_stream:
        if event[0] == "updates":
            for node_data in event[1].values():
                msgs = node_data.get("messages", [])
                if msgs:
                    for msg in msgs:
                        if isinstance(msg, ToolMessage) and not isinstance(msg.content, str):
                            msg.content = json.dumps(msg.content)
                    for item in output_to_responses_items_stream(msgs):
                        yield item
        elif event[0] == "messages":
            try:
                chunk = event[1][0]
                if isinstance(chunk, AIMessageChunk) and (content := chunk.content):
                    yield ResponsesAgentStreamEvent(
                        **create_text_delta(delta=content, item_id=chunk.id)
                    )
            except Exception as e:
                log.exception("Error processing stream event: %s", e)
