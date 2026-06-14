"""Chat thread endpoints — create, list, and fetch messages for a thread."""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.db import ChatMessage, ChatThread, User
from app.models.schemas import ThreadCreate, ThreadMessagesResponse, ThreadMessageResponse, ThreadResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/threads", tags=["threads"])


@router.post("", response_model=ThreadResponse, status_code=201)
async def create_thread(
    body: ThreadCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Create a new chat thread for the authenticated user."""
    thread = ChatThread(
        id=uuid4(),
        user_id=current_user.id,
        title=body.title or "New Chat",
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    logger.info("Created thread %s for user %s", thread.id, current_user.id)
    return ThreadResponse(
        id=str(thread.id),
        title=thread.title,
        created_at=thread.created_at,
    )


@router.get("", response_model=list[ThreadResponse])
async def list_threads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ThreadResponse]:
    """List all threads for the authenticated user, newest first."""
    result = await db.execute(
        select(ChatThread)
        .where(ChatThread.user_id == current_user.id)
        .order_by(ChatThread.created_at.desc())
    )
    threads = result.scalars().all()
    return [
        ThreadResponse(id=str(t.id), title=t.title, created_at=t.created_at)
        for t in threads
    ]


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a thread and all its messages. 404 if not owned by the current user."""
    from fastapi import HTTPException

    result = await db.execute(
        select(ChatThread).where(
            ChatThread.id == thread_id,
            ChatThread.user_id == current_user.id,
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    await db.delete(thread)   # cascade deletes ChatMessage rows automatically
    await db.commit()
    logger.info("Deleted thread %s for user %s", thread_id, current_user.id)


@router.get("/{thread_id}/messages", response_model=ThreadMessagesResponse)
async def get_thread_messages(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadMessagesResponse:
    """Return all messages in a thread (oldest first). 404 if thread not owned by user."""
    from fastapi import HTTPException

    result = await db.execute(
        select(ChatThread).where(
            ChatThread.id == thread_id,
            ChatThread.user_id == current_user.id,
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.created_at.asc())
    )
    msgs = msg_result.scalars().all()
    return ThreadMessagesResponse(
        thread_id=thread_id,
        messages=[
            ThreadMessageResponse(
                id=str(m.id),
                role=m.role,
                content=m.content,
                created_at=m.created_at,
            )
            for m in msgs
        ],
    )
