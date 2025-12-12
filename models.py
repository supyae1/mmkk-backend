from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    api_keys = relationship("APIKey", back_populates="workspace")
    accounts = relationship("Account", back_populates="workspace")


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    key = Column(String, unique=True, nullable=False, index=True)
    label = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="api_keys")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    name = Column(String, nullable=False)
    domain = Column(String, nullable=True, index=True)
    industry = Column(String, nullable=True)
    employee_count = Column(Integer, nullable=True)
    stage = Column(String, nullable=True)
    country = Column(String, nullable=True)
    city = Column(String, nullable=True)

    # Scores
    intent_score = Column(Float, default=0.0)
    engagement_score = Column(Float, default=0.0)
    fit_score = Column(Float, default=0.0)
    predictive_score = Column(Float, default=0.0)
    total_score = Column(Float, default=0.0)

    buyer_stage = Column(String, nullable=True)
    last_activity_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="accounts")
    contacts = relationship("Contact", back_populates="account")
    events = relationship("Event", back_populates="account")
    tasks = relationship("Task", back_populates="account")
    alerts = relationship("Alert", back_populates="account")
    opportunities = relationship("Opportunity", back_populates="account")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)

    email = Column(String, nullable=False, index=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    title = Column(String, nullable=True)
    phone = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", back_populates="contacts")
    workspace = relationship("Workspace")


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=True)

    event_type = Column(String, nullable=False)
    source = Column(String, nullable=True)  # channel, utm_source, etc.
    page = Column(String, nullable=True)
    route = Column(String, nullable=True)
    url = Column(String, nullable=True)
    referrer = Column(String, nullable=True)
    ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)

    event_metadata = Column(JSON, nullable=True)
    value = Column(Float, nullable=True)  # revenue or score contribution

    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="events")
    contact = relationship("Contact")
    workspace = relationship("Workspace")


class AnonymousVisit(Base):
    __tablename__ = "anonymous_visits"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    url = Column(String, nullable=False)
    referrer = Column(String, nullable=True)
    ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)

    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=True)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    due_at = Column(DateTime, nullable=True)
    status = Column(String, default="open")
    owner = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", back_populates="tasks")
    contact = relationship("Contact")
    workspace = relationship("Workspace")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=True)

    title = Column(String, nullable=False)
    severity = Column(String, default="medium")  # low/medium/high
    description = Column(Text, nullable=True)
    owner = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", back_populates="alerts")
    contact = relationship("Contact")
    workspace = relationship("Workspace")


class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)

    name = Column(String, nullable=False)
    stage = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    close_date = Column(DateTime, nullable=True)
    probability = Column(Float, nullable=True)
    external_id = Column(String, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", back_populates="opportunities")
    workspace = relationship("Workspace")


class PlaybookRule(Base):
    __tablename__ = "playbook_rules"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    min_intent = Column(Float, nullable=True)
    min_engagement = Column(Float, nullable=True)
    min_total_score = Column(Float, nullable=True)
    trigger_event_type = Column(String, nullable=True)

    # Actions
    create_task = Column(Boolean, default=False)
    create_alert = Column(Boolean, default=False)
    push_to_crm = Column(Boolean, default=False)

    task_title_template = Column(String, nullable=True)
    alert_title_template = Column(String, nullable=True)
    alert_severity = Column(String, nullable=True)  # low/medium/high
    owner = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace")
