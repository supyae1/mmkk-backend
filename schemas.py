from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


# ------------------------------------------------
# Base helper
# ------------------------------------------------

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------
# Tracking
# ------------------------------------------------

class TrackEventPayload(ORMModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None

    event_type: str = "pageview"
    url: Optional[str] = None
    page: Optional[str] = None
    route: Optional[str] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    referrer: Optional[str] = None

    channel: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_term: Optional[str] = None
    utm_content: Optional[str] = None

    revenue: Optional[float] = None
    is_conversion: bool = False

    metadata: Optional[Dict[str, Any]] = None


class AnonymousVisitCreate(ORMModel):
    url: str
    referrer: Optional[str] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None


class AnonymousVisitRead(AnonymousVisitCreate):
    id: str
    first_seen_at: datetime
    last_seen_at: datetime


# ------------------------------------------------
# Accounts & Contacts
# ------------------------------------------------

class AccountBase(ORMModel):
    name: str
    domain: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    stage: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None


class AccountCreate(AccountBase):
    pass


class AccountUpdate(ORMModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    stage: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None


class AccountRead(AccountBase):
    id: str
    intent_score: float
    engagement_score: float
    fit_score: float
    predictive_score: float
    total_score: float
    buyer_stage: Optional[str] = None
    last_activity_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ContactBase(ORMModel):
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None


class ContactCreate(ContactBase):
    account_id: Optional[str] = None


class ContactRead(ContactBase):
    id: str
    account_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------
# Tasks & Alerts
# ------------------------------------------------

class TaskCreate(ORMModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    due_at: Optional[datetime] = None
    status: str = "open"
    owner: Optional[str] = None


class TaskRead(TaskCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class AlertCreate(ORMModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    title: str
    severity: str = "medium"
    description: Optional[str] = None
    owner: Optional[str] = None


class AlertRead(AlertCreate):
    id: str
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------
# Insights
# ------------------------------------------------

class TopAccountItem(ORMModel):
    id: str
    name: str
    intent_score: float
    engagement_score: float
    fit_score: float
    predictive_score: float
    total_score: float
    buyer_stage: Optional[str] = None
    last_activity_at: Optional[datetime] = None


class TopAccountsResponse(ORMModel):
    items: List[TopAccountItem]


class ActivityFeedItem(ORMModel):
    id: str
    account_id: Optional[str]
    contact_id: Optional[str]
    event_type: str
    source: Optional[str] = None
    page: Optional[str] = None
    route: Optional[str] = None
    url: Optional[str] = None
    value: Optional[float] = None
    created_at: datetime


class ActivityFeedResponse(ORMModel):
    items: List[ActivityFeedItem]


class TimelineItem(ORMModel):
    id: str
    event_type: str
    url: Optional[str]
    created_at: datetime
    value: Optional[float] = None
    source: Optional[str] = None


class Account360Response(ORMModel):
    account: AccountRead
    contacts: List[ContactRead]
    timeline: List[TimelineItem]
    tasks: List[TaskRead]
    alerts: List[AlertRead]
    ai_insights: Dict[str, Any]


# ------------------------------------------------
# CRM / Opportunities
# ------------------------------------------------

class CRMAccountUpsert(ORMModel):
    external_id: str
    name: str
    domain: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    stage: Optional[str] = None


class CRMContactUpsert(ORMModel):
    external_id: str
    email: str
    account_external_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None


class CRMOpportunityUpsert(ORMModel):
    external_id: str
    account_external_id: str
    name: str
    stage: str
    amount: float
    currency: str = "USD"
    close_date: Optional[datetime] = None
    probability: Optional[float] = None


class OpportunityBase(ORMModel):
    name: str
    stage: str
    amount: float
    currency: str = "USD"
    close_date: Optional[datetime] = None
    probability: Optional[float] = None
    account_id: Optional[str] = None
    external_id: Optional[str] = None


class OpportunityCreate(OpportunityBase):
    pass


class OpportunityUpdate(ORMModel):
    name: Optional[str] = None
    stage: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    close_date: Optional[datetime] = None
    probability: Optional[float] = None


class OpportunityRead(OpportunityBase):
    id: str
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------
# Attribution & Segmentation
# ------------------------------------------------

class AttributedChannel(BaseModel):
    channel: str
    first_touch: float
    last_touch: float
    linear: float


class AttributionRequest(BaseModel):
    account_id: Optional[str] = None
    lookback_days: int = 90


class AttributionResponse(BaseModel):
    account_id: Optional[str] = None
    breakdown: List[AttributedChannel]


class SegmentFilter(BaseModel):
    field: str
    operator: str
    value: str


class Segment(BaseModel):
    segment_name: str
    account_ids: List[str]


class SegmentationRequest(BaseModel):
    workspace_id: str
    filters: List[SegmentFilter] = []


class SegmentationResponse(BaseModel):
    segments: List[Segment]


# ------------------------------------------------
# Playbooks
# ------------------------------------------------

class PlaybookRuleBase(ORMModel):
    name: str
    description: Optional[str] = None
    min_intent: Optional[float] = None
    min_engagement: Optional[float] = None
    min_total_score: Optional[float] = None
    trigger_event_type: Optional[str] = None
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
