export type ListingSource = "ebay" | "vinted";

export interface VisionDetail {
  score: number;
  centering: string;
  corners: string;
  surface: string;
  confidence: string;
  caveats: string;
  printed_name?: string;
  printed_set_number?: string;
  ocr_confidence?: string;
  disclaimer: string;
}

export interface PriceDetail {
  price_eur: number;
  price_low_eur: number | null;
  price_high_eur: number | null;
  variation_7d_eur: number | null;
  rarity: string | null;
  series_name: string | null;
  matched_card: string;
  matched_code: string | null;
  confidence: string;
  reason: string;
  source: string;
}

export interface PriceIndexStatus {
  series_known: number;
  series_synced: number;
  series_pending: number;
  cards_in_index: number;
  progress_percent: number;
}

export interface Listing {
  id: number;
  source: ListingSource;
  title: string;
  url: string;
  price: number;
  shipping_price: number;
  currency: string;
  photo_urls: string[];
  seller_username: string | null;
  seller_reliability_score: number | null;
  reference_price: number | null;
  reference_price_source: string | null;
  margin_net: number | null;
  margin_ratio: number | null;
  quality_text_score: number | null;
  condition_tier: string | null;
  price_low_eur: number | null;
  price_high_eur: number | null;
  price_match_confidence: string | null;
  price_detail: PriceDetail | null;
  quality_vision_score: number | null;
  quality_vision_detail: VisionDetail | null;
  deal_score: number | null;
  rarity_tier: string | null;
  is_vintage: boolean;
  is_popular_pokemon: boolean;
  status: string;
  first_seen_at: string;
  last_seen_at: string;
}

export interface AppSettings {
  deal_score_threshold: number;
  margin_weight: number;
  quality_weight: number;
  seller_weight: number;
  check_interval_minutes: number;
}

export type SortField = "deal_score" | "margin_net" | "first_seen_at" | "price";
export type SortOrder = "asc" | "desc";

// En dev local sans variable d'env définie, on suppose le backend sur le
// port 8000 (voir README > lancement local). En production, définir
// NEXT_PUBLIC_API_URL vers l'URL du backend déployé (ex: Render).
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Erreur API ${res.status} sur ${path}`);
  }
  return res.json();
}

export function fetchListings(params: {
  source?: ListingSource;
  sortBy?: SortField;
  order?: SortOrder;
  minScore?: number;
}): Promise<Listing[]> {
  const qs = new URLSearchParams();
  if (params.source) qs.set("source", params.source);
  if (params.sortBy) qs.set("sort_by", params.sortBy);
  if (params.order) qs.set("order", params.order);
  if (params.minScore !== undefined) qs.set("min_score", String(params.minScore));
  return apiFetch<Listing[]>(`/api/listings?${qs.toString()}`);
}

export function fetchSettings(): Promise<AppSettings> {
  return apiFetch<AppSettings>("/api/settings");
}

export function updateSettings(update: Partial<AppSettings>): Promise<AppSettings> {
  return apiFetch<AppSettings>("/api/settings", {
    method: "PUT",
    body: JSON.stringify(update),
  });
}

export function triggerCheckNow(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/api/admin/run-check-now", { method: "POST" });
}

export function fetchPriceIndexStatus(): Promise<PriceIndexStatus> {
  return apiFetch<PriceIndexStatus>("/api/admin/price-index-status");
}

export function triggerPriceSync(batchSize = 12): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(
    `/api/admin/sync-prices?batch_size=${batchSize}`,
    { method: "POST" }
  );
}
