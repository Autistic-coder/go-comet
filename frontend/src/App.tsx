import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { AuctionDetail, AuctionStatus, AuctionSummary, ExtensionTrigger } from "./types";

const currency = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const statusLabels: Record<AuctionStatus, string> = {
  scheduled: "Scheduled",
  active: "Live",
  closed: "Closed",
  force_closed: "Force closed",
};

const triggerLabels: Record<ExtensionTrigger, string> = {
  bid_received: "Any bid received",
  any_rank_change: "Any supplier rank change",
  lowest_bidder_change: "Lowest bidder (L1) changes",
};

function fmtDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function countdown(value: string, now: number) {
  const diff = Math.max(0, new Date(value).getTime() - now);
  const hours = Math.floor(diff / 3_600_000);
  const minutes = Math.floor((diff % 3_600_000) / 60_000);
  const seconds = Math.floor((diff % 60_000) / 1000);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function nowLocalInput(offsetMinutes: number) {
  const date = new Date(Date.now() + offsetMinutes * 60_000);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function StatusPill({ status }: { status: AuctionStatus }) {
  return <span className={`status-pill status-${status}`}><i />{statusLabels[status]}</span>;
}

function CreateAuctionModal({ onClose, onCreated }: { onClose: () => void; onCreated: (auction: AuctionDetail) => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const auction = await api.createAuction({
        reference_id: data.get("reference_id"),
        name: data.get("name"),
        bid_start_at: new Date(String(data.get("bid_start_at"))).toISOString(),
        bid_close_at: new Date(String(data.get("bid_close_at"))).toISOString(),
        forced_close_at: new Date(String(data.get("forced_close_at"))).toISOString(),
        pickup_service_at: new Date(String(data.get("pickup_service_at"))).toISOString(),
        trigger_window_minutes: Number(data.get("trigger_window_minutes")),
        extension_minutes: Number(data.get("extension_minutes")),
        extension_trigger: data.get("extension_trigger"),
      });
      onCreated(auction);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create auction");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal" onMouseDown={(event) => event.stopPropagation()} aria-modal="true" role="dialog">
        <header className="modal-header">
          <div><span className="eyebrow">New event</span><h2>Create British auction</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close">×</button>
        </header>
        <form onSubmit={submit} className="form-grid">
          <label><span>RFQ reference</span><input required name="reference_id" placeholder="RFQ-2026-1042" /></label>
          <label><span>Auction name</span><input required name="name" placeholder="Mumbai → Delhi FTL" /></label>
          <label><span>Bid starts</span><input required type="datetime-local" name="bid_start_at" defaultValue={nowLocalInput(-5)} /></label>
          <label><span>Bid closes</span><input required type="datetime-local" name="bid_close_at" defaultValue={nowLocalInput(55)} /></label>
          <label><span>Forced close</span><input required type="datetime-local" name="forced_close_at" defaultValue={nowLocalInput(85)} /></label>
          <label><span>Pickup / service</span><input required type="datetime-local" name="pickup_service_at" defaultValue={nowLocalInput(2880)} /></label>
          <label><span>Trigger window</span><div className="input-suffix"><input required type="number" min="1" name="trigger_window_minutes" defaultValue="10" /><em>min</em></div></label>
          <label><span>Extension duration</span><div className="input-suffix"><input required type="number" min="1" name="extension_minutes" defaultValue="5" /><em>min</em></div></label>
          <label className="wide"><span>Extension trigger</span><select name="extension_trigger" defaultValue="lowest_bidder_change">
            {Object.entries(triggerLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
          {error && <p className="form-error wide">{error}</p>}
          <footer className="form-actions wide"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={saving}>{saving ? "Creating…" : "Create auction"}</button></footer>
        </form>
      </section>
    </div>
  );
}

function BidModal({ auction, onClose, onSubmitted }: { auction: AuctionDetail; onClose: () => void; onSubmitted: (auction: AuctionDetail) => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const result = await api.submitBid(auction.id, {
        supplier_name: data.get("supplier_name"), carrier_name: data.get("carrier_name"),
        freight_charges: Number(data.get("freight_charges")), origin_charges: Number(data.get("origin_charges")),
        destination_charges: Number(data.get("destination_charges")), transit_time_days: Number(data.get("transit_time_days")),
        validity_date: new Date(String(data.get("validity_date"))).toISOString(),
      });
      onSubmitted(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Bid could not be submitted");
    } finally { setSaving(false); }
  }

  return <div className="modal-backdrop" onMouseDown={onClose}><section className="modal compact" onMouseDown={(event) => event.stopPropagation()} aria-modal="true" role="dialog">
    <header className="modal-header"><div><span className="eyebrow">{auction.reference_id}</span><h2>Submit supplier bid</h2></div><button className="icon-button" onClick={onClose} aria-label="Close">×</button></header>
    <form className="form-grid" onSubmit={submit}>
      <label><span>Supplier</span><input required name="supplier_name" placeholder="Northstar Logistics" /></label>
      <label><span>Carrier</span><input required name="carrier_name" placeholder="Northstar Roadways" /></label>
      <label><span>Freight charges</span><input required name="freight_charges" type="number" min="0" step="0.01" /></label>
      <label><span>Origin charges</span><input required name="origin_charges" type="number" min="0" step="0.01" defaultValue="0" /></label>
      <label><span>Destination charges</span><input required name="destination_charges" type="number" min="0" step="0.01" defaultValue="0" /></label>
      <label><span>Transit time</span><div className="input-suffix"><input required name="transit_time_days" type="number" min="1" defaultValue="3" /><em>days</em></div></label>
      <label className="wide"><span>Quote valid until</span><input required type="datetime-local" name="validity_date" defaultValue={nowLocalInput(10_080)} /></label>
      {error && <p className="form-error wide">{error}</p>}
      <footer className="form-actions wide"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={saving}>{saving ? "Submitting…" : "Place bid"}</button></footer>
    </form>
  </section></div>;
}

function AuctionDetails({ auction, now, onBack, onBid }: { auction: AuctionDetail; now: number; onBack: () => void; onBid: () => void }) {
  const progress = Math.min(100, Math.max(0, ((now - new Date(auction.bid_start_at).getTime()) / (new Date(auction.current_close_at).getTime() - new Date(auction.bid_start_at).getTime())) * 100));
  return <main className="content details-view">
    <button className="back-button" onClick={onBack}>← Back to auctions</button>
    <section className="details-hero">
      <div><div className="detail-title-row"><StatusPill status={auction.status} /><span className="rfq-ref">{auction.reference_id}</span></div><h1>{auction.name}</h1><p>Pickup / service · {fmtDate(auction.pickup_service_at)}</p></div>
      <div className="hero-actions"><div className="big-countdown"><span>Time remaining</span><strong>{countdown(auction.current_close_at, now)}</strong></div>{auction.status === "active" && <button className="button primary" onClick={onBid}>+ Submit bid</button>}</div>
    </section>
    <div className="progress-track"><div style={{ width: `${progress}%` }} /><span className="trigger-marker">Trigger window</span></div>
    <section className="stat-row">
      <article><span>Current L1</span><strong>{auction.lowest_bid == null ? "No bids" : currency.format(auction.lowest_bid)}</strong><small>{auction.bid_count} submitted bids</small></article>
      <article><span>Closes at</span><strong>{fmtDate(auction.current_close_at)}</strong><small>Original: {fmtDate(auction.original_close_at)}</small></article>
      <article><span>Forced close</span><strong>{fmtDate(auction.forced_close_at)}</strong><small>Hard stop, no exceptions</small></article>
      <article><span>Extension rule</span><strong>+{auction.extension_minutes} min</strong><small>Last {auction.trigger_window_minutes} min · {triggerLabels[auction.extension_trigger]}</small></article>
    </section>
    <div className="details-grid">
      <section className="panel"><header className="panel-header"><div><span className="eyebrow">Live standings</span><h2>Supplier rankings</h2></div><span className="panel-count">{auction.bids.length} bids</span></header>
        {auction.bids.length === 0 ? <div className="empty-small"><span>↗</span><h3>No bids yet</h3><p>The first qualified quote will take the L1 position.</p></div> : <div className="bid-table-wrap"><table className="bid-table"><thead><tr><th>Rank</th><th>Supplier / carrier</th><th>Price</th><th>Transit</th><th>Validity</th></tr></thead><tbody>{auction.bids.map((bid) => <tr key={bid.id} className={bid.rank === 1 ? "winner" : ""}><td><span className={`rank rank-${bid.rank}`}>L{bid.rank}</span></td><td><strong>{bid.supplier_name}</strong><small>{bid.carrier_name}</small></td><td><strong>{currency.format(bid.total_price)}</strong><small>F {currency.format(bid.freight_charges)} · O {currency.format(bid.origin_charges)} · D {currency.format(bid.destination_charges)}</small></td><td>{bid.transit_time_days} days</td><td>{fmtDate(bid.validity_date)}</td></tr>)}</tbody></table></div>}
      </section>
      <aside className="panel activity"><header className="panel-header"><div><span className="eyebrow">Audit trail</span><h2>Activity</h2></div></header><div className="timeline">{auction.events.map((event) => <article key={event.id}><span className={`timeline-dot ${event.event_type}`} /><div><p>{event.message}</p><time>{fmtDate(event.created_at)}</time></div></article>)}</div></aside>
    </div>
  </main>;
}

export default function App() {
  const [auctions, setAuctions] = useState<AuctionSummary[]>([]);
  const [selected, setSelected] = useState<AuctionDetail | null>(null);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [bidOpen, setBidOpen] = useState(false);
  const [now, setNow] = useState(Date.now());

  const load = useCallback(async () => {
    try { setAuctions(await api.listAuctions(filter)); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "API unavailable"); }
    finally { setLoading(false); }
  }, [filter]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);

  const visible = useMemo(() => auctions.filter((auction) => `${auction.name} ${auction.reference_id}`.toLowerCase().includes(query.toLowerCase())), [auctions, query]);
  const liveCount = auctions.filter((auction) => auction.status === "active").length;
  const totalSavings = auctions.reduce((sum, auction) => sum + (auction.lowest_bid ? Math.max(0, 150000 - auction.lowest_bid) : 0), 0);

  async function openAuction(id: number) { try { setSelected(await api.getAuction(id)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load RFQ"); } }
  function handleUpdated(detail: AuctionDetail) { setSelected(detail); setBidOpen(false); void load(); }

  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">G</span><strong>GoComet</strong></div><p className="brand-caption">Freight intelligence</p><nav aria-label="Main navigation"><button type="button" className="active" aria-current="page"><span>01</span>Auctions</button><button type="button"><span>02</span>RFQs</button><button type="button"><span>03</span>Suppliers</button><button type="button"><span>04</span>Analytics</button></nav><div className="sidebar-bottom"><button type="button"><span>05</span>Settings</button><div className="profile"><div className="avatar">VB</div><div><strong>Vaibhav Bedi</strong><span>Procurement admin</span></div></div></div></aside>
    <div className="main-shell">
      <header className="topbar"><div className="mobile-brand"><span className="brand-mark">G</span><strong>GoComet</strong></div><div className="topbar-title"><span>Workspace <b>/</b> Procurement</span><strong>Live auction desk</strong></div><div className="topbar-actions"><span className="system-state"><i /> Market online</span><button className="button primary" onClick={() => setCreateOpen(true)}>New auction <span aria-hidden="true">↗</span></button></div></header>
      {selected ? <AuctionDetails auction={selected} now={now} onBack={() => setSelected(null)} onBid={() => setBidOpen(true)} /> : <main className="content">
        <section className="page-heading"><div><span className="eyebrow">Freight procurement · live intelligence</span><h1>Better rates,<br/><em>decided in real time.</em></h1><p>Run transparent British auctions, compare qualified carriers, and turn every bid into measurable savings.</p></div><button className="button primary mobile-new" onClick={() => setCreateOpen(true)}>New auction <span aria-hidden="true">↗</span></button></section>
        <section className="metrics"><article className="metric-primary"><div><span>Live auctions</span><strong>{liveCount}</strong><small>competitive events running now</small></div><div className="pulse-orbit"><i /><b /></div></article><article><span>Supplier quotes</span><strong>{auctions.reduce((sum, auction) => sum + auction.bid_count, 0)}</strong><small>offers across active lanes</small></article><article><span>Estimated savings</span><strong>{currency.format(totalSavings)}</strong><small className="positive">↗ created through competition</small></article></section>
        <section className="auction-section"><header className="section-title"><div><span className="eyebrow">Auction portfolio</span><h2>Current events</h2></div><span>{visible.length.toString().padStart(2, "0")} records</span></header><div className="list-controls"><div className="tabs">{["all", "active", "scheduled", "closed", "force_closed"].map((value) => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{value === "all" ? "All auctions" : statusLabels[value as AuctionStatus]}</button>)}</div><div className="search"><span>⌕</span><input aria-label="Search auctions" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search RFQ or lane" /></div></div>
          {error && <div className="error-banner"><span>!</span><div><strong>Could not reach the auction API</strong><p>{error}. Start the FastAPI server on port 8000, then retry.</p></div><button onClick={() => void load()}>Retry</button></div>}
          {loading ? <div className="loading-list">Loading auctions…</div> : visible.length === 0 ? <div className="empty-state"><div className="empty-icon"><span>↗</span></div><span className="eyebrow">Ready for competition</span><h2>No auctions here yet</h2><p>Create a British auction to collect transparent bids, rank suppliers automatically, and prevent last-second sniping.</p><button className="button primary" onClick={() => setCreateOpen(true)}>Create your first auction</button></div> : <div className="auction-list">{visible.map((auction) => <article className="auction-card" key={auction.id} onClick={() => void openAuction(auction.id)}><div className="auction-main"><StatusPill status={auction.status} /><div><span className="rfq-ref">{auction.reference_id}</span><h3>{auction.name}</h3><p>{auction.bid_count} bids · Forced close {fmtDate(auction.forced_close_at)}</p></div></div><div className="auction-stat"><span>Current L1</span><strong>{auction.lowest_bid == null ? "—" : currency.format(auction.lowest_bid)}</strong></div><div className="auction-stat countdown"><span>{auction.status === "active" ? "Time remaining" : "Current close"}</span><strong>{auction.status === "active" ? countdown(auction.current_close_at, now) : fmtDate(auction.current_close_at)}</strong></div><button className="row-arrow" aria-label={`Open ${auction.name}`}>→</button></article>)}</div>}
        </section>
      </main>}
    </div>
    {createOpen && <CreateAuctionModal onClose={() => setCreateOpen(false)} onCreated={(auction) => { setCreateOpen(false); setSelected(auction); void load(); }} />}
    {bidOpen && selected && <BidModal auction={selected} onClose={() => setBidOpen(false)} onSubmitted={handleUpdated} />}
  </div>;
}

