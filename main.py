from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
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
    Opportunity,
    PlaybookRule,
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
    OpportunityCreate,
    OpportunityRead,
    OpportunityUpdate,
    AttributionRequest,
    AttributionResponse,
    SegmentationRequest,
    SegmentationResponse,
)
from scoring import score_event
from ai_scoring import generate_ai_insights
from analytics import multi_touch_attribution, segment_accounts


# ------------------------------------------------
# App setup
# ------------------------------------------------

app = FastAPI(
    title="MMKK Revenue Engine API",
    version="1.0.1",
    description="AI-powered, account-based revenue intelligence engine.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten per client in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static for your dashboard
app.mount("/static", StaticFiles(directory="static"), name="static")

# Create tables
Base.metadata.create_all(bind=engine)


DEFAULT_WORKSPACE_ID = "default"
DEFAULT_WORKSPACE_NAME = "Default Workspace"
DEFAULT_API_KEY = "supersecret123"  # change in production


def get_workspace_id() -> str:
    # Single-tenant for now (easy to sell). Multi-tenant later.
    return DEFAULT_WORKSPACE_ID


@app.on_event("startup")
def ensure_default_workspace() -> None:
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
    # Your dashboard is typically static/dashboard.html
    return RedirectResponse("/static/dashboard.html")


# ------------------------------------------------
# Pixel.js
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
      metadata: {{
        session_id: anonId
      }}
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
# Helpers (for dashboard response shapes)
# ------------------------------------------------

def _event_summary(e: Event) -> str:
    et = (e.event_type or "").strip()
    page = e.page or ""
    if not page and e.url:
        try:
            page = urlparse(e.url).path or e.url
        except Exception:
            page = e.url
    src = (e.source or "").strip()
    bits = [b for b in [et, page] if b]
    s = " · ".join(bits) if bits else et or "event"
    if src:
        return f"{s} ({src})"
    return s


def _safe_domain(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        u = urlparse(url)
        return u.netloc or ""
    except Exception:
        return ""


def _is_open_opp_stage(stage: str) -> bool:
    s = (stage or "").lower()
    return s not in {"closed_won", "closed_lost", "won", "lost", "closed"}


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

    source = payload.channel or meta.get("utm_source") or meta.get("utm_medium") or "web"

    event = Event(
        workspace_id=ws,
        account_id=payload.account_id,
        contact_id=payload.contact_id,
        event_type=payload.event_type,
        source=source,
        page=payload.page,
        route=payload.route,
        url=payload.url,
        referrer=payload.referrer,
        ip=payload.ip,
        user_agent=payload.user_agent,
        event_metadata=meta or None,
        value=payload.revenue,
        created_at=now,
    )
    db.add(event)

    account: Optional[Account] = None
    if payload.account_id:
        account = (
            db.query(Account)
            .filter(Account.workspace_id == ws, Account.id == payload.account_id)
            .first()
        )

    _, _, totals = score_event(account, event)

    if account:
        account.intent_score = totals.intent_score
        account.engagement_score = totals.engagement_score
        account.fit_score = totals.fit_score
        account.predictive_score = totals.predictive_score
        account.total_score = totals.total_score
        account.last_activity_at = now
        db.add(account)

    db.commit()

    # Lightweight auto-alert (keeps dashboard alive)
    if account and totals.total_score >= 80:
        alert = Alert(
            workspace_id=ws,
            account_id=account.id,
            title="High-intent account",
            severity="high",
            description=f"{account.name} crossed total_score={totals.total_score:.1f}",
            owner=None,
            created_at=now,
            updated_at=now,
        )
        db.add(alert)
        db.commit()

    return {
        "status": "ok",
        "event_id": event.id,
        "account_totals": totals.__dict__ if account else None,
    }


# ------------------------------------------------
# Accounts
# ------------------------------------------------

@app.post("/accounts", response_model=AccountRead, dependencies=[Depends(verify_api_key)])
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


@app.get("/accounts/{account_id}", response_model=AccountRead, dependencies=[Depends(verify_api_key)])
def get_account(account_id: str, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    acc = db.query(Account).filter(Account.workspace_id == ws, Account.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountRead.from_orm(acc)


@app.patch("/accounts/{account_id}", response_model=AccountRead, dependencies=[Depends(verify_api_key)])
def update_account(account_id: str, payload: AccountUpdate, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    acc = db.query(Account).filter(Account.workspace_id == ws, Account.id == account_id).first()
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

@app.post("/contacts", response_model=ContactRead, dependencies=[Depends(verify_api_key)])
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
# Tasks & Alerts (POST endpoints)
# ------------------------------------------------

@app.post("/tasks", response_model=TaskRead, dependencies=[Depends(verify_api_key)])
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


@app.post("/alerts", response_model=AlertRead, dependencies=[Depends(verify_api_key)])
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
# Opportunities
# ------------------------------------------------

@app.post("/opportunities", response_model=OpportunityRead, dependencies=[Depends(verify_api_key)])
def create_opportunity(payload: OpportunityCreate, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    now = datetime.utcnow()

    opp = Opportunity(
        workspace_id=ws,
        account_id=payload.account_id,
        name=payload.name,
        stage=payload.stage,
        amount=payload.amount,
        currency=payload.currency,
        close_date=payload.close_date,
        probability=payload.probability,
        external_id=payload.external_id,
        created_at=now,
        updated_at=now,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return OpportunityRead.from_orm(opp)


@app.get("/opportunities/{opportunity_id}", response_model=OpportunityRead, dependencies=[Depends(verify_api_key)])
def get_opportunity(opportunity_id: str, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    opp = db.query(Opportunity).filter(Opportunity.workspace_id == ws, Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return OpportunityRead.from_orm(opp)


@app.patch("/opportunities/{opportunity_id}", response_model=OpportunityRead, dependencies=[Depends(verify_api_key)])
def update_opportunity(opportunity_id: str, payload: OpportunityUpdate, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    opp = db.query(Opportunity).filter(Opportunity.workspace_id == ws, Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(opp, field, value)
    opp.updated_at = datetime.utcnow()
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return OpportunityRead.from_orm(opp)


# ------------------------------------------------
# Dashboard endpoints (match dashboard.html)
# ------------------------------------------------

@app.get("/insights/top-accounts", response_model=TopAccountsResponse, dependencies=[Depends(verify_api_key)])
def top_accounts(limit: int = 50, db: Session = Depends(get_db)):
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
            intent_score=float(a.intent_score or 0.0),
            engagement_score=float(a.engagement_score or 0.0),
            fit_score=float(a.fit_score or 0.0),
            predictive_score=float(a.predictive_score or 0.0),
            total_score=float(a.total_score or 0.0),
            buyer_stage=a.stage or a.buyer_stage,
            last_activity_at=a.last_activity_at,
        )
        for a in rows
    ]
    return TopAccountsResponse(items=items)


@app.get("/insights/activity-feed", response_model=ActivityFeedResponse, dependencies=[Depends(verify_api_key)])
def activity_feed(limit: int = 80, db: Session = Depends(get_db)):
    """
    Dashboard expects:
      items[].account_name
      items[].summary
    """
    ws = get_workspace_id()
    events: List[Event] = (
        db.query(Event)
        .filter(Event.workspace_id == ws)
        .order_by(Event.created_at.desc())
        .limit(limit)
        .all()
    )

    # batch load account names
    account_ids = list({e.account_id for e in events if e.account_id})
    name_map: Dict[str, str] = {}
    if account_ids:
        rows = db.query(Account.id, Account.name).filter(Account.id.in_(account_ids)).all()
        name_map = {rid: rname for rid, rname in rows}

    items = []
    for e in events:
        items.append(
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
                # Extra fields your UI uses (schemas.py should already allow extra OR you can add them there)
                account_name=name_map.get(e.account_id or "", None),  # type: ignore
                summary=_event_summary(e),  # type: ignore
            )
        )

    return ActivityFeedResponse(items=items)


@app.get("/accounts/{account_id}/360", response_model=Account360Response, dependencies=[Depends(verify_api_key)])
def account_360(account_id: str, db: Session = Depends(get_db)):
    ws = get_workspace_id()

    acc = db.query(Account).filter(Account.workspace_id == ws, Account.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    contacts: List[Contact] = (
        db.query(Contact).filter(Contact.workspace_id == ws, Contact.account_id == account_id).all()
    )
    tasks: List[Task] = (
        db.query(Task).filter(Task.workspace_id == ws, Task.account_id == account_id).all()
    )
    alerts: List[Alert] = (
        db.query(Alert).filter(Alert.workspace_id == ws, Alert.account_id == account_id).all()
    )
    events: List[Event] = (
        db.query(Event)
        .filter(Event.workspace_id == ws, Event.account_id == account_id)
        .order_by(Event.created_at.desc())
        .limit(250)
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


@app.get("/insights/anon-visits", dependencies=[Depends(verify_api_key)])
def insights_anon_visits(limit: int = 20, db: Session = Depends(get_db)):
    """
    Dashboard expects an array:
      [{ session_id, url, referrer, created_at }]
    """
    ws = get_workspace_id()
    rows: List[AnonymousVisit] = (
        db.query(AnonymousVisit)
        .filter(AnonymousVisit.workspace_id == ws)
        .order_by(AnonymousVisit.last_seen_at.desc())
        .limit(limit)
        .all()
    )

    out = []
    for r in rows:
        out.append(
            {
                "session_id": r.id,
                "url": r.url,
                "referrer": r.referrer,
                "created_at": r.first_seen_at,
                "last_seen_at": r.last_seen_at,
            }
        )
    return out


@app.get("/alerts", dependencies=[Depends(verify_api_key)])
def list_alerts(limit: int = 50, db: Session = Depends(get_db)):
    """
    Dashboard supports:
      - { items: [...] }
      - or [...] directly
    Best is:
      { items: [ { alert: {...}, account: {...} } ] }
    """
    ws = get_workspace_id()

    alerts: List[Alert] = (
        db.query(Alert)
        .filter(Alert.workspace_id == ws)
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )

    account_ids = list({a.account_id for a in alerts if a.account_id})
    acc_map: Dict[str, Dict[str, Any]] = {}
    if account_ids:
        accs = db.query(Account).filter(Account.id.in_(account_ids)).all()
        for a in accs:
            acc_map[a.id] = {"id": a.id, "name": a.name, "stage": a.stage, "domain": a.domain}

    items = []
    for a in alerts:
        items.append(
            {
                "alert": {
                    "id": a.id,
                    "title": a.title,
                    "body": a.description,  # dashboard reads row.body sometimes
                    "severity": a.severity or "medium",
                    "status": "open",
                    "created_at": a.created_at,
                },
                "account": acc_map.get(a.account_id or "", None),
            }
        )

    return {"items": items}


@app.get("/insights/pipeline", dependencies=[Depends(verify_api_key)])
def insights_pipeline(db: Session = Depends(get_db)):
    """
    Dashboard expects:
      total_open_value
      total_open_accounts
      items: [{ account: {id,name,stage}, open_value, open_tasks, last_touch }]
    """
    ws = get_workspace_id()

    # open opps by account
    opps: List[Opportunity] = (
        db.query(Opportunity)
        .filter(Opportunity.workspace_id == ws)
        .all()
    )
    open_value_by_acc: Dict[str, float] = {}
    for o in opps:
        if not o.account_id:
            continue
        if _is_open_opp_stage(o.stage):
            open_value_by_acc[o.account_id] = open_value_by_acc.get(o.account_id, 0.0) + float(o.amount or 0.0)

    # open tasks by account
    tasks: List[Task] = (
        db.query(Task)
        .filter(Task.workspace_id == ws)
        .all()
    )
    open_tasks_by_acc: Dict[str, int] = {}
    for t in tasks:
        if not t.account_id:
            continue
        if (t.status or "open").lower() != "closed":
            open_tasks_by_acc[t.account_id] = open_tasks_by_acc.get(t.account_id, 0) + 1

    # accounts (only those that have any pipeline signal)
    acc_ids = set(open_value_by_acc.keys()) | set(open_tasks_by_acc.keys())
    accounts: List[Account] = []
    if acc_ids:
        accounts = db.query(Account).filter(Account.workspace_id == ws, Account.id.in_(list(acc_ids))).all()

    items = []
    total_open_value = 0.0
    total_open_accounts = 0

    for a in accounts:
        ov = float(open_value_by_acc.get(a.id, 0.0))
        ot = int(open_tasks_by_acc.get(a.id, 0))
        last_touch = a.last_activity_at or a.updated_at or a.created_at

        if ov > 0 or ot > 0:
            total_open_accounts += 1
            total_open_value += ov

        items.append(
            {
                "account": {"id": a.id, "name": a.name, "stage": a.stage or a.buyer_stage},
                "open_value": round(ov, 2),
                "open_tasks": ot,
                "last_touch": last_touch,
            }
        )

    items.sort(key=lambda r: float(r.get("open_value") or 0.0), reverse=True)

    return {
        "total_open_value": round(total_open_value, 2),
        "total_open_accounts": total_open_accounts,
        "items": items[:50],
    }


@app.get("/insights/playbook-coverage", dependencies=[Depends(verify_api_key)])
def insights_playbook_coverage(db: Session = Depends(get_db)):
    """
    Dashboard expects:
      { coverage_pct: number }
    We define "coverage" as % of accounts that have at least one task OR alert generated.
    """
    ws = get_workspace_id()

    total_accounts = db.query(func.count(Account.id)).filter(Account.workspace_id == ws).scalar() or 0
    if total_accounts == 0:
        return {"coverage_pct": 0.0}

    covered_acc_ids = set()

    task_accs = db.query(Task.account_id).filter(Task.workspace_id == ws, Task.account_id.isnot(None)).all()
    for (aid,) in task_accs:
        if aid:
            covered_acc_ids.add(aid)

    alert_accs = db.query(Alert.account_id).filter(Alert.workspace_id == ws, Alert.account_id.isnot(None)).all()
    for (aid,) in alert_accs:
        if aid:
            covered_acc_ids.add(aid)

    coverage_pct = (len(covered_acc_ids) / float(total_accounts)) * 100.0
    return {"coverage_pct": round(coverage_pct, 2)}


@app.get("/insights/competitors", dependencies=[Depends(verify_api_key)])
def insights_competitors(db: Session = Depends(get_db)):
    """
    Dashboard wants rows where:
      row.competitor.name exists
      row.hits_count / row.last_seen
    We build a simple 'competitor activity' list from events metadata OR referrer domains.
    """
    ws = get_workspace_id()
    since = datetime.utcnow() - timedelta(days=30)

    events: List[Event] = (
        db.query(Event)
        .filter(Event.workspace_id == ws, Event.created_at >= since)
        .order_by(Event.created_at.desc())
        .limit(500)
        .all()
    )

    # Aggregate competitor signals
    agg: Dict[str, Dict[str, Any]] = {}
    for e in events:
        meta = e.event_metadata or {}
        cname = meta.get("competitor_name") or meta.get("competitor") or None
        cdom = meta.get("competitor_domain") or meta.get("competitorWebsite") or None

        # fallback: use referrer domain as "competitor-like" if it isn't empty and isn't our own direct
        if not cname and not cdom:
            d = _safe_domain(e.referrer)
            if d and d not in {"", "localhost"}:
                cname = d.split(".")[0].capitalize()
                cdom = d

        if not cname:
            continue

        key = (cdom or cname).lower()
        if key not in agg:
            agg[key] = {
                "competitor": {"id": key, "name": cname, "domain": cdom or ""},
                "hits_count": 0,
                "last_seen": e.created_at,
            }

        agg[key]["hits_count"] += 1
        if e.created_at and agg[key]["last_seen"] and e.created_at > agg[key]["last_seen"]:
            agg[key]["last_seen"] = e.created_at

    items = list(agg.values())
    items.sort(key=lambda r: int(r.get("hits_count") or 0), reverse=True)

    return {"items": items[:12]}


# ------------------------------------------------
# Analytics: attribution & segments
# ------------------------------------------------

@app.post("/analytics/attribution", response_model=AttributionResponse, dependencies=[Depends(verify_api_key)])
def analytics_attribution(payload: AttributionRequest, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    return multi_touch_attribution(db, ws, payload)


@app.post("/analytics/segments", response_model=SegmentationResponse, dependencies=[Depends(verify_api_key)])
def analytics_segments(payload: SegmentationRequest, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    return segment_accounts(db, ws, payload)


# ------------------------------------------------
# CRM export
# ------------------------------------------------

@app.get("/crm/export.csv", dependencies=[Depends(verify_api_key)])
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
        last_ts = (a.last_activity_at or a.updated_at or a.created_at).isoformat()
        row = [
            a.id,
            (a.name or "").replace(",", " "),
            str(a.intent_score or 0.0),
            str(a.engagement_score or 0.0),
            str(a.fit_score or 0.0),
            str(a.predictive_score or 0.0),
            str(a.total_score or 0.0),
            (a.stage or a.buyer_stage or "").replace(",", " "),
            last_ts,
        ]
        output.write(",".join(row) + "\n")

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mmkk_accounts.csv"},
    )
