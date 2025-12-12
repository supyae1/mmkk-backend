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

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    api_keys = relationship("APIKey", back_populates="workspace")


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    key = Column(String, nullable=False, unique=True)
    label = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="api_keys")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    name = Column(String, nullable=False)
    domain = Column(String, nullable=True)
    owner = Column(String, nullable=True)
    country = Column(String, nullable=True)
    industry = Column(String, nullable=True)

    stage = Column(String, nullable=True)

    intent_score = Column(Float, default=0.0)
    fit_score = Column(Float, default=0.0)
    engagement_score = Column(Float, default=0.0)
    predictive_score = Column(Float, default=0.0)
    total_score = Column(Float, default=0.0)
    buyer_stage = Column(String, nullable=True)

    last_event_at = Column(DateTime, nullable=True)
    last_source = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace")

    contacts = relationship("Contact", back_populates="account", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="account", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="account", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="account", cascade="all, delete-orphan")
    anon_visits = relationship("AnonymousVisit", back_populates="account", cascade="all, delete-orphan")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)

    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    title = Column(String, nullable=True)
    phone = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace")
    account = relationship("Account", back_populates="contacts")


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=True)

    event_type = Column(String, nullable=False)  # e.g. "pageview", "form_submit", etc.
    source = Column(String, nullable=True)  # website, outbound, crm, email, etc.
    page = Column(String, nullable=True)
    route = Column(String, nullable=True)
    url = Column(String, nullable=True)
    event_metadata = Column(JSON, nullable=True)

    value = Column(Float, nullable=True)
    duration = Column(Integer, nullable=True)

    intent_score = Column(Float, default=0.0)
    engagement_score = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace")
    account = relationship("Account", back_populates="events")
    contact = relationship("Contact")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="open")  # open, in_progress, done
    owner = Column(String, nullable=True)
    due_at = Column(DateTime, nullable=True)
    source = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace")
    account = relationship("Account", back_populates="tasks")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)

    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    type = Column(String, nullable=True)  # score_spike, churn_risk, etc.
    severity = Column(String, nullable=True)  # low, medium, high
    is_read = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace")
    account = relationship("Account", back_populates="alerts")


class AnonymousVisit(Base):
    __tablename__ = "anonymous_visits"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)

    ip = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)
    url = Column(String, nullable=True)
    referrer = Column(String, nullable=True)
    country = Column(String, nullable=True)
    city = Column(String, nullable=True)
    company_guess = Column(String, nullable=True)
    raw = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace")
    account = relationship("Account", back_populates="anon_visits")


class IpCompanyMap(Base):
    __tablename__ = "ip_company_map"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    ip = Column(String, nullable=False)
    company_name = Column(String, nullable=True)
    domain = Column(String, nullable=True)
    country = Column(String, nullable=True)
    city = Column(String, nullable=True)
    source = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace")


# -----------------------
# CRM / Opportunities / Playbooks (extensions)
# -----------------------

class CRMConnection(Base):
    __tablename__ = "crm_connections"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    provider = Column(String, nullable=False)  # "hubspot", "salesforce", etc.
    name = Column(String, nullable=True)

    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    config = Column(JSON, nullable=True)   # <- OK

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace")


class ExternalObjectMap(Base):
    # Maps external CRM objects to internal objects.
    __tablename__ = "external_object_map"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    provider = Column(String, nullable=False)
    external_object_type = Column(String, nullable=False)  # account, contact, opportunity
    external_id = Column(String, nullable=False)

    internal_object_type = Column(String, nullable=False)  # account, contact, opportunity
    internal_id = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace")


class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)

    name = Column(String, nullable=False)
    amount = Column(Float, nullable=True)
    currency = Column(String, nullable=True)

    stage = Column(String, nullable=True)   # e.g. "open", "proposal", "won", "lost"
    status = Column(String, nullable=True)  # "open", "won", "lost"

    close_date = Column(DateTime, nullable=True)
    source = Column(String, nullable=True)  # "crm", "manual", etc.
    external_id = Column(String, nullable=True)  # CRM opportunity id

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace")
    account = relationship("Account")
    touches = relationship("RevenueAttributionTouch", back_populates="opportunity", cascade="all, delete-orphan")


class RevenueAttributionTouch(Base):
    __tablename__ = "revenue_attribution_touches"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    opportunity_id = Column(String, ForeignKey("opportunities.id"), nullable=False)

    event_id = Column(String, ForeignKey("events.id"), nullable=True)
    anon_visit_id = Column(String, ForeignKey("anonymous_visits.id"), nullable=True)

    touch_type = Column(String, nullable=True)  # "first", "middle", "last"
    weight = Column(Float, default=1.0)

    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace")
    opportunity = relationship("Opportunity", back_populates="touches")
    event = relationship("Event")
    anon_visit = relationship("AnonymousVisit")


class PlaybookRule(Base):
    # Simple rule engine for scores → tasks/alerts/CRM.
    __tablename__ = "playbook_rules"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    # Conditions
    min_total_score = Column(Float, nullable=True)
    min_intent_score = Column(Float, nullable=True)
    buyer_stage_in = Column(JSON, nullable=True)  # list of stages
    countries_in = Column(JSON, nullable=True)    # list of country codes/names
    stages_in = Column(JSON, nullable=True)       # list of pipeline stages
    has_open_tasks = Column(Boolean, nullable=True)

    # Actions
    create_task = Column(Boolean, default=False)
    create_alert = Column(Boolean, default=False)
    push_to_crm = Column(Boolean, default=False)

    task_title_template = Column(String, nullable=True)
    alert_title_template = Column(String, nullable=True)
    alert_severity = Column(String, nullable=True)  # low/medium/high
    owner = Column(String, nullable=True)           # assignee for created tasks

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace")
