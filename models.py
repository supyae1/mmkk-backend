# models.py
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# IMPORTANT:
# Your Supabase tables do NOT have updated_at (Render log proves it).
# So we REMOVE updated_at from ORM models to avoid Postgres crashing at startup.


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, default="Default Workspace")
    created_at = Column(DateTime, default=datetime.utcnow)

    api_keys = relationship("APIKey", back_populates="workspace")


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)

    key = Column(String, nullable=False, unique=True, index=True)
    label = Column(String, default="Default demo key")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="api_keys")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    domain = Column(String, nullable=True, index=True)
    owner = Column(String, nullable=True)
    country = Column(String, nullable=True)
    industry = Column(String, nullable=True)

    fit_score = Column(Float, default=0.0)
    intent_score = Column(Float, default=0.0)
    engagement_score = Column(Float, default=0.0)
    stage = Column(String, default="cold")

    created_at = Column(DateTime, default=datetime.utcnow)


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True, index=True)

    email = Column(String, nullable=True, index=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    title = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)

    account_id = Column(String, ForeignKey("accounts.id"), nullable=True, index=True)
    anonymous_id = Column(String, nullable=True, index=True)
    email = Column(String, nullable=True, index=True)

    event_type = Column(String, nullable=False)  # page_view, click, form_submit, booking, purchase, etc
    url = Column(Text, nullable=True)
    path = Column(String, nullable=True)
    referrer = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    ip = Column(String, nullable=True)

    utm = Column(JSON, nullable=True)
    channel = Column(String, nullable=True)
    metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class AnonymousVisit(Base):
    __tablename__ = "anonymous_visits"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)

    anonymous_id = Column(String, nullable=False, index=True)
    ip = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)

    url = Column(Text, nullable=True)
    referrer = Column(Text, nullable=True)

    company_guess = Column(String, nullable=True)
    raw = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True, index=True)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="open")
    priority = Column(String, default="normal")

    created_at = Column(DateTime, default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True, index=True)

    severity = Column(String, default="low")
    category = Column(String, default="signal")
    message = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)


# This fixes your Render crash:
# ImportError: cannot import name 'IpCompanyMap' from 'models'
class IpCompanyMap(Base):
    __tablename__ = "ip_company_map"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, nullable=True, index=True)

    ip = Column(String, nullable=False, unique=True, index=True)
    company_name = Column(String, nullable=True)
    domain = Column(String, nullable=True, index=True)
    country = Column(String, nullable=True)
    city = Column(String, nullable=True)
    source = Column(String, nullable=True)
    raw = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
