from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
    # FastAPI setup
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import Base, engine, get_db

# Safe import so Render doesn’t crash if ip_resolver.py is missing
try:
    from ip_resolver import resolve_ipinfo  # type: ignore
except ImportError:
    def resolve_ipinfo(ip: str):
        # Fallback: no enrichment – we still track the visit
        return None

from models import (
    Account,
    Alert,
    AnonymousVisit,
    APIKey,
    Contact,
    Event,
    IpCompanyMap,
    Task,
    Workspace,
)
from schemas import (
    Account360Response,
    AccountCreate,
    AccountRead,
    AccountUpdate,
    ActivityFeedItem,
    ActivityFeedResponse,
    AlertCreate,
    AlertRead,
    AnonymousVisitCreate,
    AnonymousVisitRead,
    ContactCreate,
    ContactRead,
    EventCreate,
    EventRead,
    PipelineStageSummary,
    PipelineAccountRow,
    PipelineSummary,
    TaskCreate,
    TaskRead,
    TimelineItem,
    TopAccountItem,
    TopAccountsResponse,
    TrackEventPayload,
)
from scoring import score_event, _buyer_stage_from_scores

# ------------------------------------------------
# App setup
# ------------------------------------------------

app = FastAPI(
    title="Revenue Engine API",
    version="1.0.0",
    description="6sense + ZoomInfo style revenue intelligence backend",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve dashboard
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return RedirectResponse(url="/static/dashboard.html")


# Create tables
Base.metadata.create_all(bind=engine)

# ------------------------------------------------
# Workspace & API key
# ------------------------------------------------

DEFAULT_WORKSPACE_ID = "default-workspace"
DEFAULT_WORKSPACE_NAME = "Default Workspace"
API_KEY = "supersecret123"  # dev only


@app.on_event("startup")
def bootstrap_workspace_and_key():
    db = next(get_db())
    try:
        ws = (
            db.query(Workspace)
            .filter(Workspace.id == DEFAULT_WORKSPACE_ID)
            .first()
        )
        if not ws:
            ws = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_NAME)
            db.add(ws)
            db.commit()
            db.refresh(ws)

        api_key_row = (
            db.query(APIKey)
            .filter(
                APIKey.workspace_id == DEFAULT_WORKSPACE_ID,
                APIKey.key == API_KEY,
            )
            .first()
        )
        if not api_key_row:
            api_key_row = APIKey(
                workspace_id=DEFAULT_WORKSPACE_ID,
                key=API_KEY,
                label="Default key",
                is_active=True,
            )
            db.add(api_key_row)
            db.commit()
    finally:
        db.close()


def get_workspace_id() -> str:
    return DEFAULT_WORKSPACE_ID


async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------
# ACCOUNTS
# ------------------------------------------------


