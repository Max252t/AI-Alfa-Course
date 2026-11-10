import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

EMBEDDING_DIM = 768


def _uuid():
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tg_id_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tz: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_from: Mapped[int] = mapped_column(Integer, default=22)
    quiet_to: Mapped[int] = mapped_column(Integer, default=9)
    ab_group: Mapped[str] = mapped_column(String(1), default="B")
    last_proactive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[dict] = mapped_column(JSONB, default=dict)


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    legal_form: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tax_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    main_task: Mapped[str | None] = mapped_column(String(128), nullable=True)
    experience: Mapped[str | None] = mapped_column(String(32), nullable=True)
    time_budget: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slot_confidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    ext_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    stage: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_ext_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    popularity: Mapped[float] = mapped_column(Float, default=0.0)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('russian', text)", persisted=True)
    )

    __table_args__ = (Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),)


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    ext_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    material_ext_id: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(32))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DialogTurn(Base):
    __tablename__ = "dialog_turns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    text_masked: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(Text)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freq: Mapped[str | None] = mapped_column(String(16), nullable=True)
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    interval: Mapped[int] = mapped_column(Integer, default=1)
    send_time: Mapped[str] = mapped_column(String(5), default="10:00")
    lead_days: Mapped[int] = mapped_column(Integer, default=0)
    material_ext_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tax_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecShown(Base):
    __tablename__ = "recs_shown"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    material_ext_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reaction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
