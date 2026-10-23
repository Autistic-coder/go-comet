from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ExtensionTrigger(str, Enum):
    BID_RECEIVED = "bid_received"
    ANY_RANK_CHANGE = "any_rank_change"
    LOWEST_BIDDER_CHANGE = "lowest_bidder_change"


class RfqCreate(BaseModel):
    reference_id: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=3, max_length=120)
    bid_start_at: datetime
    bid_close_at: datetime
    forced_close_at: datetime
    pickup_service_at: datetime
    trigger_window_minutes: int = Field(ge=1, le=240)
    extension_minutes: int = Field(ge=1, le=120)
    extension_trigger: ExtensionTrigger

    @model_validator(mode="after")
    def validate_dates(self) -> "RfqCreate":
        if self.bid_close_at <= self.bid_start_at:
            raise ValueError("Bid close time must be later than bid start time")
        if self.forced_close_at <= self.bid_close_at:
            raise ValueError("Forced close time must be later than bid close time")
        if self.pickup_service_at <= self.bid_start_at:
            raise ValueError("Pickup/service time must be later than bid start time")
        return self


class BidCreate(BaseModel):
    supplier_name: str = Field(min_length=2, max_length=100)
    carrier_name: str = Field(min_length=2, max_length=100)
    freight_charges: float = Field(ge=0)
    origin_charges: float = Field(ge=0)
    destination_charges: float = Field(ge=0)
    transit_time_days: int = Field(ge=1, le=365)
    validity_date: datetime
    submitted_at: datetime | None = None


class EventResponse(BaseModel):
    id: int
    event_type: str
    message: str
    created_at: datetime


class BidResponse(BaseModel):
    id: int
    supplier_name: str
    carrier_name: str
    freight_charges: float
    origin_charges: float
    destination_charges: float
    transit_time_days: int
    validity_date: datetime
    total_price: float
    submitted_at: datetime
    rank: int


class RfqSummary(BaseModel):
    id: int
    reference_id: str
    name: str
    bid_start_at: datetime
    current_close_at: datetime
    forced_close_at: datetime
    status: str
    lowest_bid: float | None
    bid_count: int


class RfqDetail(RfqSummary):
    original_close_at: datetime
    pickup_service_at: datetime
    trigger_window_minutes: int
    extension_minutes: int
    extension_trigger: ExtensionTrigger
    bids: list[BidResponse]
    events: list[EventResponse]

