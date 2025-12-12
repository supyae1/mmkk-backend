from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from models import Account, Event


@dataclass
class ScoreTotals:
    intent_score: float
    fit_score: float
    engagement_score: float
    predictive_score: float
    total_score: float


def _event_intent_weight(event: Event) -> float:
    et = (event.event_type or "").lower()
    if et in {"signup", "demo_request", "booking_completed"}:
        return 10.0
    if et in {"pricing_view", "pageview_pricing"}:
        return 5.0
    if et in {"webinar_attended", "content_download"}:
        return 3.0
    if et in {"pageview"}:
        return 1.0
    return 2.0


def _event_engagement_weight(event: Event) -> float:
    src = (event.source or "").lower()
    if src in {"paid_search", "paid_social"}:
        return 4.0
    if src in {"email"}:
        return 3.0
    if src in {"organic", "direct"}:
        return 1.5
    return 1.0


def score_event(
    account: Optional[Account],
    event: Event,
) -> Tuple[float, float, ScoreTotals]:
    """
    Simple scoring model combining:
    - event intent weight
    - event engagement weight
    - event value (revenue) if present
    """
    base_intent = float(account.intent_score) if account else 0.0
    base_engagement = float(account.engagement_score) if account else 0.0
    base_fit = float(account.fit_score) if account else 0.0
    base_predictive = float(account.predictive_score) if account else 0.0

    w_intent = _event_intent_weight(event)
    w_engagement = _event_engagement_weight(event)
    revenue = float(event.value or 0.0)

    event_intent = w_intent + 0.1 * revenue
    event_engagement = w_engagement + 0.05 * revenue

    new_intent = base_intent + event_intent
    new_engagement = base_engagement + event_engagement
    new_fit = base_fit  # placeholder for future ML fit model
    new_predictive = base_predictive + 0.5 * (event_intent + event_engagement)
    new_total = new_intent + new_engagement + new_fit + new_predictive

    totals = ScoreTotals(
        intent_score=new_intent,
        fit_score=new_fit,
        engagement_score=new_engagement,
        predictive_score=new_predictive,
        total_score=new_total,
    )

    return event_intent, event_engagement, totals
