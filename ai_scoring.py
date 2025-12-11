# ai_scoring.py
from datetime import datetime, timedelta
from typing import List

from sqlalchemy.orm import Session

from models import Account, Event


def _classify_lead_quality(score: int) -> str:
    if score >= 60:
        return "High"
    if score >= 20:
        return "Medium"
    return "Low"


def _estimate_conversion_probability(score: int) -> int:
    if score >= 80:
        return 70
    if score >= 60:
        return 55
    if score >= 40:
        return 40
    if score >= 20:
        return 25
    return 15


def _estimate_buying_timeline(score: int, last_event_at: datetime | None) -> str:
    if not last_event_at:
        return "Unknown / very early"

    days_since = (datetime.utcnow() - last_event_at).days

    if score >= 60 and days_since <= 3:
        return "Very near term (1–2 weeks)"
    if score >= 40 and days_since <= 7:
        return "Near term (2–4 weeks)"
    if score >= 20:
        return "Medium term (1–3 months)"
    return "Long-term nurture (3+ months)"


def _infer_best_channel(events: List[Event]) -> str:
    # Simple heuristic
    sources = [e.source for e in events]
    if any(s in ("email", "mailchimp", "klaviyo") for s in sources):
        return "Email"
    if any(s in ("facebook", "instagram", "tiktok") for s in sources):
        return "Social + retargeting"
    if any(s in ("whatsapp", "line", "telegram", "messaging") for s in sources):
        return "Messaging (WhatsApp/LINE/etc.)"
    if any(s == "website" for s in sources):
        return "Website + retargeting"
    return "Mixed / test channels"


def generate_ai_insights(
    db: Session,
    account: Account,
    events: List[Event],
):
    """
    Rule-based AI-like insights for now.
    You can later plug in a real LLM here.
    """
    score = account.score or 0
    lead_quality = _classify_lead_quality(score)
    conversion_probability = _estimate_conversion_probability(score)

    last_event_at = None
    if events:
        last_event_at = max((e.occurred_at for e in events if e.occurred_at), default=None)

    buying_timeline = _estimate_buying_timeline(score, last_event_at)
    best_channel = _infer_best_channel(events)

    # Priority score can mirror the main score for now
    priority_score = score

    # Urgency: combine score + recency
    if score >= 60 and last_event_at and (datetime.utcnow() - last_event_at).days <= 3:
        urgency = "Very High"
    elif score >= 40:
        urgency = "High"
    elif score >= 20:
        urgency = "Medium"
    else:
        urgency = "Low"

    # Simple recommended message skeleton
    recommended_message = (
        f"Hi {account.name}, we've noticed recent interest in our services. "
        f"We help {account.industry or 'businesses'} in {account.country or 'your region'} "
        f"improve revenue and efficiency. Would you be open to a quick "
        f"10–15 minute chat this week to see if it's a good fit?"
    )

    red_flags: List[str] = []
    if not events:
        red_flags.append("No engagement events recorded yet.")
    elif last_event_at and (datetime.utcnow() - last_event_at).days > 30:
        red_flags.append("No recent activity in the last 30 days.")
    if score < 20:
        red_flags.append("Low engagement score so far.")

    summary = (
        f"Account '{account.name}' in {account.country or 'Unknown country'} "
        f"with current score {score} and stage '{account.stage}'. "
        f"Overall lead quality is {lead_quality} with an estimated conversion "
        f"probability around {conversion_probability}%."
    )

    return {
        "summary": summary,
        "lead_quality": lead_quality,
        "conversion_probability": conversion_probability,
        "buying_timeline": buying_timeline,
        "next_best_action": "Prioritize outreach if urgency is High or Very High. Otherwise keep in nurture.",
        "best_channel": best_channel,
        "recommended_message": recommended_message,
        "red_flags": red_flags,
        "priority_score": priority_score,
        "urgency": urgency,
    }
