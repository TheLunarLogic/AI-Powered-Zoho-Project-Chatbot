"""Action agent — handles create/update/delete operations with HIL confirmation."""

import json
import logging
import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.state import GraphState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Zoho Projects assistant. You can ONLY perform the following operations on TASKS inside existing projects:

SUPPORTED WRITE OPERATIONS:
- create_task: Create a new task inside an existing project
- update_task: Update fields on an existing task
- delete_task: Delete an existing task

NOT SUPPORTED — do NOT attempt these:
- Creating, updating, deleting, or archiving PROJECTS
- Creating or managing users, teams, or roles
- Managing milestones, sprints, or timesheets
- Any other operation not in the supported list above

If the user requests any unsupported operation, respond with a JSON object using operation "unsupported":
{"operation": "unsupported", "description": "<explain what was requested and that it is not supported, suggest what IS supported>", "parameters": {}}

Otherwise respond with ONLY a valid JSON object — no markdown, no explanation, no code blocks:
{
  "operation": "create_task" | "update_task" | "delete_task",
  "description": "<human-readable summary of what will happen>",
  "parameters": {
    <exact keyword arguments for the tool>
  }
}

For create_task, parameters must include at minimum: project_id, name
  - project_id: use the project name, key (e.g. CH-1), or numeric ID — whichever the user provided
  - assignee_id: use the assignee's full name as provided by the user (e.g. "Navneet Garg") — the system will resolve it to an ID
For update_task, parameters must include: project_id, task_id, fields
For delete_task, parameters must include: project_id, task_id

If you do not have enough information (e.g. missing project or task name), still return JSON but set operation to "clarify" and explain what is missing in the description field."""

_CLARIFY_RESPONSE = AIMessage(
    content="I need more details before I can do that. "
    "Please tell me the project name and any other relevant details (task name, assignee, due date, etc.)."
)

# The only write operations this application implements.
# Any operation not in this set is rejected before reaching tool execution.
SUPPORTED_WRITE_OPERATIONS: frozenset[str] = frozenset({
    "create_task",
    "update_task",
    "delete_task",
})


class PendingAction(BaseModel):
    """Describes a write operation that requires user confirmation before execution."""

    operation: str = Field(
        description="The tool to call: 'create_task', 'update_task', or 'delete_task'."
    )
    description: str = Field(
        description="Human-readable summary of exactly what will happen, shown to the user for confirmation."
    )
    parameters: dict[str, Any] = Field(
        description="The exact keyword arguments to pass to the tool when the user confirms."
    )


def _extract_text(content) -> str:
    """Normalise message content to plain text regardless of type."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(p for p in parts if p).strip()
    return str(content)


def _extract_json(text: str) -> str:
    """Strip markdown fences and return the first JSON object found."""
    # Remove ```json ... ``` or ``` ... ``` wrappers
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    # Find the first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _format_tool_result(operation: str, result: dict) -> str:
    """Return a concise, user-friendly confirmation message from a tool result dict."""
    if isinstance(result, dict) and result.get("error"):
        return f"⚠️ Operation failed: {result['error']}"

    if operation == "create_task":
        name = result.get("name", "")
        task_id = result.get("id_string") or result.get("id", "")
        if name and task_id:
            return f"✅ Task created successfully.\n\n**Task:** {name}\n**Task ID:** {task_id}"
        if name:
            return f"✅ Successfully created task '{name}'."
        return "✅ Task created successfully."

    if operation == "update_task":
        name = result.get("name", "")
        task_id = result.get("id_string") or result.get("id", "")
        if name and task_id:
            return f"✅ Task updated successfully.\n\n**Task:** {name}\n**Task ID:** {task_id}"
        return "✅ Task updated successfully."

    if operation == "delete_task":
        task_id = result.get("task_id", "")
        if task_id:
            return f"✅ Task {task_id} deleted successfully."
        return "✅ Task deleted successfully."

    return "✅ Operation completed successfully."


