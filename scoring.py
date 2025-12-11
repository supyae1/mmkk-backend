# scoring.py
from __future__ import annotations

from dataclasses import dataclass

from models import Account, Event


@dataclass
class ScoreTotals:
    intent_score: float
    fit_score: float
    engagement_score: float
    predictive_score: float
    total_score: float


def _event_intent_weight(event: Event) -> float:
    """
    Simple heuristic weights.
    You can refine later based on your 6sense-style logic.
    """
    et = (event.event_type or "").lower()
    if et in {"form_submit", "signup", "demo_request"}:
        return 10.0
    if et in {"pageview", "page_view"}:
        return 1.5
    if et in {"email_click"}:
        return 3.0
    return 1.0


def _event_engagement_weight(event: Event) -> float:
    if event.duration and event.duration > 120:
        return 3.0
    if event.duration and event.duration > 30:
        return 2.0
    return 1.0


def _buyer_stage_from_scores(intent: float, engagement: float, total: float) -> str:
    score = total
    if score >= 80:
        return "buying"
    if score >= 50:
        return "evaluating"
    if score >= 25:
        return "considering"
    if score >= 10:
        return "aware"
    return "unaware"


def score_event(account: Account, event: Event) -> tuple[float, float, ScoreTotals]:
    """
    Given an Account + new Event, compute:
      - event intent & engagement score
      - updated account scores
    """
    base_intent = account.intent_score or 0.0
    base_engagement = account.engagement_score or 0.0
    base_fit = account.fit_score or 0.0
    base_predictive = account.predictive_score or 0.0
    base_total = account.total_score or 0.0

    intent_weight = _event_intent_weight(event)
    engagement_weight = _event_engagement_weight(event)

    event_intent = intent_weight
    event_engagement = engagement_weight

    new_intent = base_intent + event_intent
    new_engagement = base_engagement + event_engagement
    new_fit = base_fit  # you can plug external models later
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
