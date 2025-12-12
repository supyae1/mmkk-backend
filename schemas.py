from __future__ import annotations

from datetime import datetime
from io import StringIO
from typing import Any, Dict, List

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import (
    Workspace,
    APIKey,
    Account,
    Contact,
    Event,
    AnonymousVisit,
    Task,
    Alert,
    PlaybookRule,
    Opportunity,
)
from schemas import (
    TrackEventPayload,
    AnonymousVisitCreate,
    AnonymousVisitRead,
    AccountCreate,
    AccountRead,
    AccountUpdate,
    ContactCreate,
    ContactRead,
    TaskCreate,
    TaskRead,
    AlertCreate,
    AlertRead,
    TopAccountItem,
    TopAccountsResponse,
    ActivityFeedItem,
    ActivityFeedResponse,
    TimelineItem,
    Account360Response,
    CRMAccountUpsert,
    CRMContactUpsert,
    CRMOpportunityUpsert,
    OpportunityCreate,
    OpportunityRead,
    OpportunityUpdate,
    AttributionRequest,
    AttributionResponse,
    SegmentationRequest,
    SegmentationResponse,
    PlaybookRuleCreate,
    PlaybookRuleRead,
)
from scoring import score_event
from ai_scoring import generate_ai_insights
from analytics import multi_touch_attribution, segment_accounts


# ------------------------------------------------
# FastAPI app setup
# ------------------------------------------------

app = FastAPI(
    title="MMKK Revenue Engine API",
    version="1.1.0",
    description="Account-based intelligence, scoring, and multi-channel attribution.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten per-client later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static demo / future dashboard
app.mount("/static", StaticFiles(directory="static"), name="static")

# Ensure tables exist
Base.metadata.create_all(bind=engine)


# ------------------------------------------------
# Workspace + API key (single-tenant MVP)
# ------------------------------------------------

DEFAULT_WORKSPACE_ID = "default"
DEFAULT_WORKSPACE_NAME = "Default Workspace"
DEFAULT_API_KEY = "supersecret123"  # demo key


def get_workspace_id() -> str:
    # For now there is only one workspace
    return DEFAULT_WORKSPACE_ID


@app.on_event("startup")
def ensure_default_workspace() -> None:
    """Create a default workspace + API key if missing."""
    db = next(get_db())
    try:
        ws = db.query(Workspace).filter(Workspace.id == DEFAULT_WORKSPACE_ID).first()
        if not ws:
            ws = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_NAME)
            db.add(ws)
            db.commit()

        key = (
            db.query(APIKey)
            .filter(
                APIKey.workspace_id == DEFAULT_WORKSPACE_ID,
                APIKey.key == DEFAULT_API_KEY,
            )
            .first()
        )
        if not key:
            key = APIKey(
                workspace_id=DEFAULT_WORKSPACE_ID,
                key=DEFAULT_API_KEY,
                label="Default demo key",
                is_active=True,
            )
            db.add(key)
            db.commit()
    finally:
        db.close()


async def verify_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> None:
    api_key = (
        db.query(APIKey)
        .filter(APIKey.key == x_api_key, APIKey.is_active == True)  # noqa: E712
        .first()
    )
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ------------------------------------------------
# Health + root
# ------------------------------------------------

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.head("/health")
def health_head() -> Response:
    # For Render probes (avoid 405 spam)
    return Response(status_code=200)


@app.get("/health/full")
def full_health(db: Session = Depends(get_db)):
    ws = get_workspace_id()

    accounts = (
        db.query(func.count(Account.id)).filter(Account.workspace_id == ws).scalar() or 0
    )
    events = (
        db.query(func.count(Event.id)).filter(Event.workspace_id == ws).scalar() or 0
    )
    contacts = (
        db.query(func.count(Contact.id)).filter(Contact.workspace_id == ws).scalar() or 0
    )

    return {
        "status": "ok",
        "workspace_id": ws,
        "counts": {
            "accounts": accounts,
            "events": events,
            "contacts": contacts,
        },
    }


