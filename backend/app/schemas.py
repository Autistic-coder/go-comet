from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExtensionTrigger(str, Enum):
    BID_RECEIVED = "bid_received"
    ANY_RANK_CHANGE = "any_rank_change"
    LOWEST_BIDDER_CHANGE = "lowest_bidder_change"


class AuctionStatus(str, Enum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    CLOSED = "closed"
    FORCE_CLOSED = "force_closed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    AWARDED = "awarded"


class AuctionAction(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    AWARD = "award"


class AuctionTransition(StrictModel):
    action: AuctionAction
    reason: str = Field(min_length=3, max_length=500)
    bid_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def award_requires_bid(self) -> "AuctionTransition":
        if self.action == AuctionAction.AWARD and self.bid_id is None:
            raise ValueError("Awarding an auction requires a bid_id")
        if self.action != AuctionAction.AWARD and self.bid_id is not None:
            raise ValueError("bid_id is only valid for an award action")
        return self


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RfqCreate(StrictModel):
    reference_id: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    name: str = Field(min_length=3, max_length=120)
    bid_start_at: datetime
    bid_close_at: datetime
    forced_close_at: datetime
    pickup_service_at: datetime
    trigger_window_minutes: int = Field(ge=1, le=240)
    extension_minutes: int = Field(ge=1, le=120)
    extension_trigger: ExtensionTrigger

    @field_validator("reference_id")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_dates(self) -> "RfqCreate":
        dates = (
            self.bid_start_at,
            self.bid_close_at,
            self.forced_close_at,
            self.pickup_service_at,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in dates):
            raise ValueError("All auction timestamps must include a timezone")
        if self.bid_close_at <= self.bid_start_at:
            raise ValueError("Bid close time must be later than bid start time")
        if self.forced_close_at <= self.bid_close_at:
            raise ValueError("Forced close time must be later than bid close time")
        if self.pickup_service_at <= self.bid_start_at:
            raise ValueError("Pickup/service time must be later than bid start time")
        return self


class BidCreate(StrictModel):
    freight_charges: Decimal = Field(ge=0, le=100_000_000, decimal_places=2)
    origin_charges: Decimal = Field(ge=0, le=100_000_000, decimal_places=2)
    destination_charges: Decimal = Field(ge=0, le=100_000_000, decimal_places=2)
    transit_time_days: int = Field(ge=1, le=365)
    validity_date: datetime

    @field_validator("validity_date")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Quote validity must include a timezone")
        return value


class EventResponse(BaseModel):
    id: int
    event_type: str
    message: str
    created_at: datetime


class BidResponse(BaseModel):
    id: int
    supplier_name: str
    carrier_name: str
    freight_charges: Decimal
    origin_charges: Decimal
    destination_charges: Decimal
    transit_time_days: int
    validity_date: datetime
    total_price: Decimal
    submitted_at: datetime
    rank: int
    is_own: bool


class RfqSummary(BaseModel):
    id: int
    reference_id: str
    name: str
    bid_start_at: datetime
    current_close_at: datetime
    forced_close_at: datetime
    status: str
    lowest_bid: Decimal | None
    bid_count: int
    lifecycle_state: str
    version: int


class RfqDetail(RfqSummary):
    original_close_at: datetime
    pickup_service_at: datetime
    trigger_window_minutes: int
    extension_minutes: int
    extension_trigger: ExtensionTrigger
    bids: list[BidResponse]
    events: list[EventResponse]

