"""SQLAlchemy ORM models."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import BOOLEAN, TIMESTAMP, VARCHAR, Boolean, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_zoho_user_id", "zoho_user_id", unique=True),
        Index("ix_users_email", "email", unique=True),
    )

    zoho_user_id: Mapped[str] = mapped_column(VARCHAR(64), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(VARCHAR(255), nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(VARCHAR(255), nullable=True)

    token: Mapped[Optional["OAuthToken"]] = relationship(
        "OAuthToken", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[List["Session"]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    long_term_memory: Mapped[Optional["LongTermMemory"]] = relationship(
        "LongTermMemory", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    chat_threads: Mapped[List["ChatThread"]] = relationship(
        "ChatThread", back_populates="user", cascade="all, delete-orphan"
    )


class OAuthToken(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "oauth_tokens"
    __table_args__ = (Index("ix_oauth_tokens_user_id", "user_id", unique=True),)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    refresh_token: Mapped[str] = mapped_column(String, nullable=False)
    token_type: Mapped[str] = mapped_column(VARCHAR(32), nullable=False, default="Bearer")
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    scopes: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="token")


class Session(UUIDMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_session_token", "session_token", unique=True),
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_token: Mapped[str] = mapped_column(VARCHAR(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    last_active_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped["User"] = relationship("User", back_populates="sessions")


class LongTermMemory(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "long_term_memory"
    __table_args__ = (Index("ix_long_term_memory_user_id", "user_id", unique=True),)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    last_active_project_id: Mapped[Optional[str]] = mapped_column(VARCHAR(64), nullable=True)
    # Human-readable project names — last 5 distinct projects the user interacted with.
    # Stored as a JSON array of strings, e.g. ["Test", "Backend", "Config"]
    recent_projects: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Names of assignees repeatedly used in task creation — kept simple, no scoring.
    # Stored as a JSON array of strings, e.g. ["Navneet", "Alice"]
    frequent_assignees: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    user: Mapped["User"] = relationship("User", back_populates="long_term_memory")


class ChatThread(UUIDMixin, Base):
    """A named conversation thread belonging to one user."""

    __tablename__ = "chat_threads"
    __table_args__ = (
        Index("ix_chat_threads_user_id", "user_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False, default="New Chat")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="chat_threads")
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="thread", cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(UUIDMixin, Base):
    """A single message (user or assistant) inside a ChatThread."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_thread_id", "thread_id"),
    )

    thread_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(VARCHAR(16), nullable=False)   # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    thread: Mapped["ChatThread"] = relationship("ChatThread", back_populates="messages")
