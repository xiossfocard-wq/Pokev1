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
    // On remonte le detail renvoye par le backend quand il y en a un :
    // sans ca, toute erreur ressemblait a "la recherche a echoue", sans
    // moyen de savoir pourquoi depuis le navigateur.
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? ` — ${body.detail}` : "";
    } catch {
      /* corps non JSON : on garde juste le code HTTP */
    }
    throw new Error(`Erreur API ${res.status} sur ${path}${detail}`);
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

export type SearchJobStatus = "pending" | "running" | "done" | "error";

export interface SearchJob {
  job_id: string;
  query: string;
  status: SearchJobStatus;
  message: string;
  error: string | null;
  result_count: number;
  elapsed_seconds: number;
  listings?: Listing[];
}

// Intervalle entre deux verifications de l'avancement, et duree max avant
// d'abandonner. Mesure sur la prod le 25/08/2026 : 325 s pour "dracaufeu"
// (92 annonces toutes nouvelles a scorer). Le plafond precedent de 6 min
// passait a 35 s pres — on prend une vraie marge, quitte a ce que
// l'utilisateur abandonne de lui-meme avant.
const SEARCH_POLL_INTERVAL_MS = 2000;
const SEARCH_MAX_WAIT_MS = 12 * 60 * 1000;

function startSearch(query: string): Promise<SearchJob> {
  return apiFetch<SearchJob>(
    `/api/listings/search?q=${encodeURIComponent(query)}`,
    { method: "POST" }
  );
}

function fetchSearchJob(jobId: string): Promise<SearchJob> {
  return apiFetch<SearchJob>(`/api/listings/search/${encodeURIComponent(jobId)}`);
}

/**
 * Lance une recherche ciblee et attend son resultat.
 *
 * La recherche ne tient PAS dans une seule requete HTTP (1 a 5 min de
 * travail cote serveur : Vinted + eBay en direct, puis scoring de chaque
 * annonce). Le backend rend donc un identifiant de job tout de suite, et
 * on vient chercher l'avancement toutes les 2 s. C'est ce qui corrige la
 * barre de recherche qui ne rendait jamais rien dans le navigateur.
 */
export async function searchListings(
  query: string,
  onProgress?: (message: string) => void
): Promise<Listing[]> {
  const job = await startSearch(query);
  const deadline = Date.now() + SEARCH_MAX_WAIT_MS;

  let current = job;
  while (Date.now() < deadline) {
    if (current.status === "done") return current.listings ?? [];
    if (current.status === "error") {
      throw new Error(current.error || "La recherche a echoue cote serveur.");
    }
    onProgress?.(current.message);
    await new Promise((r) => setTimeout(r, SEARCH_POLL_INTERVAL_MS));
    current = await fetchSearchJob(job.job_id);
  }

  throw new Error(
    "La recherche prend anormalement longtemps (plus de 12 minutes). " +
      "Réessaie dans un moment."
  );
}
