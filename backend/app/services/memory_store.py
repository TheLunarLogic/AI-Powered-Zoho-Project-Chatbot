"""Long-term memory helpers — load and save per-user persistent context."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import LongTermMemory

MAX_RECENT_PROJECTS = 5
MAX_FREQUENT_ASSIGNEES = 10  # keep a reasonable cap


async def load_memory(db: AsyncSession, user_id: UUID) -> dict | None:
    """Load the user's long-term memory record.

    Returns a plain dict with four keys, or None on first session.

    Keys:
      last_active_project_id  str | None
      recent_projects         list[str]  — up to 5 project names
      frequent_assignees      list[str]  — repeatedly-used assignee names
    """
    result = await db.execute(
        select(LongTermMemory).where(LongTermMemory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if memory is None:
        return None
    return {
        "last_active_project_id": memory.last_active_project_id,
        "recent_projects": memory.recent_projects or [],
        "frequent_assignees": memory.frequent_assignees or [],
    }


async def save_memory(
    db: AsyncSession,
    user_id: UUID,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
    assignee_name: str | None = None,
) -> None:
    """Upsert the user's long-term memory with updated context.

    - project_id   → stored as last_active_project_id
    - project_name → prepended to recent_projects (max 5, deduped)
    - assignee_name → appended to frequent_assignees if not already present (max 10)

    All arguments are optional; only provided fields update the record.
    """
    result = await db.execute(
        select(LongTermMemory).where(LongTermMemory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()

    if memory is None:
        # First-ever memory record for this user
        recent: list[str] = []
        assignees: list[str] = []
        if project_name:
            recent = [project_name]
        if assignee_name:
            assignees = [assignee_name]
        stmt = pg_insert(LongTermMemory).values(
            user_id=user_id,
            last_active_project_id=project_id,
            recent_projects=recent,
            frequent_assignees=assignees,
        ).on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "last_active_project_id": project_id,
                "recent_projects": recent,
                "frequent_assignees": assignees,
            },
        )
        await db.execute(stmt)
    else:
        # Update existing record
        if project_id is not None:
            memory.last_active_project_id = project_id

        if project_name:
            recent = list(memory.recent_projects or [])
            # Remove duplicates (case-insensitive), prepend latest
            recent = [p for p in recent if p.lower() != project_name.lower()]
            recent = [project_name] + recent
            memory.recent_projects = recent[:MAX_RECENT_PROJECTS]

        if assignee_name:
            assignees = list(memory.frequent_assignees or [])
            if assignee_name.lower() not in [a.lower() for a in assignees]:
                assignees.append(assignee_name)
            memory.frequent_assignees = assignees[:MAX_FREQUENT_ASSIGNEES]

    await db.commit()
