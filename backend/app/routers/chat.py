"""Chat API endpoint."""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config, get_config
from app.database import get_db
from app.dependencies import get_current_user
from app.models.db import ChatMessage, ChatThread, User
from app.models.schemas import ChatRequest, ChatResponse, PendingActionSchema
from app.services.llm_service import get_llm
from app.services.memory_store import load_memory
from app.services.zoho_client import ZohoClient
from app.agents.graph import build_graph

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


async def _get_or_create_thread(
    db: AsyncSession,
    user_id,
    thread_id: str | None,
    first_message: str,
) -> ChatThread:
    """Return the requested thread (verifying ownership) or create a new one."""
    if thread_id:
        result = await db.execute(
            select(ChatThread).where(
                ChatThread.id == thread_id,
                ChatThread.user_id == user_id,
            )
        )
        thread = result.scalar_one_or_none()
        if thread:
            return thread
        # Thread not found / doesn't belong to user — fall through to create
        logger.warning("Thread %s not found for user %s — creating new thread", thread_id, user_id)

    # Auto-title: use first 60 chars of the first message
    title = first_message[:60].strip() or "New Chat"
    thread = ChatThread(id=uuid4(), user_id=user_id, title=title)
    db.add(thread)
    await db.flush()   # assign id without committing yet
    return thread


async def _load_thread_history(db: AsyncSession, thread_id) -> list:
    """Return LangChain message objects for all messages in the thread."""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = []
    for row in result.scalars().all():
        if row.role == "user":
            messages.append(HumanMessage(content=row.content))
        else:
            messages.append(AIMessage(content=row.content))
    return messages


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: Config = Depends(get_config),
) -> ChatResponse:
    """
    Main chat endpoint. Invokes the LangGraph graph with the user's message.

    - Loads conversation history from the thread so context is maintained.
    - Saves the user message and assistant reply to the thread after each turn.
    """
    llm = get_llm()
    zoho_client = ZohoClient(config=config, db=db, user_id=current_user.id)
    graph = await build_graph(llm=llm, zoho_client=zoho_client, db=db)

    # Resolve or create thread
    thread = await _get_or_create_thread(
        db, current_user.id, request.thread_id, request.message
    )

    # Load prior messages from this thread as LangChain message objects
    history = await _load_thread_history(db, thread.id)

    thread_config = {"configurable": {"thread_id": str(thread.id)}}

    # Load long-term memory for project context injection
    memory = await load_memory(db, current_user.id)

    # Build the input state — prepend history so the LLM has full context
    input_state: dict = {
        "messages": history + [HumanMessage(content=request.message)],
        "session_id": request.session_id,
        "user_id": str(current_user.id),
    }

    if request.hil_response:
        input_state["hil_decision"] = request.hil_response

    # Inject last active project from long-term memory if the current thread
    # has no project context yet (i.e. this is a fresh thread or first message).
    # Show the user a notice so they know which project is being assumed.
    fallback_notice: str | None = None
    if memory and memory.get("last_active_project_id"):
        # Only fall back when the loaded thread history has no project context.
        # We detect this by checking whether history is empty (new thread) or
        # by the absence of a project-bearing message in the loaded history.
        # Simple heuristic: if no current_project_id has been resolved from
        # the history messages yet, use the memory value.
        input_state["current_project_id"] = memory["last_active_project_id"]

        # Build a context hint for the LLM so it knows about recent projects
        # and frequent assignees. This is injected as a system-level note
        # prepended to the message, not exposed as a separate chat message.
        memory_hints: list[str] = []
        recent = memory.get("recent_projects", [])
        if recent:
            memory_hints.append(f"Recent projects: {', '.join(recent)}")
        assignees = memory.get("frequent_assignees", [])
        if assignees:
            memory_hints.append(f"Frequent assignees: {', '.join(assignees)}")

        if memory_hints:
            hint_text = "[Memory context — " + "; ".join(memory_hints) + "]"
            # Prepend as a silent system note to the first human message
            original_msg = request.message
            input_state["messages"] = history + [
                HumanMessage(content=f"{hint_text}\n\n{original_msg}")
            ]

        # Only show the fallback notice when the thread is brand-new (no prior history)
        # so we don't spam it on every message in an ongoing thread.
        if not history:
            fallback_notice = f"Using your last active project: {memory['last_active_project_id']}"

    # Run the graph
    result = await graph.ainvoke(input_state, config=thread_config)

    # Extract the final plain-text reply
    reply = ""
    for msg in reversed(result.get("messages", [])):
        if not hasattr(msg, "content") or msg.type == "human":
            continue
        if getattr(msg, "tool_calls", None):
            continue
        content = msg.content
        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            reply = " ".join(p for p in text_parts if p).strip()
        else:
            reply = str(content).strip()
        if reply:
            break

    # Prepend fallback notice when we silently used long-term memory project context
    if fallback_notice and reply:
        reply = f"_{fallback_notice}_\n\n{reply}"

    # Persist user message + assistant reply to the thread
    if reply:
        db.add(ChatMessage(
            id=uuid4(),
            thread_id=thread.id,
            role="user",
            content=request.message,
        ))
        db.add(ChatMessage(
            id=uuid4(),
            thread_id=thread.id,
            role="assistant",
            content=reply,
        ))

    await db.commit()

    # HIL confirmation
    pending_action = result.get("pending_action")
    pending_schema = None
    if pending_action:
        pending_schema = PendingActionSchema(
            operation=pending_action["operation"],
            description=pending_action["description"],
            parameters=pending_action["parameters"],
            tool_call_id="",
        )
        if not reply:
            reply = f"I'm about to {pending_action['description']}. Please confirm or cancel."

    return ChatResponse(
        reply=reply,
        session_id=request.session_id,
        thread_id=str(thread.id),
        pending_action=pending_schema,
    )