async def action_agent_node(
    state: GraphState,
    llm: BaseChatModel,
    tools: list,
    zoho_client,
    portal_id: str,
) -> dict:
    """
    First call: ask the LLM to determine the action, build a PendingAction, and pause.
    Resume call (after HIL confirm): actually execute the tool.
    """
    tool_names = [t.name for t in tools]
    logger.info("Write tools available: %s", tool_names)

    # Resume path: user confirmed — execute the pending action
    if state.get("hil_decision") == "confirm" and state.get("pending_action"):
        pending = state["pending_action"]
        tool_map = {t.name: t for t in tools}
        tool = tool_map.get(pending["operation"])
        if tool is None or pending["operation"] not in SUPPORTED_WRITE_OPERATIONS:
            logger.warning("Resume path: unsupported or unknown operation '%s'", pending["operation"])
            return {
                "messages": [AIMessage(content=f"Operation '{pending['operation']}' is not supported. I can create, update, or delete tasks inside existing projects.")],
                "pending_action": None,
                "hil_decision": None,
            }

        params: dict = dict(pending["parameters"])

        # --- Coerce all ID fields to str (LLM often emits integers) ---
        for id_field in ("project_id", "task_id"):
            if id_field in params:
                params[id_field] = str(params[id_field])

        # Note: assignee resolution for create_task is handled inside write_tools.py.
        # update_task also resolves assignee internally (name → zpuid → person_responsible).
        # No pre-processing needed here.

        logger.info("Executing operation=%s params=%s", pending["operation"], params)
        try:
            result = await tool.ainvoke(params)
        except Exception:
            logger.exception("tool.ainvoke failed for operation=%s", pending["operation"])
            return {
                "messages": [AIMessage(content="⚠️ The operation could not be completed due to an unexpected error. Please try again.")],
                "pending_action": None,
                "hil_decision": None,
            }

        # Format a concise user-facing confirmation instead of dumping the raw API object
        reply = _format_tool_result(pending["operation"], result)
        return {
            "messages": [AIMessage(content=reply)],
            "pending_action": None,
            "hil_decision": None,
            # Persist the project so memory_writer can update last_active_project_id
            "current_project_id": params.get("project_id") or state.get("current_project_id"),
        }

    # First call: ask the model to produce a JSON PendingAction.
    # Pass full conversation history so the model can use project IDs / task names
    # provided in earlier turns.
    messages = state["messages"]
    history_text = []
    for m in messages:
        role = "User" if m.type == "human" else "Assistant"
        history_text.append(f"{role}: {_extract_text(m.content)}")
    conversation = "\n".join(history_text)

    logger.info("Executing operation with conversation context (%d turns)", len(messages))

    response = await llm.ainvoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=conversation),
    ])

    # Normalise content — DeepSeek returns list[dict] for tool-call responses
    raw_content = response.content
    if isinstance(raw_content, list):
        # Extract text blocks only
        raw_content = " ".join(
            block.get("text", "")
            for block in raw_content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()

    logger.info("Raw action agent response: %s", raw_content)

    # Parse JSON
    try:
        json_str = _extract_json(str(raw_content))
        data = json.loads(json_str)
        pending = PendingAction(**data)
    except Exception:
        logger.exception("Failed to parse pending action from: %s", raw_content)
        return {"messages": [_CLARIFY_RESPONSE]}

    logger.info("Pending action raw: %s", pending)

    # If the model said it needs clarification, ask the user instead of queuing an action
    if pending.operation == "clarify":
        logger.info("Action agent requesting clarification: %s", pending.description)
        return {"messages": [AIMessage(content=pending.description)]}

    # Capability gate — reject operations that have no implemented tool
    if pending.operation not in SUPPORTED_WRITE_OPERATIONS:
        logger.info("Unsupported operation requested: '%s'", pending.operation)
        msg = pending.description if pending.description else (
            f"The operation '{pending.operation}' is not supported. "
            "I can create, update, or delete tasks inside existing projects."
        )
        return {"messages": [AIMessage(content=msg)]}

    logger.info("Action agent built pending action: %s", pending.operation)
    return {
        "pending_action": pending.model_dump(),
        "hil_decision": None,
    }
