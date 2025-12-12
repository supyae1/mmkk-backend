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
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, default="Default Workspace")
    created_at = Column(DateTime, default=datetime.utcnow)

    api_keys = relationship("APIKey", back_populates="workspace")
    accounts = relationship("Account", back_populates="workspace")


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    key = Column(String, nullable=False, unique=True, index=True)
    label = Column(String, default="Default key")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="api_keys")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    name = Column(String, nullable=False)
    domain = Column(String, nullable=True, index=True)
    industry = Column(String, nullable=True)
    employee_range = Column(String, nullable=True)
    country = Column(String, nullable=True)

    intent_score = Column(Float, default=0.0)
    fit_score = Column(Float, default=0.0)
    engagement_score = Column(Float, default=0.0)
    stage = Column(String, default="unknown")  # cold/warm/hot, etc.

    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="accounts")
    contacts = relationship("Contact", back_populates="account")
    events = relationship("Event", back_populates="account")
    tasks = relationship("Task", back_populates="account")
    alerts = relationship("Alert", back_populates="account")
    anon_visits = relationship("AnonymousVisit", back_populates="account")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)

    email = Column(String, nullable=True, index=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    title = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="contacts")


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)

    event_type = Column(String, nullable=False)  # page_view, form_submit, etc
    source = Column(String, nullable=True)  # web, ad, crm, etc

    url = Column(Text, nullable=True)
    path = Column(String, nullable=True)
    referrer = Column(Text, nullable=True)

    utm = Column(JSON, nullable=True)
    metadata = Column(JSON, nullable=True)

    ip = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)

    anonymous_id = Column(String, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="events")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="open")  # open/done
    priority = Column(String, default="normal")  # low/normal/high
    due_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="tasks")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)

    severity = Column(String, default="low")  # low/med/high
    category = Column(String, default="signal")  # risk, signal, etc
    message = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="alerts")


class AnonymousVisit(Base):
    __tablename__ = "anonymous_visits"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)

    anonymous_id = Column(String, nullable=False, index=True)
    ip = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)

    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    visit_count = Column(Integer, default=1)

    utm_first = Column(JSON, nullable=True)
    utm_last = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="anon_visits")


class IpCompanyMap(Base):
    __tablename__ = "ip_company_map"

    id = Column(String, primary_key=True, default=_uuid)
    ip = Column(String, nullable=False, unique=True, index=True)

    company_name = Column(String, nullable=True)
    domain = Column(String, nullable=True, index=True)
    industry = Column(String, nullable=True)
    employee_range = Column(String, nullable=True)
    country = Column(String, nullable=True)

    raw = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)

    name = Column(String, nullable=False)
    stage = Column(String, default="pipeline")
    amount = Column(Float, default=0.0)
    probability = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)


class RevenueAttributionTouch(Base):
    __tablename__ = "revenue_attribution_touches"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    opportunity_id = Column(String, ForeignKey("opportunities.id"), nullable=True)

    touch_type = Column(String, nullable=False)  # first_touch, last_touch, touch
    channel = Column(String, nullable=True)
    source = Column(String, nullable=True)
    campaign = Column(String, nullable=True)
    content = Column(String, nullable=True)

    event_id = Column(String, ForeignKey("events.id"), nullable=True)
    weight = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)


class PlaybookRule(Base):
    __tablename__ = "playbook_rules"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    # Simple rule config (extend later)
    min_intent_score = Column(Float, default=0.0)
    min_fit_score = Column(Float, default=0.0)
    min_engagement_score = Column(Float, default=0.0)

    recommended_action = Column(String, nullable=False)  # e.g. "Call within 24h"
    created_at = Column(DateTime, default=datetime.utcnow)
