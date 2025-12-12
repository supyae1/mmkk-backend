from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from models import Account, Event

try:
    import openai
except ImportError:  # if library missing, we degrade gracefully
    openai = None


LOOKBACK_DAYS_DEFAULT = 30


def _classify_lead_quality(score: float) -> str:
    if score >= 80:
        return "Very High"
    if score >= 60:
        return "High"
    if score >= 30:
        return "Medium"
    if score > 0:
        return "Low"
    return "Cold"


def _estimate_conversion_probability(score: float) -> float:
    # naive scaling
    if score <= 0:
        return 0.05
    if score >= 100:
        return 0.85
    return round(0.05 + 0.8 * (score / 100.0), 2)


def _estimate_buying_timeline(events: List[Event]) -> str:
    if not events:
        return "Unknown"
    now = datetime.utcnow()
    last = max(e.created_at for e in events)
    days = (now - last).days
    if days <= 3:
        return "0–2 weeks"
    if days <= 14:
        return "2–4 weeks"
    if days <= 30:
        return "1–2 months"
    return "2+ months"


def _aggregate_channels(events: List[Event]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for e in events:
        src = (e.source or "unknown").lower()
        counts[src] = counts.get(src, 0) + 1
    return counts


def generate_ai_insights(db: Session, account_id: str) -> Dict[str, Any]:
    """
    Returns an AI-enriched summary for an account.
    """
    account: Account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        return {"error": "account_not_found"}

    since = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS_DEFAULT)
    events: List[Event] = (
        db.query(Event)
        .filter(Event.account_id == account_id, Event.created_at >= since)
        .order_by(Event.created_at.asc())
        .all()
    )

    total_score = float(account.total_score or 0.0)
    lead_quality = _classify_lead_quality(total_score)
    conversion_probability = _estimate_conversion_probability(total_score)
    buying_timeline = _estimate_buying_timeline(events)
    channel_counts = _aggregate_channels(events)
    best_channel = max(channel_counts, key=channel_counts.get) if channel_counts else "unknown"

    base_summary = {
        "account_name": account.name,
        "industry": account.industry,
        "country": account.country,
        "city": account.city,
        "stage": account.stage or account.buyer_stage,
        "total_score": total_score,
        "intent_score": float(account.intent_score or 0.0),
        "engagement_score": float(account.engagement_score or 0.0),
        "fit_score": float(account.fit_score or 0.0),
        "predictive_score": float(account.predictive_score or 0.0),
        "events_last_30_days": len(events),
        "channels_last_30_days": channel_counts,
    }

    # Fallback text if OpenAI is not configured
    fallback_summary = (
        f"{account.name} shows {lead_quality} buying intent with score {total_score:.1f}. "
        f"They engaged via {', '.join(channel_counts.keys()) or 'no channels yet'} in the last 30 days. "
        f"Estimated conversion probability is {int(conversion_probability*100)}% "
        f"with a likely buying timeline of {buying_timeline}."
    )

    recommended_message = (
        "Reference their recent behavior, highlight 1–2 clear benefits, and propose a short call in the next 7 days."
    )
    red_flags: List[str] = []
    urgency = "Normal"

    if total_score >= 80:
        urgency = "Very High"
    elif total_score >= 60:
        urgency = "High"
    elif total_score <= 10:
        urgency = "Low"

    if len(events) == 0:
        red_flags.append("No recent activity in the last 30 days.")
    elif (datetime.utcnow() - events[-1].created_at).days > 21:
        red_flags.append("Last activity more than 3 weeks ago.")

    if (account.stage or "").lower() in {"closed_lost", "churned"}:
        red_flags.append("Marked as closed-lost / churned in CRM.")

    priority_score = min(100, int(total_score))

    summary_text = fallback_summary

    # If OpenAI is available and API key set, call GPT
    api_key = os.getenv("OPENAI_API_KEY")
    if openai is not None and api_key:
        try:
            openai.api_key = api_key
            prompt = (
                "You are a B2B revenue operations assistant. "
                "Given account metrics and recent activity, write a short (3–5 sentence) summary for sales. "
                "Focus on intent, risk, suggested next step, and which channel to use.\n\n"
                f"DATA: {base_summary}\n\n"
                f"LEAD QUALITY: {lead_quality}\n"
                f"CONVERSION PROBABILITY: {conversion_probability}\n"
                f"BUYING TIMELINE: {buying_timeline}\n"
                f"BEST CHANNEL: {best_channel}\n"
            )
            completion = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You write concise sales intelligence summaries.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=220,
            )
            summary_text = completion.choices[0].message["content"].strip()
        except Exception:
            summary_text = fallback_summary

    return {
        "summary": summary_text,
        "lead_quality": lead_quality,
        "conversion_probability": conversion_probability,
        "buying_timeline": buying_timeline,
        "next_best_action": "Prioritize outreach if urgency is High or Very High; otherwise keep in nurture with 1–2 touches per month.",
        "best_channel": best_channel,
        "recommended_message": recommended_message,
        "red_flags": red_flags,
        "priority_score": priority_score,
        "urgency": urgency,
        "raw": base_summary,
    }
