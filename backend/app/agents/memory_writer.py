"""Memory writer node — persists project/assignee context to long-term memory.

Runs at the end of every graph turn (after query_agent or action_agent).
Keeps it simple: no LLM calls, no summarisation, no scoring.
"""

import logging
from uuid import UUID

from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import GraphState
from app.services.memory_store import save_memory

logger = logging.getLogger(__name__)


def _extract_project_name_from_messages(messages: list) -> str | None:
    """Scan tool result messages for a project name.

    list_projects returns a list of dicts with a "name" key.
    list_tasks / get_task_details are called with a project_id arg — we look
    at the AIMessage tool_calls to find the project_id we already resolved,
    but for the *name* we check ToolMessages from list_projects calls.
    """
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        # list_projects tool returns a list of project dicts
        content = msg.content
        if isinstance(content, list) and content and isinstance(content[0], dict):
            name = content[0].get("name")
            if name:
                return str(name)
        # Sometimes the content is a JSON string — skip for simplicity
    return None


def _extract_assignee_from_messages(messages: list) -> str | None:
    """Look for assignee_id in the most recent AIMessage tool_call args."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                args = tc.get("args", {})
                if "assignee_id" in args:
                    assignee = args["assignee_id"]
                    if assignee:
                        return str(assignee)
    return None


async def memory_writer_node(
    state: GraphState,
    db: AsyncSession,
) -> dict:
    """Persist current project and assignee context to long-term memory."""
    try:
        user_id = UUID(state["user_id"])
        project_id: str | None = state.get("current_project_id")
        messages = state.get("messages", [])

        # Try to find the project name from tool responses so we can store
        # a human-readable name in recent_projects.
        project_name = _extract_project_name_from_messages(messages)

        # Try to capture the assignee used in this turn (for write operations)
        assignee_name = _extract_assignee_from_messages(messages)

        # Only write to DB if we have something new to save
        if project_id or project_name or assignee_name:
            await save_memory(
                db,
                user_id,
                project_id=project_id,
                project_name=project_name,
                assignee_name=assignee_name,
            )
            logger.info(
                "Memory updated for user %s: project_id=%s project_name=%s assignee=%s",
                user_id, project_id, project_name, assignee_name,
            )

    except Exception:
        logger.exception("Memory writer failed — continuing without saving memory")

    return {}