@app.post(
    "/accounts",
    response_model=AccountRead,
    dependencies=[Depends(verify_api_key)],
)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    account = Account(
        workspace_id=get_workspace_id(),
        **payload.model_dump(),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return AccountRead.model_validate(account)


@app.get(
    "/accounts",
    response_model=List[AccountRead],
    dependencies=[Depends(verify_api_key)],
)
def list_accounts(db: Session = Depends(get_db)):
    accounts = (
        db.query(Account)
        .filter(Account.workspace_id == get_workspace_id())
        .order_by(Account.created_at.desc())
        .all()
    )
    return [AccountRead.model_validate(a) for a in accounts]


@app.get(
    "/accounts/{account_id}",
    response_model=AccountRead,
    dependencies=[Depends(verify_api_key)],
)
def get_account(account_id: str, db: Session = Depends(get_db)):
    account = (
        db.query(Account)
        .filter(
            Account.id == account_id,
            Account.workspace_id == get_workspace_id(),
        )
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountRead.model_validate(account)


@app.patch(
    "/accounts/{account_id}",
    response_model=AccountRead,
    dependencies=[Depends(verify_api_key)],
)
def update_account(
    account_id: str,
    payload: AccountUpdate,
    db: Session = Depends(get_db),
):
    account = (
        db.query(Account)
        .filter(
            Account.id == account_id,
            Account.workspace_id == get_workspace_id(),
        )
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, field, value)

    db.commit()
    db.refresh(account)
    return AccountRead.model_validate(account)


@app.delete(
    "/accounts/{account_id}",
    status_code=204,
    dependencies=[Depends(verify_api_key)],
)
def delete_account(account_id: str, db: Session = Depends(get_db)):
    account = (
        db.query(Account)
        .filter(
            Account.id == account_id,
            Account.workspace_id == get_workspace_id(),
        )
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    db.delete(account)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------
# CONTACTS
# ------------------------------------------------


@app.post(
    "/accounts/{account_id}/contacts",
    response_model=ContactRead,
    dependencies=[Depends(verify_api_key)],
)
def create_contact(
    account_id: str,
    payload: ContactCreate,
    db: Session = Depends(get_db),
):
    ws = get_workspace_id()
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.workspace_id == ws)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    contact = Contact(
        workspace_id=ws,
        account_id=account_id,
        **payload.model_dump(),
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return ContactRead.model_validate(contact)


@app.get(
    "/accounts/{account_id}/contacts",
    response_model=List[ContactRead],
    dependencies=[Depends(verify_api_key)],
)
def list_contacts(account_id: str, db: Session = Depends(get_db)):
    contacts = (
        db.query(Contact)
        .filter(
            Contact.account_id == account_id,
            Contact.workspace_id == get_workspace_id(),
        )
        .order_by(Contact.created_at.desc())
        .all()
    )
    return [ContactRead.model_validate(c) for c in contacts]


# ------------------------------------------------
# EVENTS + SCORING
# ------------------------------------------------


@app.post(
    "/accounts/{account_id}/events",
    response_model=EventRead,
    dependencies=[Depends(verify_api_key)],
)
def create_event(
    account_id: str,
    payload: EventCreate,
    db: Session = Depends(get_db),
):
    ws = get_workspace_id()
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.workspace_id == ws)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if payload.contact_id:
        contact = (
            db.query(Contact)
            .filter(
                Contact.id == payload.contact_id,
                Contact.account_id == account_id,
                Contact.workspace_id == ws,
            )
            .first()
        )
        if not contact:
            raise HTTPException(
                status_code=400,
                detail="Contact not found or not linked to this account",
            )

    event = Event(
        workspace_id=ws,
        account_id=account_id,
        contact_id=payload.contact_id,
        **payload.model_dump(exclude={"contact_id"}),
    )

    event_intent, event_engagement, totals = score_event(account=account, event=event)

    event.intent_score = event_intent
    event.engagement_score = event_engagement

    account.intent_score = totals.intent_score
    account.fit_score = totals.fit_score
    account.engagement_score = totals.engagement_score
    account.predictive_score = totals.predictive_score
    account.total_score = totals.total_score
    account.last_event_at = event.created_at
    account.last_source = event.source or account.last_source
    account.buyer_stage = _buyer_stage_from_scores(
        intent=account.intent_score,
        engagement=account.engagement_score,
        total=account.total_score,
    )

    db.add(event)
    db.add(account)
    db.commit()
    db.refresh(event)
    return EventRead.model_validate(event)


# ------------------------------------------------
# TASKS
# ------------------------------------------------


@app.post(
    "/accounts/{account_id}/tasks",
    response_model=TaskRead,
    dependencies=[Depends(verify_api_key)],
)
def create_task(
    account_id: str,
    payload: TaskCreate,
    db: Session = Depends(get_db),
):
    ws = get_workspace_id()
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.workspace_id == ws)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    task = Task(
        workspace_id=ws,
        account_id=account_id,
        **payload.model_dump(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return TaskRead.model_validate(task)


@app.get(
    "/accounts/{account_id}/tasks",
    response_model=List[TaskRead],
    dependencies=[Depends(verify_api_key)],
)
def list_tasks(account_id: str, db: Session = Depends(get_db)):
    tasks = (
        db.query(Task)
        .filter(
            Task.account_id == account_id,
            Task.workspace_id == get_workspace_id(),
        )
        .order_by(Task.created_at.desc())
        .all()
    )
    return [TaskRead.model_validate(t) for t in tasks]


# ------------------------------------------------
# ALERTS
# ------------------------------------------------


@app.post(
    "/alerts",
    response_model=AlertRead,
    dependencies=[Depends(verify_api_key)],
)
def create_alert(payload: AlertCreate, db: Session = Depends(get_db)):
    alert = Alert(
        workspace_id=get_workspace_id(),
        account_id=payload.account_id,
        title=payload.title,
        body=payload.body,
        type=payload.type,
        severity=payload.severity,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return AlertRead.model_validate(alert)


@app.get(
    "/alerts",
    response_model=List[AlertRead],
    dependencies=[Depends(verify_api_key)],
)
def list_alerts(db: Session = Depends(get_db)):
    alerts = (
        db.query(Alert)
        .filter(Alert.workspace_id == get_workspace_id())
        .order_by(Alert.created_at.desc())
        .all()
    )
    return [AlertRead.model_validate(a) for a in alerts]

# ------------------------------------------------
# SIMPLE PLAYBOOK ENGINE (HIGH-INTENT RULE)
# ------------------------------------------------

def evaluate_playbooks_for_account(db: Session, account: Account):
    """
    Demo playbook engine.

    For now: whenever this is called for an account, create:
    - 1 high-intent alert
    - 1 follow-up task

    Later we can make this respect real playbook configs & thresholds.
    """
    ws = account.workspace_id
    created_tasks = 0
    created_alerts = 0

    total = float(account.total_score or 0.0)
    intent = float(account.intent_score or 0.0)

    # You can tighten this later (e.g. >= 3); for demo we just require some score
    if total >= 0 or intent >= 0:
        alert = Alert(
            workspace_id=ws,
            account_id=account.id,
            title=f"High intent: {account.name}",
            body=f"Automation rule fired for {account.name} (total={total}, intent={intent}).",
            type="high_intent",
            severity="high",
        )
        db.add(alert)
        created_alerts = 1

        task = Task(
            workspace_id=ws,
            account_id=account.id,
            title=f"Follow up with {account.name}",
            description="Auto-created from high-intent rule.",
            status="open",
            owner=account.owner,
            source="playbook_high_intent",
        )
        db.add(task)
        created_tasks = 1

        db.commit()

    return created_tasks, created_alerts


# ------------------------------------------------
# ANONYMOUS VISITS (raw table)
# ------------------------------------------------


@app.post(
    "/anon-visits",
    response_model=AnonymousVisitRead,
    dependencies=[Depends(verify_api_key)],
)
def create_anon_visit(payload: AnonymousVisitCreate, db: Session = Depends(get_db)):
    visit = AnonymousVisit(
        workspace_id=get_workspace_id(),
        **payload.model_dump(),
    )
    db.add(visit)
    db.commit()
    db.refresh(visit)
    return AnonymousVisitRead.model_validate(visit)


@app.get(
    "/anon-visits",
    response_model=List[AnonymousVisitRead],
    dependencies=[Depends(verify_api_key)],
)
def list_anon_visits(db: Session = Depends(get_db)):
    visits = (
        db.query(AnonymousVisit)
        .filter(AnonymousVisit.workspace_id == get_workspace_id())
        .order_by(AnonymousVisit.created_at.desc())
        .all()
    )
    return [AnonymousVisitRead.model_validate(v) for v in visits]


# ------------------------------------------------
# TRACK (website/product intake with API key)
# ------------------------------------------------


@app.post(
    "/track",
    dependencies=[Depends(verify_api_key)],
)
def track(
    payload: TrackEventPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    ws = get_workspace_id()

    ip = payload.ip or (request.client.host if request.client else None)
    ua = payload.user_agent
    url = payload.url
    metadata = payload.metadata or {}

    ipinfo_data = resolve_ipinfo(ip) if ip else None

    country = ipinfo_data.get("country") if ipinfo_data else None
    city = ipinfo_data.get("city") if ipinfo_data else None
    company_guess = ipinfo_data.get("org") if ipinfo_data else None
    raw = ipinfo_data.get("raw") if ipinfo_data else None

    if ip and ipinfo_data:
        existing_map = (
            db.query(IpCompanyMap)
            .filter(IpCompanyMap.workspace_id == ws, IpCompanyMap.ip == ip)
            .first()
        )
        if not existing_map:
            ip_map = IpCompanyMap(
                workspace_id=ws,
                ip=ip,
                company_name=company_guess,
                domain=None,
                country=country,
                city=city,
                source="ipinfo",
            )
            db.add(ip_map)

    anon_visit = AnonymousVisit(
        workspace_id=ws,
        account_id=payload.account_id,
        ip=ip,
        user_agent=ua,
        url=url,
        referrer=metadata.get("referrer"),
        country=country,
        city=city,
        company_guess=company_guess,
        raw=raw,
    )
    db.add(anon_visit)

    created_event_id: Optional[str] = None

    if payload.account_id:
        account = (
            db.query(Account)
            .filter(Account.id == payload.account_id, Account.workspace_id == ws)
            .first()
        )
        if account:
            event = Event(
                workspace_id=ws,
                account_id=account.id,
                contact_id=payload.contact_id,
                event_type=payload.event_type or "pageview",
                source="website",
                url=url,
                event_metadata=metadata,
            )

            event_intent, event_engagement, totals = score_event(
                account=account,
                event=event,
            )

            event.intent_score = event_intent
            event.engagement_score = event_engagement

            account.intent_score = totals.intent_score
            account.fit_score = totals.fit_score
            account.engagement_score = totals.engagement_score
            account.predictive_score = totals.predictive_score
            account.total_score = totals.total_score

            account.buyer_stage = _buyer_stage_from_scores(
                intent=account.intent_score,
                engagement=account.engagement_score,
                total=account.total_score,
            )
            account.last_event_at = event.created_at
            account.last_source = event.source or account.last_source

            db.add(event)
            db.add(account)
            db.flush()
            created_event_id = event.id

    db.commit()
    db.refresh(anon_visit)

    return {
        "status": "ok",
        "visit_id": anon_visit.id,
        "event_id": created_event_id,
        "ip_enriched": bool(ipinfo_data),
    }


# ------------------------------------------------
# PUBLIC ANONYMOUS TRACKING (no API key)
# ------------------------------------------------

@app.post("/public/track")
async def public_track(request: Request, db: Session = Depends(get_db)):
    """
    Lightweight anonymous tracking endpoint for website visitors.
    No API key required – safe for embedding directly in frontend JS.
    """
    ws = get_workspace_id()
    data = await request.json()

    url = data.get("url")
    referrer = data.get("referrer")
    ip = data.get("ip") or (request.client.host if request.client else None)
    ua = request.headers.get("user-agent")

    anon_visit = AnonymousVisit(
        workspace_id=ws,
        url=url,
        referrer=referrer,
        ip=ip,
        user_agent=ua,
    )
    db.add(anon_visit)
    db.commit()
    db.refresh(anon_visit)

    return {"status": "ok", "visit_id": anon_visit.id}


# ------------------------------------------------
# INSIGHTS: TOP ACCOUNTS
# ------------------------------------------------


@app.get(
    "/insights/top-accounts",
    response_model=TopAccountsResponse,
    dependencies=[Depends(verify_api_key)],
)
def insights_top_accounts(limit: int = 50, db: Session = Depends(get_db)):
    ws = get_workspace_id()
    accounts = (
        db.query(Account)
        .filter(Account.workspace_id == ws)
        .order_by(Account.total_score.desc())
        .limit(limit)
        .all()
    )
    items: List[TopAccountItem] = []
    for a in accounts:
        items.append(
            TopAccountItem(
                id=a.id,
                name=a.name,
                intent_score=a.intent_score or 0.0,
                engagement_score=a.engagement_score or 0.0,
                fit_score=a.fit_score or 0.0,
                predictive_score=a.predictive_score or 0.0,
                total_score=a.total_score or 0.0,
                buyer_stage=a.buyer_stage,
                last_event_at=a.last_event_at,
                last_source=a.last_source,
                country=a.country,
                industry=a.industry,
            )
        )
    return TopAccountsResponse(items=items)


# ------------------------------------------------
# INSIGHTS: ACTIVITY FEED
# ------------------------------------------------


@app.get(
    "/insights/activity-feed",
    response_model=ActivityFeedResponse,
    dependencies=[Depends(verify_api_key)],
)
def insights_activity_feed(limit: int = 100, db: Session = Depends(get_db)):
    ws = get_workspace_id()

    events = (
        db.query(Event)
        .join(Account, Event.account_id == Account.id)
        .filter(Event.workspace_id == ws)
        .order_by(Event.created_at.desc())
        .limit(limit)
        .all()
    )
    alerts = (
        db.query(Alert)
        .outerjoin(Account, Alert.account_id == Account.id)
        .filter(Alert.workspace_id == ws)
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )
    tasks = (
        db.query(Task)
        .join(Account, Task.account_id == Account.id)
        .filter(Task.workspace_id == ws)
        .order_by(Task.created_at.desc())
        .limit(limit)
        .all()
    )
    visits = (
        db.query(AnonymousVisit)
        .outerjoin(Account, AnonymousVisit.account_id == Account.id)
        .filter(AnonymousVisit.workspace_id == ws)
        .order_by(AnonymousVisit.created_at.desc())
        .limit(limit)
        .all()
    )

    items: List[ActivityFeedItem] = []

    for e in events:
        acc = e.account
        items.append(
            ActivityFeedItem(
                id=e.id,
                account_id=e.account_id,
                account_name=acc.name if acc else None,
                type="event",
                source=e.source,
                url=e.url,
                created_at=e.created_at,
                summary=f"{e.event_type} via {e.source or 'unknown'}",
                intent_score=e.intent_score or 0.0,
                buyer_stage=acc.buyer_stage if acc else None,
            )
        )

    for a in alerts:
        acc = a.account
        items.append(
            ActivityFeedItem(
                id=a.id,
                account_id=a.account_id,
                account_name=acc.name if acc else None,
                type="alert",
                source=a.type,
                url=None,
                created_at=a.created_at,
                summary=a.title,
                intent_score=acc.intent_score if acc else 0.0,
                buyer_stage=acc.buyer_stage if acc else None,
            )
        )

    for t in tasks:
        acc = t.account
        items.append(
            ActivityFeedItem(
                id=t.id,
                account_id=t.account_id,
                account_name=acc.name if acc else None,
                type="task",
                source=t.source,
                url=None,
                created_at=t.created_at,
                summary=f"{t.status.upper()} task: {t.title}",
                intent_score=acc.intent_score if acc else 0.0,
                buyer_stage=acc.buyer_stage if acc else None,
            )
        )

    for v in visits:
        acc = v.account
        items.append(
            ActivityFeedItem(
                id=v.id,
                account_id=v.account_id,
                account_name=acc.name if acc else None,
                type="anon_visit",
                source="website",
                url=v.url,
                created_at=v.created_at,
                summary=f"Anonymous visit from {v.country or 'unknown country'}",
                intent_score=acc.intent_score if acc else 0.0,
                buyer_stage=acc.buyer_stage if acc else None,
            )
        )

    items.sort(key=lambda i: i.created_at, reverse=True)
    items = items[:limit]

    return ActivityFeedResponse(items=items)


# ------------------------------------------------
# INSIGHTS: ANON VISITS (for dashboard)
# ------------------------------------------------


@app.get(
    "/insights/anon-visits",
    dependencies=[Depends(verify_api_key)],
)
def insights_anon_visits(db: Session = Depends(get_db), limit: int = 200):
    visits = (
        db.query(AnonymousVisit)
        .filter(AnonymousVisit.workspace_id == get_workspace_id())
        .order_by(AnonymousVisit.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "session_id": v.id,
            "url": v.url,
            "referrer": v.referrer,
            "created_at": v.created_at,
        }
        for v in visits
    ]


# ------------------------------------------------
# INSIGHTS: PLAYBOOK COVERAGE
# ------------------------------------------------


@app.get(
    "/insights/playbook-coverage",
    dependencies=[Depends(verify_api_key)],
)
def insights_playbook_coverage(db: Session = Depends(get_db)):
    ws = get_workspace_id()

    total_accounts = (
        db.query(func.count(Account.id))
        .filter(Account.workspace_id == ws)
        .scalar()
        or 0
    )

    covered_accounts = (
        db.query(func.count(Account.id))
        .filter(
            Account.workspace_id == ws,
            Account.buyer_stage.isnot(None),
            Account.buyer_stage != "unaware",
        )
        .scalar()
        or 0
    )

    coverage_pct = (
        round(covered_accounts / total_accounts * 100, 2)
        if total_accounts
        else 0.0
    )

    return {"coverage_pct": coverage_pct}


# ------------------------------------------------
# INSIGHTS: COMPETITORS (stub)
# ------------------------------------------------


@app.get(
    "/insights/competitors",
    dependencies=[Depends(verify_api_key)],
)
def insights_competitors(db: Session = Depends(get_db)):
    """
    Simple stub to keep the dashboard happy.

    The frontend calls `/insights/competitors` and expects an object
    with an `items` array. Each item can have:
      - id, name
      - hitsCount
      - topAccounts: list of accounts with scores

    For now we synthesize a single "Market competitors" group that
    just reuses your top accounts.
    """
    ws = get_workspace_id()

    # Reuse top accounts as "competitor hits"
    top_accounts = (
        db.query(Account)
        .filter(Account.workspace_id == ws)
        .order_by(Account.total_score.desc())
        .limit(10)
        .all()
    )

    top_accounts_payload = [
        {
            "id": a.id,
            "name": a.name,
            "domain": a.domain,
            "totalScore": float(a.total_score or 0.0),
            "intentScore": float(a.intent_score or 0.0),
            "engagementScore": float(a.engagement_score or 0.0),
            "fitScore": float(a.fit_score or 0.0),
            "buyerStage": a.buyer_stage,
        }
        for a in top_accounts
    ]

    competitor_obj = {
        "id": "market-competitors",
        "name": "Market competitors",
        "website": None,
        "category": "generic",
        "notes": "Synthetic competitor grouping for demo coverage.",
        "created_at": datetime.utcnow().isoformat(),
        "hitsCount": len(top_accounts_payload),
        "topAccounts": top_accounts_payload,
    }

    # IMPORTANT: frontend expects `{ items: [...] }`
    return {"items": [competitor_obj]}


# ------------------------------------------------
# INSIGHTS: PIPELINE
# ------------------------------------------------


@app.get(
    "/insights/pipeline",
    response_model=PipelineSummary,
    dependencies=[Depends(verify_api_key)],
)
def insights_pipeline(db: Session = Depends(get_db)):
    """Return accounts with open pipeline + stage counts.

    This powers the dashboard pipeline table and header stats.
    """
    ws = get_workspace_id()

    # Load all accounts for this workspace
    accounts = (
        db.query(Account)
        .filter(Account.workspace_id == ws)
        .all()
    )

    # Aggregate open tasks per account
    from collections import defaultdict

    open_tasks_by_account = defaultdict(int)
    rows_tasks = (
        db.query(Task.account_id, func.count(Task.id))
        .filter(
            Task.workspace_id == ws,
            Task.status != "done",
        )
        .group_by(Task.account_id)
        .all()
    )
    for acc_id, cnt in rows_tasks:
        open_tasks_by_account[acc_id] = cnt

    # Aggregate open opportunity value per account
    open_value_by_account = defaultdict(float)
    rows_opps = (
        db.query(Opportunity.account_id, func.coalesce(func.sum(Opportunity.amount), 0.0))
        .filter(
            Opportunity.workspace_id == ws,
            Opportunity.status != "won",
        )
        .group_by(Opportunity.account_id)
        .all()
    )
    for acc_id, total_amount in rows_opps:
        open_value_by_account[acc_id] = float(total_amount or 0.0)

    items: List[PipelineAccountRow] = []
    total_open_value = 0.0
    total_open_accounts = 0

    for acc in accounts:
        open_value = open_value_by_account.get(acc.id, 0.0)
        open_tasks = open_tasks_by_account.get(acc.id, 0)
        last_touch = acc.last_event_at

        # We consider an account "with open pipeline" if it has open value OR open tasks
        if open_value > 0 or open_tasks > 0:
            total_open_accounts += 1
            total_open_value += open_value

        items.append(
            PipelineAccountRow(
                account=AccountRead.model_validate(acc),
                open_value=open_value,
                open_tasks=open_tasks,
                last_touch=last_touch,
            )
        )

    return PipelineSummary(
        total_open_value=total_open_value,
        total_open_accounts=total_open_accounts,
        items=items,
    )


# ------------------------------------------------
# ACCOUNT 360
# ------------------------------------------------


@app.get(
    "/accounts/{account_id}/360",
    response_model=Account360Response,
    dependencies=[Depends(verify_api_key)],
)
def account_360(account_id: str, db: Session = Depends(get_db)):
    ws = get_workspace_id()

    acc = (
        db.query(Account)
        .filter(Account.id == account_id, Account.workspace_id == ws)
        .first()
    )
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    events = (
        db.query(Event)
        .filter(Event.account_id == account_id, Event.workspace_id == ws)
        .order_by(Event.created_at.desc())
        .all()
    )
    alerts = (
        db.query(Alert)
        .filter(Alert.account_id == account_id, Alert.workspace_id == ws)
        .order_by(Alert.created_at.desc())
        .all()
    )
    tasks = (
        db.query(Task)
        .filter(Task.account_id == account_id, Task.workspace_id == ws)
        .order_by(Task.created_at.desc())
        .all()
    )
    visits = (
        db.query(AnonymousVisit)
        .filter(
            AnonymousVisit.account_id == account_id,
            AnonymousVisit.workspace_id == ws,
        )
        .order_by(AnonymousVisit.created_at.desc())
        .all()
    )

    timeline: List[TimelineItem] = []

    for e in events:
        timeline.append(
            TimelineItem(
                type="event",
                created_at=e.created_at,
                summary=f"{e.event_type} via {e.source or 'unknown'}",
                payload=EventRead.model_validate(e).model_dump(),
            )
        )

    for a in alerts:
        timeline.append(
            TimelineItem(
                type="alert",
                created_at=a.created_at,
                summary=a.title,
                payload=AlertRead.model_validate(a).model_dump(),
            )
        )

    for t in tasks:
        timeline.append(
            TimelineItem(
                type="task",
                created_at=t.created_at,
                summary=f"{t.status.upper()} task: {t.title}",
                payload=TaskRead.model_validate(t).model_dump(),
            )
        )

    for v in visits:
        timeline.append(
            TimelineItem(
                type="anon_visit",
                created_at=v.created_at,
                summary=f"Anonymous visit from {v.country or 'unknown country'}",
                payload=AnonymousVisitRead.model_validate(v).model_dump(),
            )
        )

    timeline.sort(key=lambda x: x.created_at, reverse=True)

    anon_visit_count = len(visits)
    anon_last_seen = visits[0].created_at if visits else None
    last_seen = timeline[0].created_at if timeline else None

    signals: List[Dict[str, Any]] = [
        {"label": "Total events", "value": len(events)},
        {"label": "Open tasks", "value": len([t for t in tasks if t.status != "done"])},
        {"label": "Alerts", "value": len(alerts)},
        {"label": "Anon visits", "value": anon_visit_count},
    ]

    next_best_action = "Reach out with a tailored demo"
    next_best_action_reason = (
        "High scores and recent activity indicate strong buying intent."
        if (acc.intent_score or 0.0) + (acc.engagement_score or 0.0) > 20
        else "Low recent activity; consider nurture or remarketing."
    )

    playbook_label = acc.buyer_stage or "unaware"
    enrichment_summary = (
        f"{acc.name} in {acc.country or 'unknown country'} with intent score {acc.intent_score:.1f}."
    )

    return Account360Response(
        account=AccountRead.model_validate(acc),
        events_count=len(events),
        last_seen=last_seen,
        country=acc.country,
        intent_score=acc.intent_score or 0.0,
        fit_score=acc.fit_score or 0.0,
        engagement_score=acc.engagement_score or 0.0,
        predictive_score=acc.predictive_score or 0.0,
        total_score=acc.total_score or 0.0,
        buyer_stage=acc.buyer_stage,
        last_source=acc.last_source,
        anon_visit_count=anon_visit_count,
        anon_last_seen=anon_last_seen,
        signals=signals,
        next_best_action=next_best_action,
        next_best_action_reason=next_best_action_reason,
        playbook_label=playbook_label,
        enrichment_summary=enrichment_summary,
        timeline=timeline,
    )


# -----------------------
# CRM / Opportunities / Playbooks endpoints
# -----------------------

from models import CRMConnection, ExternalObjectMap, Opportunity, PlaybookRule
from schemas import (
    CRMAccountUpsert,
    CRMContactUpsert,
    CRMOpportunityUpsert,
    OpportunityCreate,
    OpportunityRead,
    OpportunityUpdate,
    PlaybookRuleCreate,
    PlaybookRuleRead,
    AccountRead,
)


def _account_matches_rule(db: Session, account: Account, rule: PlaybookRule) -> bool:
    # Score thresholds
    if rule.min_total_score is not None and (account.total_score or 0.0) < rule.min_total_score:
        return False
    if rule.min_intent_score is not None and (account.intent_score or 0.0) < rule.min_intent_score:
        return False

    # Buyer stage filter
    if rule.buyer_stage_in:
        if (account.buyer_stage or "").lower() not in {s.lower() for s in rule.buyer_stage_in}:
            return False

    # Country filter
    if rule.countries_in:
        if (account.country or "").lower() not in {c.lower() for c in rule.countries_in}:
            return False

    # Pipeline stage filter
    if rule.stages_in:
        if (account.stage or "").lower() not in {s.lower() for s in rule.stages_in}:
            return False

    # Has / doesn't have open tasks
    if rule.has_open_tasks is not None:
        open_count = (
            db.query(Task)
            .filter(
                Task.workspace_id == account.workspace_id,
                Task.account_id == account.id,
                Task.status != "done",
            )
            .count()
        )
        has_open = open_count > 0
        if has_open != rule.has_open_tasks:
            return False

    return True


def run_playbooks_for_account(db: Session, account: Account) -> None:
    """Evaluate playbook rules and create tasks/alerts."""
    rules = (
        db.query(PlaybookRule)
        .filter(
            PlaybookRule.workspace_id == account.workspace_id,
            PlaybookRule.is_active == True,  # noqa: E712
        )
        .all()
    )

    for rule in rules:
        if not _account_matches_rule(db, account, rule):
            continue

        # Actions
        if rule.create_task:
            title = rule.task_title_template or f"Follow up with {account.name}"
            task = Task(
                workspace_id=account.workspace_id,
                account_id=account.id,
                title=title,
                description=rule.description,
                owner=rule.owner,
                source="playbook",
            )
            db.add(task)

        if rule.create_alert:
            title = rule.alert_title_template or f"Playbook triggered: {rule.name}"
            alert = Alert(
                workspace_id=account.workspace_id,
                account_id=account.id,
                title=title,
                body=rule.description,
                type="playbook",
                severity=rule.alert_severity or "medium",
            )
            db.add(alert)

        # push_to_crm would be handled later by a background worker or connector


# -------- CRM Upserts --------


@app.post(
    "/crm/{provider}/accounts/upsert",
    response_model=AccountRead,
    dependencies=[Depends(verify_api_key)],
)
def crm_upsert_account(
    provider: str,
    payload: CRMAccountUpsert,
    db: Session = Depends(get_db),
):
    workspace_id = get_workspace_id()

    mapping = (
        db.query(ExternalObjectMap)
        .filter(
            ExternalObjectMap.workspace_id == workspace_id,
            ExternalObjectMap.provider == provider,
            ExternalObjectMap.external_object_type == "account",
            ExternalObjectMap.external_id == payload.external_id,
        )
        .first()
    )

    if mapping:
        account = db.query(Account).filter(
            Account.workspace_id == workspace_id,
            Account.id == mapping.internal_id,
        ).first()
        if not account:
            # mapping is stale, treat as new
            mapping = None

    if not mapping:
        account = Account(
            workspace_id=workspace_id,
            name=payload.name,
            domain=payload.domain,
            owner=payload.owner,
            country=payload.country,
            industry=payload.industry,
        )
        db.add(account)
        db.flush()  # get id

        mapping = ExternalObjectMap(
            workspace_id=workspace_id,
            provider=provider,
            external_object_type="account",
            external_id=payload.external_id,
            internal_object_type="account",
            internal_id=account.id,
        )
        db.add(mapping)
    else:
        # update existing account
        if payload.name:
            account.name = payload.name
        account.domain = payload.domain or account.domain
        account.owner = payload.owner or account.owner
        account.country = payload.country or account.country
        account.industry = payload.industry or account.industry
        db.add(account)

    db.commit()
    db.refresh(account)
    return AccountRead.model_validate(account)


@app.post(
    "/crm/{provider}/contacts/upsert",
    dependencies=[Depends(verify_api_key)],
)
def crm_upsert_contact(
    provider: str,
    payload: CRMContactUpsert,
    db: Session = Depends(get_db),
):
    workspace_id = get_workspace_id()

    account_id = None
    if payload.account_external_id:
        mapping = (
            db.query(ExternalObjectMap)
            .filter(
                ExternalObjectMap.workspace_id == workspace_id,
                ExternalObjectMap.provider == provider,
                ExternalObjectMap.external_object_type == "account",
                ExternalObjectMap.external_id == payload.account_external_id,
            )
            .first()
        )
        if mapping:
            account_id = mapping.internal_id

    if not account_id:
        raise HTTPException(status_code=400, detail="Unknown account_external_id for contact upsert")

    contact = (
        db.query(Contact)
        .filter(
            Contact.workspace_id == workspace_id,
            Contact.account_id == account_id,
            Contact.email == payload.email,
        )
        .first()
    )

    if not contact:
        contact = Contact(
            workspace_id=workspace_id,
            account_id=account_id,
            name=payload.name,
            email=payload.email,
            title=payload.title,
            phone=payload.phone,
        )
        db.add(contact)
    else:
        contact.name = payload.name or contact.name
        contact.title = payload.title or contact.title
        contact.phone = payload.phone or contact.phone
        db.add(contact)

    db.commit()
    return {"status": "ok"}


@app.post(
    "/crm/{provider}/opportunities/upsert",
    response_model=OpportunityRead,
    dependencies=[Depends(verify_api_key)],
)
def crm_upsert_opportunity(
    provider: str,
    payload: CRMOpportunityUpsert,
    db: Session = Depends(get_db),
):
    workspace_id = get_workspace_id()

    # Find account by external id mapping
    account_mapping = (
        db.query(ExternalObjectMap)
        .filter(
            ExternalObjectMap.workspace_id == workspace_id,
            ExternalObjectMap.provider == provider,
            ExternalObjectMap.external_object_type == "account",
            ExternalObjectMap.external_id == payload.account_external_id,
        )
        .first()
    )
    if not account_mapping:
        raise HTTPException(status_code=400, detail="Unknown account_external_id for opportunity upsert")

    account_id = account_mapping.internal_id

    opp = (
        db.query(Opportunity)
        .filter(
            Opportunity.workspace_id == workspace_id,
            Opportunity.external_id == payload.external_id,
        )
        .first()
    )

    if not opp:
        opp = Opportunity(
            workspace_id=workspace_id,
            account_id=account_id,
            name=payload.name,
            amount=payload.amount,
            currency=payload.currency,
            stage=payload.stage,
            status=payload.status,
            close_date=payload.close_date,
            source=payload.source or provider,
            external_id=payload.external_id,
        )
        db.add(opp)
    else:
        opp.account_id = account_id
        opp.name = payload.name or opp.name
        if payload.amount is not None:
            opp.amount = payload.amount
        opp.currency = payload.currency or opp.currency
        opp.stage = payload.stage or opp.stage
        opp.status = payload.status or opp.status
        opp.close_date = payload.close_date or opp.close_date
        opp.source = payload.source or opp.source
        db.add(opp)

    db.commit()
    db.refresh(opp)
    return OpportunityRead.model_validate(opp)


# -------- Native Opportunity CRUD --------


@app.post(
    "/opportunities",
    response_model=OpportunityRead,
    dependencies=[Depends(verify_api_key)],
)
def create_opportunity(
    payload: OpportunityCreate,
    db: Session = Depends(get_db),
):
    workspace_id = get_workspace_id()

    account = (
        db.query(Account)
        .filter(
            Account.workspace_id == workspace_id,
            Account.id == payload.account_id,
        )
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    opp = Opportunity(
        workspace_id=workspace_id,
        account_id=payload.account_id,
        name=payload.name,
        amount=payload.amount,
        currency=payload.currency,
        stage=payload.stage,
        status=payload.status,
        close_date=payload.close_date,
        source=payload.source,
        external_id=payload.external_id,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return OpportunityRead.model_validate(opp)


@app.get(
    "/opportunities",
    response_model=List[OpportunityRead],
    dependencies=[Depends(verify_api_key)],
)
def list_opportunities(
    account_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    workspace_id = get_workspace_id()
    q = db.query(Opportunity).filter(Opportunity.workspace_id == workspace_id)
    if account_id:
        q = q.filter(Opportunity.account_id == account_id)

    opps = q.order_by(Opportunity.created_at.desc()).all()
    return [OpportunityRead.model_validate(o) for o in opps]


# -------- Playbooks CRUD and manual trigger --------


@app.post(
    "/playbooks",
    response_model=PlaybookRuleRead,
    dependencies=[Depends(verify_api_key)],
)
def create_playbook_rule(
    payload: PlaybookRuleCreate,
    db: Session = Depends(get_db),
):
    workspace_id = get_workspace_id()

    rule = PlaybookRule(
        workspace_id=workspace_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        min_total_score=payload.min_total_score,
        min_intent_score=payload.min_intent_score,
        buyer_stage_in=payload.buyer_stage_in,
        countries_in=payload.countries_in,
        stages_in=payload.stages_in,
        has_open_tasks=payload.has_open_tasks,
        create_task=payload.create_task,
        create_alert=payload.create_alert,
        push_to_crm=payload.push_to_crm,
        task_title_template=payload.task_title_template,
        alert_title_template=payload.alert_title_template,
        alert_severity=payload.alert_severity,
        owner=payload.owner,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return PlaybookRuleRead.model_validate(rule)


@app.get(
    "/playbooks",
    response_model=List[PlaybookRuleRead],
    dependencies=[Depends(verify_api_key)],
)
def list_playbook_rules(
    db: Session = Depends(get_db),
):
    workspace_id = get_workspace_id()
    rules = (
        db.query(PlaybookRule)
        .filter(PlaybookRule.workspace_id == workspace_id)
        .order_by(PlaybookRule.created_at.desc())
        .all()
    )
    return [PlaybookRuleRead.model_validate(r) for r in rules]


@app.post(
    "/accounts/{account_id}/run-playbooks",
    dependencies=[Depends(verify_api_key)],
)
def run_playbooks_for_account(
    account_id: str,
    db: Session = Depends(get_db),
):
    ws = get_workspace_id()

    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.workspace_id == ws)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    created_tasks, created_alerts = evaluate_playbooks_for_account(db, account)

    return {
        "account_id": account.id,
        "created_tasks": created_tasks,
        "created_alerts": created_alerts,
    }
