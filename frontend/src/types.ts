export type AuctionStatus = "scheduled" | "active" | "closed" | "force_closed";
export type ExtensionTrigger = "bid_received" | "any_rank_change" | "lowest_bidder_change";

export interface AuctionSummary {
  id: number;
  reference_id: string;
  name: string;
  bid_start_at: string;
  current_close_at: string;
  forced_close_at: string;
  status: AuctionStatus;
  lowest_bid: number | null;
  bid_count: number;
}

export interface Bid {
  id: number;
  supplier_name: string;
  carrier_name: string;
  freight_charges: number;
  origin_charges: number;
  destination_charges: number;
  transit_time_days: number;
  validity_date: string;
  total_price: number;
  submitted_at: string;
  rank: number;
}

export interface AuctionEvent {
  id: number;
  event_type: string;
  message: string;
  created_at: string;
}

export interface AuctionDetail extends AuctionSummary {
  original_close_at: string;
  pickup_service_at: string;
  trigger_window_minutes: number;
  extension_minutes: number;
  extension_trigger: ExtensionTrigger;
  bids: Bid[];
  events: AuctionEvent[];
}

