import type { AuctionDetail, AuctionSummary } from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail ?? "Request failed");
  }
  return response.json() as Promise<T>;
}

export const api = {
  listAuctions: (status = "all") => request<AuctionSummary[]>(`/api/rfqs?status=${status}`),
  getAuction: (id: number) => request<AuctionDetail>(`/api/rfqs/${id}`),
  createAuction: (payload: Record<string, unknown>) =>
    request<AuctionDetail>("/api/rfqs", { method: "POST", body: JSON.stringify(payload) }),
  submitBid: (id: number, payload: Record<string, unknown>) =>
    request<AuctionDetail>(`/api/rfqs/${id}/bids`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

