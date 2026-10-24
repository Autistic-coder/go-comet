from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Sequence

MONEY_QUANTUM = Decimal("0.01")


def money(value: object) -> Decimal:
    """Convert database/API money without ever routing through binary floating point."""
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def total_price(*charges: Decimal) -> Decimal:
    return sum((money(value) for value in charges), Decimal("0.00")).quantize(MONEY_QUANTUM)


def status_for(rfq: Mapping[str, object], now: datetime, parse_timestamp) -> str:
    lifecycle = str(rfq["lifecycle_state"]) if "lifecycle_state" in rfq.keys() else "published"
    if lifecycle in {"paused", "cancelled", "awarded"}:
        return lifecycle
    forced_close = parse_timestamp(str(rfq["forced_close_at"]))
    current_close = parse_timestamp(str(rfq["current_close_at"]))
    if now >= forced_close and current_close >= forced_close:
        return "force_closed"
    if now >= current_close:
        return "closed"
    if now < parse_timestamp(str(rfq["bid_start_at"])):
        return "scheduled"
    return "active"


def extension_close(
    *, submitted_at: datetime, current_close: datetime, forced_close: datetime,
    window_minutes: int, extension_minutes: int, trigger: str,
    previous_order: Sequence[object], current_order: Sequence[object],
) -> datetime | None:
    in_window = submitted_at >= current_close - timedelta(minutes=window_minutes)
    previous_l1 = previous_order[0] if previous_order else None
    current_l1 = current_order[0] if current_order else None
    qualifies = (
        trigger == "bid_received"
        or (trigger == "any_rank_change" and previous_order != current_order)
        or (trigger == "lowest_bidder_change" and previous_l1 != current_l1)
    )
    proposed = min(current_close + timedelta(minutes=extension_minutes), forced_close)
    return proposed if in_window and qualifies and proposed > current_close else None
