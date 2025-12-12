from __future__ import annotations

import os
import uuid
import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, List

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from database import Base, engine, get_db, DATABASE_URL
from models import (
    Workspace,
    APIKey,
    Account,
    Contact,
    Event,
    AnonymousVisit,
    Task,
    Alert,
    IpCompanyMap,
)


# -----------------------------
# ENV / Defaults
# -----------------------------
DEFAULT_WORKSPACE_ID = os.getenv("DEFAULT_WORKSPACE_ID", "default")
DEFAULT_WORKSPACE_NAME = os.getenv("DEFAULT_WORKSPACE_NAME", "Default Workspace")

# Put this in Render env var (recommended)
MMKK_DEFAULT_API_KEY = os.getenv("MMKK_DEFAULT_API_KEY", "supersecret123")

# Demo mode: allow /public/track without API key (set false for production)
ALLOW_PUBLIC_TRACK_NO_KEY = os.getenv("ALLOW_PUBLIC_TRACK_NO_KEY", "true").lower() == "true"


def _uuid() -> str:
    return str(uuid.uuid4())


# If local sqlite, auto-create
if DATABASE_URL.startswith("sqlite"):
    Base.metadata.create_all(bind=engine)


app = FastAPI(title="MMKK Revenue Engine API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve /static/*
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# -----------------------------
# Startup bootstrap (IDEMPOTENT)
# fixes your UniqueViolation: api_keys.key already exists
# -----------------------------
@app.on_event("startup")
def bootstrap_defaults():
    db = next(get_db())
    try:
        ws = db.query(Workspace).filter(Workspace.id == DEFAULT_WORKSPACE_ID).first()
        if not ws:
            ws = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_NAME)
            db.add(ws)
            db.commit()

        existing_key = db.query(APIKey).filter(APIKey.key == MMKK_DEFAULT_API_KEY).first()
        if not existing_key:
            db.add(
                APIKey(
                    id=_uuid(),
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    key=MMKK_DEFAULT_API_KEY,
                    label="Default demo key",
                    is_active=True,
                )
            )
            db.commit()

    finally:
        db.close()


# -----------------------------
# Health (GET + HEAD) fixes 405
# -----------------------------
@app.get("/health")
def health_get():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


@app.head("/health")
def health_head():
    return Response(status_code=200)


# -----------------------------
# Auth helpers
# -----------------------------
def _require_api_key(x_api_key: Optional[str]) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    return x_api_key


def verify_key_and_workspace(db: Session, x_api_key: Optional[str]) -> str:
    key_value = _require_api_key(x_api_key)
    key_row = db.query(APIKey).filter(APIKey.key == key_value, APIKey.is_active == True).first()  # noqa: E712
    if not key_row:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key_row.workspace_id


# -----------------------------
# Attribution helpers
# -----------------------------
def derive_channel(utm: Optional[Dict[str, Any]], referrer: Optional[str]) -> str:
    utm = utm or {}
    src = (utm.get("source") or "").lower()
    med = (utm.get("medium") or "").lower()

    if med in {"cpc", "ppc", "paid", "paid_search"}:
        return "paid_search"
    if med in {"paid_social", "paidsocial"} or src in {"facebook", "instagram", "tiktok", "linkedin", "x"}:
        return "paid_social"
    if med in {"social"}:
        return "social"
    if med == "email":
        return "email"
    if med == "affiliate":
        return "affiliate"
    if med == "referral":
        return "referral"
    if referrer:
        return "referral"
    return "direct"