@app.get("/")
def root() -> RedirectResponse:
    # Go straight to live demo
    return RedirectResponse("/static/demo.html")


# ------------------------------------------------
# Pixel.js (1-line script)
# ------------------------------------------------

PIXEL_JS_TEMPLATE = """
(function () {{
  function uuidv4() {{
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function(c) {{
      var r = Math.random() * 16 | 0, v = c === "x" ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    }});
  }}

  var anonId = localStorage.getItem("mmkk_anon_id");
  if (!anonId) {{
    anonId = uuidv4();
    localStorage.setItem("mmkk_anon_id", anonId);
  }}

  function sendEvent(eventType) {{
    var payload = {{
      event_type: eventType || "pageview",
      url: window.location.href,
      referrer: document.referrer || null,
      channel: "web",
      metadata: {{}}
    }};
    fetch("{base_url}/track", {{
      method: "POST",
      headers: {{
        "Content-Type": "application/json",
        "X-API-Key": "{api_key}"
      }},
      body: JSON.stringify(payload)
    }}).catch(function () {{}});
  }}

  window.MMKK = window.MMKK || {{}};
  window.MMKK.track = sendEvent;

  if (document.readyState === "complete") {{
    sendEvent("pageview");
  }} else {{
    window.addEventListener("load", function () {{
      sendEvent("pageview");
    }});
  }}
}})();
""".strip()


@app.get("/pixel.js")
def pixel_js(request: Request) -> Response:
    base_url = str(request.base_url).rstrip("/")
    js = PIXEL_JS_TEMPLATE.format(base_url=base_url, api_key=DEFAULT_API_KEY)
    return Response(content=js, media_type="application/javascript")


# ------------------------------------------------
# Tracking
# ------------------------------------------------

