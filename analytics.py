# analytics.py
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Account, Event
from schemas import (
    AttributedChannel,
    AttributionRequest,
    AttributionResponse,
    SegmentationRequest,
    SegmentationResponse,
    Segment,
)


def multi_touch_attribution(
    db: Session,
    workspace_id: str,
    req: AttributionRequest,
) -> AttributionResponse:
    """
    Multi-touch attribution at ACCOUNT level (no session_id stored in DB).

    For each conversion event:
      • First touch: earliest touch (by created_at) for that account
      • Last touch: latest touch before the conversion
      • Linear: revenue split equally across all touches up to that conversion

    Channel is taken from Event.source (preferred) or event_metadata["channel"].
    Revenue:
      • Event.value if present
      • or event_metadata["revenue"] if present
    Conversion:
      • req.is_conversion flag in metadata
      • or value > 0
      • or event_type in a small conversion list
    """
    cutoff = datetime.utcnow() - timedelta(days=req.lookback_days)

    q = (
        db.query(Event)
        .filter(Event.workspace_id == workspace_id)
        .filter(Event.created_at >= cutoff)
    )

    if req.account_id:
        q = q.filter(Event.account_id == req.account_id)

    events: List[Event] = q.order_by(Event.account_id, Event.created_at).all()

    # Group events by account_id
    events_by_account: Dict[str, List[Event]] = defaultdict(list)
    for e in events:
        events_by_account[e.account_id].append(e)

    channel_stats: Dict[str, AttributedChannel] = {}

    def get_channel_name(ev: Event) -> str:
        md = ev.event_metadata or {}
        ch = ev.source or md.get("channel")
        return ch or "unknown"

    def get_revenue(ev: Event) -> float:
        md = ev.event_metadata or {}
        if ev.value is not None:
            return float(ev.value)
        if md.get("revenue") is not None:
            try:
                return float(md["revenue"])
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def is_conversion(ev: Event) -> bool:
        md = ev.event_metadata or {}
        if md.get("is_conversion"):
            return True
        if get_revenue(ev) > 0:
            return True
        return ev.event_type in {
            "booking",
            "purchase",
            "deal_closed",
            "opportunity_won",
            "form_submit",
        }

    for account_id, acc_events in events_by_account.items():
        # sorted by created_at from query
        touches = [e for e in acc_events if get_channel_name(e) != "unknown"]

        if not touches:
            continue

        for conv in [e for e in acc_events if is_conversion(e)]:
            revenue = get_revenue(conv)
            if revenue <= 0:
                continue

            # Path up to conversion
            path = [e for e in touches if e.created_at <= conv.created_at]
            if not path:
                continue

            first_touch = path[0]
            last_touch = path[-1]

            def stat_for(channel_name: str) -> AttributedChannel:
                if channel_name not in channel_stats:
                    channel_stats[channel_name] = AttributedChannel(channel=channel_name)
                return channel_stats[channel_name]

            # First-touch revenue
            ft = stat_for(get_channel_name(first_touch))
            ft.first_touch_revenue += revenue

            # Last-touch revenue
            lt = stat_for(get_channel_name(last_touch))
            lt.last_touch_revenue += revenue
            lt.conversions += 1

            # Linear attribution
            share = revenue / len(path)
            for e in path:
                lc = stat_for(get_channel_name(e))
                lc.linear_revenue += share

    return AttributionResponse(channels=list(channel_stats.values()))


def segment_accounts(
    db: Session,
    workspace_id: str,
    req: SegmentationRequest,
) -> SegmentationResponse:
    """
    Segment accounts into:
      • Active_high_intent: many visits + recently active
      • Low_intent: some activity, not hot
      • Dormant: no activity or very old

    Uses:
      - Account.last_event_at
      - Event counts per account
      - Optional filters from SegmentFilter
    """
    filters = req.filters
    now = datetime.utcnow()

    # Base accounts query
    acc_q = db.query(Account).filter(Account.workspace_id == workspace_id)

    if filters.industries:
        acc_q = acc_q.filter(Account.industry.in_(filters.industries))
    if filters.stages:
        acc_q = acc_q.filter(Account.stage.in_(filters.stages))

    accounts: List[Account] = acc_q.all()

    # Event counts per account for this workspace
    ev_counts = dict(
        db.query(Event.account_id, func.count(Event.id))
        .filter(Event.workspace_id == workspace_id)
        .group_by(Event.account_id)
        .all()
    )

    active_high_intent: List[str] = []
    low_intent: List[str] = []
    dormant: List[str] = []

    for acc in accounts:
        acc_id = acc.id
        total_visits = int(ev_counts.get(acc_id, 0))
        last_seen = acc.last_event_at

        # Filter: min_visits
        if filters.min_visits is not None and total_visits < filters.min_visits:
            continue

        # Filter: max_inactive_days
        if filters.max_inactive_days is not None and last_seen is not None:
            inactive_days = (now - last_seen).days
            if inactive_days > filters.max_inactive_days:
                continue

        # Basic buckets
        if total_visits >= 5 and last_seen and (now - last_seen).days <= 7:
            active_high_intent.append(acc_id)
        elif not last_seen or (now - last_seen).days > 30:
            dormant.append(acc_id)
        else:
            low_intent.append(acc_id)

    segments: List[Segment] = []
    if active_high_intent:
        segments.append(
            Segment(segment_name="Active_high_intent", account_ids=active_high_intent)
        )
    if low_intent:
        segments.append(Segment(segment_name="Low_intent", account_ids=low_intent))
    if dormant:
        segments.append(Segment(segment_name="Dormant", account_ids=dormant))

    return SegmentationResponse(segments=segments)
