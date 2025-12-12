from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Set

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


def _window_start(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


def multi_touch_attribution(
    db: Session,
    workspace_id: str,
    payload: AttributionRequest,
) -> AttributionResponse:
    """
    Basic first-touch / last-touch / linear multi-touch attribution by channel.
    Uses Event.value as "revenue".
    """
    since = _window_start(payload.lookback_days)

    q = db.query(Event).filter(
        Event.workspace_id == workspace_id,
        Event.created_at >= since,
    )
    if payload.account_id:
        q = q.filter(Event.account_id == payload.account_id)

    events: List[Event] = q.order_by(Event.created_at.asc()).all()
    if not events:
        return AttributionResponse(account_id=payload.account_id, breakdown=[])

    def channel_for(ev: Event) -> str:
        if ev.channel:
            return ev.channel
        meta = ev.event_metadata or {}
        return (
            meta.get("channel")
            or meta.get("utm_source")
            or meta.get("utm_medium")
            or "unknown"
        )

    by_account: Dict[str, List[Event]] = defaultdict(list)
    for ev in events:
        key = ev.account_id or "_anon"
        by_account[key].append(ev)

    channel_stats: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"first_touch": 0.0, "last_touch": 0.0, "linear": 0.0}
    )

    for _, evts in by_account.items():
        if not evts:
            continue

        first = evts[0]
        last = evts[-1]
        def _val(e):
            meta = e.event_metadata or {}
            try:
                return float(meta.get("value") or meta.get("revenue") or 0.0)
            except Exception:
                return 0.0
        total_value = sum(_val(e) for e in evts)
        unique_channels: Set[str] = {channel_for(e) for e in evts}

        ft_ch = channel_for(first)
        lt_ch = channel_for(last)

        channel_stats[ft_ch]["first_touch"] += _val(first)
        channel_stats[lt_ch]["last_touch"] += _val(last)

        if unique_channels and total_value:
            share = total_value / float(len(unique_channels))
            for ch in unique_channels:
                channel_stats[ch]["linear"] += share

    breakdown: List[AttributedChannel] = []
    for ch, vals in channel_stats.items():
        breakdown.append(
            AttributedChannel(
                channel=ch,
                first_touch=round(vals["first_touch"], 2),
                last_touch=round(vals["last_touch"], 2),
                linear=round(vals["linear"], 2),
            )
        )

    breakdown.sort(key=lambda x: x.linear, reverse=True)
    return AttributionResponse(account_id=payload.account_id, breakdown=breakdown)


def segment_accounts(
    db: Session,
    workspace_id: str,
    payload: SegmentationRequest,
) -> SegmentationResponse:
    """
    Simple segmentation:
      - Active_high_intent: total_score >= 70 and last activity in last 30 days
      - Low_intent: total_score < 20
      - Dormant: everyone else
    Payload.filters is reserved for future advanced filters.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(days=30)

    accounts: List[Account] = (
        db.query(Account).filter(Account.workspace_id == workspace_id).all()
    )

    active_high_intent: List[str] = []
    low_intent: List[str] = []
    dormant: List[str] = []

    for acc in accounts:
        last = acc.last_activity_at or acc.updated_at or acc.created_at
        score = float(acc.total_score or 0.0)

        if score >= 70 and last >= cutoff:
            active_high_intent.append(acc.id)
        elif score < 20:
            low_intent.append(acc.id)
        else:
            dormant.append(acc.id)

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
