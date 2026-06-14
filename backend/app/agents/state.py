"""LangGraph state schema."""

from typing import Annotated, Any, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class GraphState(TypedDict):
    # Conversation history — add_messages appends new messages rather than replacing
    messages: Annotated[list[BaseMessage], add_messages]

    # Routing result from the router node
    intent: Optional[str]  # "read" | "write" | "clarify"

    # Set by ActionAgent before HIL pause; cleared after execution
    pending_action: Optional[dict[str, Any]]

    # Injected by the chat endpoint when the user responds to a HIL prompt
    hil_decision: Optional[str]  # "confirm" | "cancel"

    # Short-term context — updated as the user references projects/tasks
    current_project_id: Optional[str]
    current_task_id: Optional[str]

    # Session identifiers — set once at session start
    session_id: str
    user_id: str
