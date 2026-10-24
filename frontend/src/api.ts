import type { AuctionDetail, AuctionSummary, SessionUser } from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    const detail = Array.isArray(error.detail)
      ? error.detail.map((item: { msg?: string }) => item.msg ?? "Invalid value").join(". ")
      : error.detail;
    throw new Error(detail ?? "Request failed");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function cookie(name: string) {
  const prefix = `${name}=`;
  return document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix))
    ?.slice(prefix.length);
}

async function mutation<T>(path: string, payload?: Record<string, unknown>): Promise<T> {
  const idempotencyKey = crypto.randomUUID();
  const options: RequestInit = {
    method: "POST",
    headers: {
      "Idempotency-Key": idempotencyKey,
      "X-CSRF-Token": decodeURIComponent(cookie("gocomet_csrf") ?? ""),
    },
    body: payload ? JSON.stringify(payload) : undefined,
  };
  try {
    return await request<T>(path, options);
  } catch (error) {
    if (!(error instanceof TypeError)) throw error;
    return request<T>(path, options);
  }
}

export const api = {
  login: (email: string, password: string) =>
    request<{ user: SessionUser }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  session: () => request<{ user: SessionUser }>("/api/auth/session"),
  logout: () =>
    request<void>("/api/auth/logout", {
      method: "POST",
      headers: { "X-CSRF-Token": decodeURIComponent(cookie("gocomet_csrf") ?? "") },
    }),
  listAuctions: (status = "all") =>
    request<AuctionSummary[]>(`/api/rfqs${status === "all" ? "" : `?status=${status}`}`),
  getAuction: (id: number) => request<AuctionDetail>(`/api/rfqs/${id}`),
  createAuction: (payload: Record<string, unknown>) =>
    mutation<AuctionDetail>("/api/rfqs", payload),
  submitBid: (id: number, payload: Record<string, unknown>) =>
    mutation<AuctionDetail>(`/api/rfqs/${id}/bids`, payload),
};