@app.post("/public/track", response_model=AnonymousVisitRead)
def public_track(payload: AnonymousVisitCreate, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    now = datetime.utcnow()

    anon = AnonymousVisit(
        workspace_id=ws,
        url=payload.url,
        referrer=payload.referrer,
        ip=payload.ip,
        user_agent=payload.user_agent,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(anon)
    db.commit()
    db.refresh(anon)

    return AnonymousVisitRead.from_orm(anon)


@app.post("/track", dependencies=[Depends(verify_api_key)])
def track_event(payload: TrackEventPayload, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    now = datetime.utcnow()

    # Build metadata from UTM fields
    meta: Dict[str, Any] = payload.metadata or {}
    for field in [
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
    ]:
        val = getattr(payload, field)
        if val:
            meta[field] = val

    source = payload.channel or meta.get("utm_source") or "web"

    event = Event(
        workspace_id=ws,
        account_id=payload.account_id,
        contact_id=payload.contact_id,
        event_type=payload.event_type,
        source=source,
        page=payload.page,
        route=payload.route,
        url=payload.url,
        event_metadata=meta or None,
        value=payload.revenue,
        created_at=now,
    )
    db.add(event)

    account = None
    if payload.account_id:
        account = (
            db.query(Account)
            .filter(Account.workspace_id == ws, Account.id == payload.account_id)
            .first()
        )

    intent_delta, engagement_delta, totals = score_event(account, event)

    if account:
        account.intent_score = totals.intent_score
        account.engagement_score = totals.engagement_score
        account.fit_score = totals.fit_score
        account.predictive_score = totals.predictive_score
        account.total_score = totals.total_score
        account.last_activity_at = now
        db.add(account)

    db.commit()

    return {
        "status": "ok",
        "event_id": event.id,
        "account_totals": totals.__dict__ if account else None,
    }


# ------------------------------------------------
# Accounts
# ------------------------------------------------

@app.post(
    "/accounts",
    response_model=AccountRead,
    dependencies=[Depends(verify_api_key)],
)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    now = datetime.utcnow()

    acc = Account(
        workspace_id=ws,
        name=payload.name,
        domain=payload.domain,
        industry=payload.industry,
        employee_count=payload.employee_count,
        stage=payload.stage,
        country=payload.country,
        city=payload.city,
        intent_score=0.0,
        engagement_score=0.0,
        fit_score=0.0,
        predictive_score=0.0,
        total_score=0.0,
        created_at=now,
        updated_at=now,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)

    return AccountRead.from_orm(acc)


@app.get(
    "/accounts/{account_id}",
    response_model=AccountRead,
    dependencies=[Depends(verify_api_key)],
)
def get_account(account_id: str, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    acc = (
        db.query(Account)
        .filter(Account.workspace_id == ws, Account.id == account_id)
        .first()
    )
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountRead.from_orm(acc)


@app.patch(
    "/accounts/{account_id}",
    response_model=AccountRead,
    dependencies=[Depends(verify_api_key)],
)
def update_account(
    account_id: str, payload: AccountUpdate, db: Session = Depends(get_db)
):
    ws = get_workspace_id()
    acc = (
        db.query(Account)
        .filter(Account.workspace_id == ws, Account.id == account_id)
        .first()
    )
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(acc, field, value)
    acc.updated_at = datetime.utcnow()
    db.add(acc)
    db.commit()
    db.refresh(acc)

    return AccountRead.from_orm(acc)


# ------------------------------------------------
# Contacts
# ------------------------------------------------

@app.post(
    "/contacts",
    response_model=ContactRead,
    dependencies=[Depends(verify_api_key)],
)
def create_contact(payload: ContactCreate, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    now = datetime.utcnow()

    contact = Contact(
        workspace_id=ws,
        account_id=payload.account_id,
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        title=payload.title,
        phone=payload.phone,
        created_at=now,
        updated_at=now,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)

    return ContactRead.from_orm(contact)


# ------------------------------------------------
# Tasks & Alerts
# ------------------------------------------------

@app.post(
    "/tasks",
    response_model=TaskRead,
    dependencies=[Depends(verify_api_key)],
)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    now = datetime.utcnow()

    task = Task(
        workspace_id=ws,
        account_id=payload.account_id,
        contact_id=payload.contact_id,
        title=payload.title,
        description=payload.description,
        due_at=payload.due_at,
        status=payload.status,
        owner=payload.owner,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    return TaskRead.from_orm(task)


@app.post(
    "/alerts",
    response_model=AlertRead,
    dependencies=[Depends(verify_api_key)],
)
def create_alert(payload: AlertCreate, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    now = datetime.utcnow()

    alert = Alert(
        workspace_id=ws,
        account_id=payload.account_id,
        contact_id=payload.contact_id,
        title=payload.title,
        severity=payload.severity,
        description=payload.description,
        owner=payload.owner,
        created_at=now,
        updated_at=now,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    return AlertRead.from_orm(alert)


# ------------------------------------------------
# Insights
# ------------------------------------------------

@app.get(
    "/insights/top-accounts",
    response_model=TopAccountsResponse,
    dependencies=[Depends(verify_api_key)],
)
def top_accounts(limit: int = 20, db: Session = Depends(get_db)):
    ws = get_workspace_id()

    rows: List[Account] = (
        db.query(Account)
        .filter(Account.workspace_id == ws)
        .order_by(Account.total_score.desc())
        .limit(limit)
        .all()
    )

    items = [
        TopAccountItem(
            id=a.id,
            name=a.name,
            intent_score=a.intent_score,
            engagement_score=a.engagement_score,
            fit_score=a.fit_score,
            predictive_score=a.predictive_score,
            total_score=a.total_score,
            buyer_stage=getattr(a, "stage", None),
            last_activity_at=getattr(a, "last_activity_at", None),
        )
        for a in rows
    ]

    return TopAccountsResponse(items=items)


@app.get(
    "/insights/activity-feed",
    response_model=ActivityFeedResponse,
    dependencies=[Depends(verify_api_key)],
)
def activity_feed(limit: int = 50, db: Session = Depends(get_db)):
    ws = get_workspace_id()

    events: List[Event] = (
        db.query(Event)
        .filter(Event.workspace_id == ws)
        .order_by(Event.created_at.desc())
        .limit(limit)
        .all()
    )

    items = [
        ActivityFeedItem(
            id=e.id,
            account_id=e.account_id,
            contact_id=e.contact_id,
            event_type=e.event_type,
            source=e.source,
            page=e.page,
            route=e.route,
            url=e.url,
            value=e.value,
            created_at=e.created_at,
        )
        for e in events
    ]

    return ActivityFeedResponse(items=items)


@app.get(
    "/accounts/{account_id}/360",
    response_model=Account360Response,
    dependencies=[Depends(verify_api_key)],
)
def account_360(account_id: str, db: Session = Depends(get_db)):
    ws = get_workspace_id()

    acc = (
        db.query(Account)
        .filter(Account.workspace_id == ws, Account.id == account_id)
        .first()
    )
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    contacts: List[Contact] = (
        db.query(Contact)
        .filter(Contact.workspace_id == ws, Contact.account_id == account_id)
        .all()
    )
    tasks: List[Task] = (
        db.query(Task)
        .filter(Task.workspace_id == ws, Task.account_id == account_id)
        .all()
    )
    alerts: List[Alert] = (
        db.query(Alert)
        .filter(Alert.workspace_id == ws, Alert.account_id == account_id)
        .all()
    )
    events: List[Event] = (
        db.query(Event)
        .filter(Event.workspace_id == ws, Event.account_id == account_id)
        .order_by(Event.created_at.desc())
        .all()
    )

    timeline = [
        TimelineItem(
            id=e.id,
            event_type=e.event_type,
            url=e.url,
            created_at=e.created_at,
            value=e.value,
            source=e.source,
        )
        for e in events
    ]

    ai = generate_ai_insights(db, account_id)

    return Account360Response(
        account=AccountRead.from_orm(acc),
        contacts=[ContactRead.from_orm(c) for c in contacts],
        timeline=timeline,
        tasks=[TaskRead.from_orm(t) for t in tasks],
        alerts=[AlertRead.from_orm(a) for a in alerts],
        ai_insights=ai,
    )


@app.get(
    "/insights/next-best-actions/{account_id}",
    dependencies=[Depends(verify_api_key)],
)
def next_best_actions(account_id: str, db: Session = Depends(get_db)):
    return generate_ai_insights(db, account_id)


# ------------------------------------------------
# Attribution & Segmentation
# ------------------------------------------------

@app.post(
    "/analytics/attribution",
    response_model=AttributionResponse,
    dependencies=[Depends(verify_api_key)],
)
def attribution(payload: AttributionRequest, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    return multi_touch_attribution(db, ws, payload)


@app.post(
    "/analytics/segments",
    response_model=SegmentationResponse,
    dependencies=[Depends(verify_api_key)],
)
def segments(payload: SegmentationRequest, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    return segment_accounts(db, ws, payload)


# ------------------------------------------------
# CRM export
# ------------------------------------------------

@app.get(
    "/crm/export.csv",
    dependencies=[Depends(verify_api_key)],
)
def crm_export(db: Session = Depends(get_db)) -> Response:
    ws = get_workspace_id()
    output = StringIO()

    header = [
        "account_id",
        "account_name",
        "intent_score",
        "engagement_score",
        "fit_score",
        "predictive_score",
        "total_score",
        "stage",
        "last_activity_at",
    ]
    output.write(",".join(header) + "\n")

    accounts: List[Account] = (
        db.query(Account)
        .filter(Account.workspace_id == ws)
        .order_by(Account.total_score.desc())
        .all()
    )

    for a in accounts:
        row = [
            a.id,
            a.name or "",
            str(a.intent_score or 0),
            str(a.engagement_score or 0),
            str(a.fit_score or 0),
            str(a.predictive_score or 0),
            str(a.total_score or 0),
            getattr(a, "stage", "") or "",
            (a.last_activity_at or a.updated_at or a.created_at).isoformat(),
        ]
        output.write(",".join(row) + "\n")

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mmkk_crm_export.csv"},
    )
