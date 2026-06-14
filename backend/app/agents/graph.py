"""LangGraph graph assembly."""

import logging
from functools import partial

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.action_agent import action_agent_node
from app.agents.hil_node import hil_node
from app.agents.memory_writer import memory_writer_node
from app.agents.query_agent import build_query_agent, query_agent_node
from app.agents.router import router_node
from app.agents.state import GraphState
from app.services.zoho_client import ZohoClient
from app.tools.read_tools import make_read_tools
from app.tools.write_tools import make_write_tools

logger = logging.getLogger(__name__)

# MemorySaver keeps conversation state in-process.
# This means state is lost on server restart, but is sufficient for the
# assignment. Noted as a known limitation in README.
_checkpointer = MemorySaver()


def _route_after_router(state: GraphState) -> str:
    intent = state.get("intent", "clarify")
    if intent == "read":
        return "query_agent"
    if intent == "write":
        return "action_agent"
    return "clarify"


def _route_after_action(state: GraphState) -> str:
    # If there's a pending action and no decision yet, pause for HIL
    if state.get("pending_action") and not state.get("hil_decision"):
        return "hil_confirmation"
    return "memory_writer"


def _route_after_hil(state: GraphState) -> str:
    if state.get("hil_decision") == "confirm":
        return "action_agent"
    return "memory_writer"


async def clarify_node(state: GraphState) -> dict:
    return {
        "messages": [AIMessage(content="Could you clarify what you'd like to do? I can list projects, show tasks, or help create/update/delete tasks.")]
    }


async def build_graph(llm: BaseChatModel, zoho_client: ZohoClient, db: AsyncSession):
    """Build and compile the LangGraph conversation graph."""
    portal_id = await zoho_client.get_portal_id()
    read_tools = make_read_tools(zoho_client, portal_id)
    write_tools = make_write_tools(zoho_client, portal_id)

    query_agent = build_query_agent(llm, read_tools)

    graph = StateGraph(GraphState)

    graph.add_node("router", partial(router_node, llm=llm))
    graph.add_node("query_agent", partial(query_agent_node, agent=query_agent))
    graph.add_node("action_agent", partial(action_agent_node, llm=llm, tools=write_tools, zoho_client=zoho_client, portal_id=portal_id))
    graph.add_node("hil_confirmation", hil_node)
    graph.add_node("memory_writer", partial(memory_writer_node, db=db))
    graph.add_node("clarify", clarify_node)

    graph.set_entry_point("router")
    graph.add_conditional_edges("router", _route_after_router)
    graph.add_edge("query_agent", "memory_writer")
    graph.add_conditional_edges("action_agent", _route_after_action)
    graph.add_conditional_edges("hil_confirmation", _route_after_hil)
    graph.add_edge("memory_writer", END)
    graph.add_edge("clarify", END)

    checkpointer = _checkpointer

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["hil_confirmation"],
    )
