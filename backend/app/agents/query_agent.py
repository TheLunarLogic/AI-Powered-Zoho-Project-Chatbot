"""Query agent — handles all read operations using Zoho read tools."""

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from app.agents.state import GraphState

logger = logging.getLogger(__name__)

QUERY_SYSTEM_PROMPT = (
    "You are a helpful Zoho Projects assistant. "
    "Answer the user's questions by calling the available tools. "
    "When the user refers to 'that project' or 'the first one', "
    "use the project they most recently mentioned. "
    "Format responses clearly and concisely. "
    "Always call a tool to fetch live data — never guess or make up project names or IDs."
)


def build_query_agent(llm: BaseChatModel, tools: list):
    """Return a compiled ReAct agent for read operations.

    We pass the system prompt as a plain string — create_react_agent accepts
    either a string or a SystemMessage for state_modifier and internally
    prepends it correctly.  Passing a SystemMessage object can cause it to
    land in the wrong position with certain LangChain/LangGraph versions.
    """
    logger.info("Building query agent with %d tools: %s", len(tools), [t.name for t in tools])
    return create_react_agent(llm, tools, state_modifier=QUERY_SYSTEM_PROMPT)


async def query_agent_node(state: GraphState, agent) -> dict:
    """Run the query agent and update the current project/task context."""
    logger.info("query_agent_node invoked with %d messages", len(state["messages"]))

    result = await agent.ainvoke({"messages": state["messages"]})

    all_messages = result["messages"]
    logger.info("query_agent returned %d messages", len(all_messages))

    # Full per-message diagnostics — shows exactly what create_react_agent produced
    for i, msg in enumerate(all_messages):
        tc = getattr(msg, "tool_calls", None)
        content_preview = str(msg.content)[:300]
        logger.info(
            "MSG %d | %s | tool_calls=%s | content=%s",
            i, type(msg).__name__, tc, content_preview,
        )
        # Extra detail for tool execution
        if isinstance(msg, AIMessage) and tc:
            for call in tc:
                logger.info("Executing tool: %s with args: %s", call["name"], call.get("args", {}))
        if isinstance(msg, ToolMessage):
            logger.info("Tool result [%s]: %s", msg.name, str(msg.content)[:500])

    # Only return messages that are new (not already in the parent graph state)
    # This avoids duplicating the user's own messages in state.
    existing_ids = {id(m) for m in state["messages"]}
    new_messages = [m for m in all_messages if id(m) not in existing_ids]
    logger.info("Appending %d new messages to parent state", len(new_messages))

    updates: dict = {"messages": new_messages}

    # Extract the most recently mentioned project_id / task_id from tool calls
    for msg in reversed(all_messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if "project_id" in tc.get("args", {}):
                    updates["current_project_id"] = tc["args"]["project_id"]
                    logger.info("Updated current_project_id: %s", tc["args"]["project_id"])
                if "task_id" in tc.get("args", {}):
                    updates["current_task_id"] = tc["args"]["task_id"]
                    logger.info("Updated current_task_id: %s", tc["args"]["task_id"])
            break

    return updates
