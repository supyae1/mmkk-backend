# schemas.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# -----------------------
# Base helpers
# -----------------------

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# -----------------------
# Account & Contact
# -----------------------

class AccountBase(ORMModel):
    name: str
    domain: Optional[str] = None
    owner: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    stage: Optional[str] = None


class AccountCreate(AccountBase):
    pass


class AccountUpdate(ORMModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    owner: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    stage: Optional[str] = None


class AccountRead(AccountBase):
    id: str
    intent_score: float = 0.0
    fit_score: float = 0.0
    engagement_score: float = 0.0
    predictive_score: float = 0.0
    total_score: float = 0.0
    buyer_stage: Optional[str] = None
    last_event_at: Optional[datetime] = None
    last_source: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ContactBase(ORMModel):
    name: str
    email: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None


class ContactCreate(ContactBase):
    pass


class ContactRead(ContactBase):
    id: str
    account_id: str
    created_at: datetime
    updated_at: datetime


# -----------------------
# Event / Task / Alert / Visit
# -----------------------

class EventBase(ORMModel):
    event_type: str
    source: Optional[str] = None
    page: Optional[str] = None
    route: Optional[str] = None
    url: Optional[str] = None
    event_metadata: Optional[Dict[str, Any]] = None
    value: Optional[float] = None
    duration: Optional[int] = None


class EventCreate(EventBase):
    contact_id: Optional[str] = None


class EventRead(EventBase):
    id: str
    account_id: str
    contact_id: Optional[str] = None
    intent_score: float = 0.0
    engagement_score: float = 0.0
    created_at: datetime


class TaskBase(ORMModel):
    title: str
    description: Optional[str] = None
    status: str = "open"
    owner: Optional[str] = None
    due_at: Optional[datetime] = None
    source: Optional[str] = None


class TaskCreate(TaskBase):
    pass


class TaskRead(TaskBase):
    id: str
    account_id: str
    created_at: datetime
    updated_at: datetime


class AlertBase(ORMModel):
    title: str
    body: Optional[str] = None
    type: Optional[str] = None
    severity: Optional[str] = None


class AlertCreate(AlertBase):
    account_id: Optional[str] = None


class AlertRead(AlertBase):
    id: str
    account_id: Optional[str] = None
    is_read: bool
    created_at: datetime


class AnonymousVisitCreate(ORMModel):
    account_id: Optional[str] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    url: Optional[str] = None
    referrer: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    company_guess: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class AnonymousVisitRead(AnonymousVisitCreate):
    id: str
    created_at: datetime


# -----------------------
# Tracking payload
# -----------------------

class TrackEventPayload(ORMModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    event_type: Optional[str] = "pageview"

    # Network + context
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    url: Optional[str] = None

    # Free-form extra fields (custom properties, referrer, etc.)
    metadata: Optional[Dict[str, Any]] = None

    # --- NEW: multi-channel + attribution fields ---
    # “Channel” = where this came from: facebook_ads, google_ads, email, linkedin, etc.
    channel: Optional[str] = None

    # Standard UTM tags for multi-touch attribution
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_term: Optional[str] = None
    utm_content: Optional[str] = None

    # Revenue + conversion flags
    revenue: Optional[float] = None          # e.g. booking value, contract value
    is_conversion: bool = False              # True if this event is a conversion-touch

# -----------------------
# Attribution & Segmentation
# -----------------------

class AttributedChannel(BaseModel):
    channel: str
    first_touch_revenue: float = 0.0
    last_touch_revenue: float = 0.0
    linear_revenue: float = 0.0
    conversions: int = 0


class AttributionRequest(BaseModel):
    account_id: Optional[str] = None   # if None, aggregate across all accounts in workspace
    lookback_days: int = 90


class AttributionResponse(BaseModel):
    channels: List[AttributedChannel]


class SegmentFilter(BaseModel):
    # Behavioral
    min_visits: Optional[int] = None          # minimum number of events
    max_inactive_days: Optional[int] = None   # max days since last_event_at

    # Firmographic
    industries: Optional[List[str]] = None
    stages: Optional[List[str]] = None        # pipeline stages


class Segment(BaseModel):
    segment_name: str
    account_ids: List[str]


class SegmentationRequest(BaseModel):
    filters: SegmentFilter


class SegmentationResponse(BaseModel):
    segments: List[Segment]

# -----------------------
# Insights: Top Accounts
# -----------------------

class TopAccountItem(ORMModel):
    id: str
    name: str
    intent_score: float
    engagement_score: float
    fit_score: float
    predictive_score: float
    total_score: float
    buyer_stage: Optional[str] = None
    last_event_at: Optional[datetime] = None
    last_source: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None


class TopAccountsResponse(ORMModel):
    items: List[TopAccountItem]


# -----------------------
# Insights: Activity Feed
# -----------------------

class ActivityFeedItem(ORMModel):
    id: str
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    type: str  # event, task, alert, anon_visit
    source: Optional[str] = None
    url: Optional[str] = None
    created_at: datetime
    summary: str
    intent_score: float = 0.0
    buyer_stage: Optional[str] = None


class ActivityFeedResponse(ORMModel):
    items: List[ActivityFeedItem]


# -----------------------
# Insights: Pipeline
# -----------------------


class PipelineStageSummary(ORMModel):
    stage: str
    count: int
    total_score: float


class PipelineAccountRow(ORMModel):
    account: AccountRead
    open_value: float
    open_tasks: int
    last_touch: Optional[datetime] = None


class PipelineSummary(ORMModel):
    total_open_value: float
    total_open_accounts: int
    items: List[PipelineAccountRow]


# -----------------------
# Account 360
# -----------------------

class TimelineItem(ORMModel):
    type: str
    created_at: datetime
    summary: str
    payload: Dict[str, Any]


class Account360Response(ORMModel):
    account: AccountRead
    events_count: int
    last_seen: Optional[datetime]
    country: Optional[str]
    intent_score: float
    fit_score: float
    engagement_score: float
    predictive_score: float
    total_score: float
    buyer_stage: Optional[str]
    last_source: Optional[str]
    anon_visit_count: int
    anon_last_seen: Optional[datetime]
    signals: List[Dict[str, Any]]
    next_best_action: str
    next_best_action_reason: str
    playbook_label: str
    enrichment_summary: str
    timeline: List[TimelineItem]


# -----------------------
# CRM Upsert payloads
# -----------------------

class CRMAccountUpsert(ORMModel):
    external_id: str
    name: str
    domain: Optional[str] = None
    owner: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None


class CRMContactUpsert(ORMModel):
    external_id: str
    account_external_id: Optional[str] = None
    name: str
    email: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None


class CRMOpportunityUpsert(ORMModel):
    external_id: str
    account_external_id: str
    name: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    close_date: Optional[datetime] = None
    source: Optional[str] = None


# -----------------------
# Opportunity
# -----------------------

class OpportunityBase(ORMModel):
    account_id: str
    name: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    close_date: Optional[datetime] = None
    source: Optional[str] = None
    external_id: Optional[str] = None


class OpportunityCreate(OpportunityBase):
    pass


class OpportunityUpdate(ORMModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    close_date: Optional[datetime] = None
    source: Optional[str] = None


class OpportunityRead(OpportunityBase):
    id: str
    created_at: datetime
    updated_at: datetime


# -----------------------
# Playbooks
# -----------------------

class PlaybookRuleBase(ORMModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True

    min_total_score: Optional[float] = None
    min_intent_score: Optional[float] = None
    buyer_stage_in: Optional[List[str]] = None
    countries_in: Optional[List[str]] = None
    stages_in: Optional[List[str]] = None
    has_open_tasks: Optional[bool] = None

    create_task: bool = False
    create_alert: bool = False
    push_to_crm: bool = False

    task_title_template: Optional[str] = None
    alert_title_template: Optional[str] = None
    alert_severity: Optional[str] = None
    owner: Optional[str] = None


class PlaybookRuleCreate(PlaybookRuleBase):
    pass


class PlaybookRuleRead(PlaybookRuleBase):
    id: str
    created_at: datetime
    updated_at: datetime
