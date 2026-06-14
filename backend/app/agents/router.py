"""Router agent — classifies user intent as read, write, or clarify."""

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import GraphState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a router for a Zoho Projects chatbot. Classify the overall intent of the conversation.

Respond with exactly one word — no punctuation, no explanation:

read    → user wants to VIEW, LIST, SHOW, GET, or FIND any of the following:
          - projects (list projects, show my projects, what projects do I have)
          - tasks (list tasks, show tasks, get tasks in a project, show task details, what tasks are there)
          - task details (show task info, get task, describe a task)
          - project members / users / team (who are the members, list members, show team,
            list users in this project, who is in this project, show project members,
            list all members, who are the team members, get project users)
          - task utilisation / workload summaries

write   → user wants to CREATE, UPDATE, or DELETE a TASK (not a project):
          - create a task, add a task
          - update a task, change a task, edit a task
          - delete a task, remove a task

clarify → ONLY use this when:
          - the user wants to create, update, delete, or archive a PROJECT (not a task)
          - the user wants to ADD, REMOVE, or INVITE users/team members (i.e. change membership)
          - the user wants to manage milestones, sprints, or timesheets
          - the request is completely unclear or unrelated to Zoho Projects

EXAMPLES:
  "List all tasks in the Test project"        → read
  "Show tasks"                                → read
  "What tasks are in project Alpha?"          → read
  "Show me task details for task 42"          → read
  "Who are the project members?"              → read
  "List all members of this project"          → read
  "Show team members"                         → read
  "List users in this project"                → read
  "Who is in the Test project?"               → read
  "Show project members"                      → read
  "What projects do I have?"                  → read
  "Show tasks in that project"                → read
  "Create a task called Fix login bug"        → write
  "Update task 5 due date"                    → write
  "Delete task 12"                            → write
  "Assign task X to Navneet"                  → write
  "Create a new project"                      → clarify
  "Delete the Alpha project"                  → clarify
  "Add John to this project"                  → clarify
  "Remove a user from the team"               → clarify

IMPORTANT: The rule about listing/showing project members or users is ALWAYS read,
regardless of earlier messages. Even if the previous turn was a write operation,
a request to VIEW or LIST members is read — not write and not clarify.

IMPORTANT: If earlier messages show a write intent (create/update/delete task),
and the latest message is providing information to complete that write (e.g. a project ID, task name),
still classify as: write — but ONLY if the latest message is clearly continuing that write.
If the latest message is a new, distinct read request (list tasks, show members, etc.),
classify it as: read."""


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


async def router_node(state: GraphState, llm: BaseChatModel) -> dict:
    """Classify the user's message and set the intent in state."""
    messages = state["messages"]
    last_message = messages[-1]

    # Build a short conversation summary for the router so it has context.
    # Include up to the last 4 human messages to capture multi-turn write flows.
    human_turns = [m for m in messages if m.type == "human"][-4:]
    conversation_context = "\n".join(
        f"User: {_extract_text(m.content)}" for m in human_turns
    )

    response = await llm.ainvoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=conversation_context),
    ])

    # Normalise — DeepSeek can return list-typed content
    raw = _extract_text(response.content).strip().lower()

    # Take only the first word in case the model adds extra text
    intent = raw.split()[0] if raw.split() else "clarify"

    if intent not in {"read", "write", "clarify"}:
        intent = "clarify"

    logger.info("Routed to: %s (raw=%r)", intent, raw)
    return {"intent": intent}