# -----------------------------
# Tracking: Public pixel endpoint
# -----------------------------
@app.post("/public/track")
async def public_track(
    request: Request,
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    # If key provided, enforce it. Otherwise allow only if demo mode enabled.
    if x_api_key:
        workspace_id = verify_key_and_workspace(db, x_api_key)
    else:
        if not ALLOW_PUBLIC_TRACK_NO_KEY:
            raise HTTPException(status_code=401, detail="Missing X-API-Key")
        workspace_id = DEFAULT_WORKSPACE_ID

    payload = await request.json()

    event_type = payload.get("event_type") or payload.get("type") or "event"
    anonymous_id = payload.get("anonymous_id") or payload.get("anon_id") or ("anon_" + _uuid()[:12])

    url = payload.get("url")
    path = payload.get("path")
    referrer = payload.get("referrer")
    utm = payload.get("utm") or {}
    event_metadata = payload.get("metadata") or {}

    ip = payload.get("ip") or (request.client.host if request.client else None)
    user_agent = request.headers.get("user-agent")

    channel = payload.get("channel") or derive_channel(utm, referrer)

    ev = Event(
        id=_uuid(),
        workspace_id=workspace_id,
        account_id=payload.get("account_id"),
        anonymous_id=anonymous_id,
        email=payload.get("email"),
        event_type=str(event_type),
        url=url,
        path=path,
        referrer=referrer,
        user_agent=user_agent,
        ip=ip,
        utm=utm,
        channel=channel,
        event_metadata=event_metadata,
    )
    db.add(ev)

    # Keep anon-visits for dashboard
    av = (
        db.query(AnonymousVisit)
        .filter(AnonymousVisit.workspace_id == workspace_id, AnonymousVisit.anonymous_id == anonymous_id)
        .first()
    )
    if not av:
        av = AnonymousVisit(
            id=_uuid(),
            workspace_id=workspace_id,
            anonymous_id=anonymous_id,
            ip=ip,
            user_agent=user_agent,
            url=url,
            referrer=referrer,
            raw={"utm": utm, "channel": channel},
        )
        db.add(av)
    else:
        av.ip = ip
        av.user_agent = user_agent
        av.url = url
        av.referrer = referrer

    db.commit()
    return {"status": "ok", "event_id": ev.id, "anonymous_id": anonymous_id, "channel": channel}


# Backward-compatible alias: your UI can call /track too
@app.post("/track")
async def track_alias(
    request: Request,
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    return await public_track(request=request, db=db, x_api_key=x_api_key)


@app.get("/pixel.js")
def pixel_js():
    """
    Install on ANY website:
      <script src="https://mmkk-backend.onrender.com/pixel.js" data-api-key="supersecret123"></script>

    Key points:
    - Automatically posts to the SAME origin as pixel.js (Render), not localhost
    - Sends page_view + link click events
    """
    js = r"""(function () {
  var s = document.currentScript;
  function attr(name){ return s && s.getAttribute ? s.getAttribute(name) : null; }
  var apiKey = attr("data-api-key") || "";
  var apiBase = (function(){
    try { return (new URL(s.src)).origin; } catch(e) { return window.location.origin; }
  })();

  function getAnonId(){
    var k="mmkk_anon_id";
    var v=localStorage.getItem(k);
    if(!v){
      v="anon_"+Math.random().toString(16).slice(2)+Date.now().toString(16);
      localStorage.setItem(k,v);
    }
    return v;
  }

  function utm(){
    var p=new URLSearchParams(window.location.search);
    var o={};
    ["source","medium","campaign","content","term"].forEach(function(k){
      var v=p.get("utm_"+k);
      if(v) o[k]=v;
    });
    return o;
  }

  function send(type, meta){
    var body={
      event_type:type,
      anonymous_id:getAnonId(),
      url:window.location.href,
      path:window.location.pathname,
      referrer:document.referrer||null,
      utm:utm(),
      metadata:meta||{}
    };
    try{
      fetch(apiBase+"/public/track",{
        method:"POST",
        headers:Object.assign({"Content-Type":"application/json"}, apiKey?{"X-API-Key":apiKey}:{ }),
        body:JSON.stringify(body),
        keepalive:true
      });
    }catch(e){}
  }

  send("page_view");

  document.addEventListener("click", function(e){
    var a = e.target && e.target.closest ? e.target.closest("a") : null;
    if(!a) return;
    var href = a.getAttribute("href") || "";
    send("click", {href: href, text: (a.innerText||"").slice(0,120)});
  }, true);
})();"""
    return Response(content=js, media_type="application/javascript")


# -----------------------------
# Insights for dashboard
# -----------------------------
@app.get("/insights/anon-visits")
def anon_visits(
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    ws = verify_key_and_workspace(db, x_api_key)

    visits = (
        db.query(AnonymousVisit)
        .filter(AnonymousVisit.workspace_id == ws)
        .order_by(AnonymousVisit.created_at.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id": v.id,
            "anonymous_id": v.anonymous_id,
            "ip": v.ip,
            "url": v.url,
            "referrer": v.referrer,
            "company_guess": v.company_guess,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in visits
    ]


@app.get("/insights/activity-feed")
def activity_feed(
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    ws = verify_key_and_workspace(db, x_api_key)

    events = (
        db.query(Event)
        .filter(Event.workspace_id == ws)
        .order_by(Event.created_at.desc())
        .limit(200)
        .all()
    )
    return {
        "items": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "anonymous_id": e.anonymous_id,
                "email": e.email,
                "url": e.url,
                "referrer": e.referrer,
                "channel": e.channel,
                "utm": e.utm,
                "metadata": e.event_metadata,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
    }


@app.get("/insights/playbook-coverage")
def playbook_coverage(
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    ws = verify_key_and_workspace(db, x_api_key)

    total_accounts = db.query(func.count(Account.id)).filter(Account.workspace_id == ws).scalar() or 0
    accounts_with_tasks = (
        db.query(func.count(func.distinct(Task.account_id)))
        .filter(Task.workspace_id == ws, Task.account_id.isnot(None))
        .scalar()
        or 0
    )
    pct = (accounts_with_tasks / total_accounts * 100.0) if total_accounts else 0.0
    return {"coverage_pct": pct, "accounts_total": total_accounts, "accounts_with_tasks": accounts_with_tasks}


@app.get("/insights/top-accounts")
def top_accounts(
    limit: int = 50,
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    ws = verify_key_and_workspace(db, x_api_key)

    # Simple scoring (no migrations)
    events = (
        db.query(Event)
        .filter(Event.workspace_id == ws)
        .order_by(Event.created_at.desc())
        .limit(5000)
        .all()
    )

    high_intent = {"form_submit", "booking", "purchase", "whatsapp_click", "contact_submit", "call_click"}

    score_by_anon: Dict[str, Dict[str, float]] = {}
    for e in events:
        aid = e.anonymous_id or "unknown"
        d = score_by_anon.setdefault(aid, {"eng": 0.0, "intent": 0.0})
        d["eng"] += 1.0
        if e.event_type in high_intent:
            d["intent"] += 1.0

    # Return accounts list (if you have accounts) + aggregated signals
    accounts = (
        db.query(Account)
        .filter(Account.workspace_id == ws)
        .order_by(desc(Account.intent_score), desc(Account.engagement_score))
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": a.id,
                "name": a.name,
                "domain": a.domain,
                "industry": a.industry,
                "country": a.country,
                "fit_score": a.fit_score,
                "intent_score": a.intent_score,
                "engagement_score": a.engagement_score,
                "intent_tier": a.stage,
            }
            for a in accounts
        ],
        "anon_rollup": score_by_anon,
    }


# -----------------------------
# CSV Export for CRM
# -----------------------------
@app.get("/export/crm.csv")
def export_crm_csv(
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    ws = verify_key_and_workspace(db, x_api_key)

    accounts = db.query(Account).filter(Account.workspace_id == ws).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["account_id", "name", "domain", "industry", "country", "fit_score", "intent_score", "engagement_score", "stage", "created_at"])
    for a in accounts:
        w.writerow([
            a.id, a.name, a.domain, a.industry, a.country,
            a.fit_score, a.intent_score, a.engagement_score, a.stage,
            a.created_at.isoformat() if a.created_at else ""
        ])

    out = buf.getvalue().encode("utf-8")
    return Response(
        content=out,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=crm_export.csv"},
    )
