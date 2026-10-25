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
  price_eur: number | null;
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
  // Combien de cartes portaient ce nom, et l'écart de prix entre elles.
  // Sert à montrer honnêtement à quel point le prix retenu est solide.
  candidates_count?: number;
  price_spread_eur?: number;
  candidates_min_eur?: number | null;
  candidates_max_eur?: number | null;
  uncertain?: boolean;
  // Alerte explicite (ex : le titre annonce une carte « V » mais la carte
  // trouvée dans l'index est la carte de base).
  warning?: string | null;
}

export interface PriceIndexStatus {
  cards_in_index: number;
  cards_priced: number;
  prices_updated_at: string | null;
  cards_unpriced: number;
  progress_percent: number;
  // Anciens noms, conservés le temps que les appelants migrent. Ils ne
  // décrivent plus une synchronisation de séries — elle n'existe plus —
  // mais le même décompte exprimé en cartes.
  series_known: number;
  series_synced: number;
  series_pending: number;
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
  is_popular_character: boolean;
  status: string;
  first_seen_at: string;
  last_seen_at: string;
  /** Corrections que tu as saisies toi-même sur cette annonce. */
  manual_status: string | null;
  manual_reference_price: number | null;
  manual_reviewed_at: string | null;
}

export interface AppSettings {
  deal_score_threshold: number;
  margin_weight: number;
  quality_weight: number;
  seller_weight: number;
  check_interval_minutes: number;
  /** Les annonces à ce prix ou en dessous sont masquées. */
  min_listing_price: number;
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

/**
 * Correction manuelle d'une annonce.
 * - "wrong_card" : la carte identifiée n'est pas la bonne → le prix est
 *   effacé et plus rien n'est retenté automatiquement.
 * - "set_price"  : tu donnes toi-même le prix du marché.
 * - "hide"       : masquer cette annonce.
 * - "reset"      : oublier ta correction, revenir à l'automatique.
 */
export type CorrectionAction = "wrong_card" | "set_price" | "hide" | "reset";

export function correctListing(
  listingId: number,
  action: CorrectionAction,
  price?: number
): Promise<Listing> {
  return apiFetch<Listing>(`/api/listings/${listingId}/correction`, {
    method: "POST",
    body: JSON.stringify({ action, price: price ?? null }),
  });
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
// d'abandonner. Mesure sur la prod le 25/08/2026 : 325 s pour une
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
  onProgress?: (message: string) => void,
  signal?: AbortSignal
): Promise<Listing[]> {
  const job = await startSearch(query);
  const deadline = Date.now() + SEARCH_MAX_WAIT_MS;

  let current = job;
  while (Date.now() < deadline) {
    // La page a ete quittee : on arrete de sonder, sans erreur bruyante.
    if (signal?.aborted) throw new DOMException("Recherche annulée", "AbortError");
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

// ---------------------------------------------------------------------------
// Catalogue de cartes (nouvelle direction du 10/10/2026)
//
// Ces appels partent du CATALOGUE (quelles cartes existent, a quel prix,
// dans quel theme, lesquelles montent), la ou fetchListings part des
// ANNONCES Vinted/eBay. Les deux cohabitent : on repere ici une carte qui
// monte, on la traque ensuite dans les annonces.
// ---------------------------------------------------------------------------

export type TrendDirection = "hausse" | "baisse" | "stable" | "inconnu";
export type TrendIntensity = "forte" | "moderee" | "faible" | "inconnu";

export interface Trend7d {
  variation_eur: number | null;
  variation_pct: number | null;
  direction: TrendDirection;
  intensite: TrendIntensity;
  label: string;
}

export interface CatalogCard {
  id: number;
  card_code: string | null;
  name_slug: string;
  display_name: string;
  series_name: string | null;
  rarity: string | null;
  price_eur: number | null;
  price_low_eur: number | null;
  price_high_eur: number | null;
  // Rappel porte depuis le backend : la fourchette vient de la volatilite
  // recente, ce ne sont PAS des extremes de ventes conclues.
  price_range_is_derived: boolean;
  themes: string[];
  image_url: string | null;
  image_source: string | null;
  // Langue du NOM affiché, et d'où il vient. « en » signale une carte que
  // la liste officielle française ne contient pas — le jeu français
  // commence à OP09 — et non une carte absente du marché français.
  language: "fr" | "en" | null;
  language_note: string | null;
  trend_7d: Trend7d;
  // Annonces en vente pour cette carte, en ce moment. Portés jusqu'à la
  // grille pour répondre d'un coup d'œil à « laquelle de ces cartes a
  // quelque chose à prendre ? », au lieu d'ouvrir chaque fiche l'une après
  // l'autre. Comptés avec EXACTEMENT les mêmes exclusions que la fiche.
  listings_count: number;
  best_deal_score: number | null;
  updated_at: string | null;
}

export interface CardTheme {
  slug: string;
  label: string;
  description: string;
  famille: "sujet" | "type";
  card_count: number;
  price_min_eur: number | null;
  price_max_eur: number | null;
  price_avg_eur: number | null;
}

export interface CardFilterValues {
  rarities: string[];
  series: string[];
  price_min_eur: number | null;
  price_max_eur: number | null;
  themes: { slug: string; label: string; famille: "sujet" | "type" }[];
  total_cards: number;
  // Combien de fiches dans chaque langue. Sans ce compte, « 3 868 cartes »
  // laisserait croire à un catalogue français complet alors qu'une partie
  // porte encore son nom anglais.
  languages: { code: string | null; label: string; count: number }[];
}

export interface CardSearchResult {
  total: number;
  limite: number;
  decalage: number;
  cartes: CatalogCard[];
}

export type CardSortField = "prix" | "nom" | "variation" | "maj";

export interface CardSearchParams {
  q?: string;
  theme?: string;
  rarity?: string;
  series?: string;
  priceMin?: number;
  priceMax?: number;
  trend?: "hausse" | "baisse" | "toutes";
  withImage?: boolean;
  withListings?: boolean;
  language?: "fr" | "en" | "inconnue";
  sortBy?: CardSortField;
  order?: SortOrder;
  limit?: number;
  offset?: number;
}

export function searchCards(params: CardSearchParams): Promise<CardSearchResult> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.theme) qs.set("theme", params.theme);
  if (params.rarity) qs.set("rarity", params.rarity);
  if (params.series) qs.set("series", params.series);
  if (params.priceMin !== undefined) qs.set("price_min", String(params.priceMin));
  if (params.priceMax !== undefined) qs.set("price_max", String(params.priceMax));
  if (params.trend) qs.set("trend", params.trend);
  if (params.withImage !== undefined) qs.set("with_image", String(params.withImage));
  if (params.withListings !== undefined)
    qs.set("with_listings", String(params.withListings));
  if (params.language) qs.set("language", params.language);
  if (params.sortBy) qs.set("sort_by", params.sortBy);
  if (params.order) qs.set("order", params.order);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  return apiFetch<CardSearchResult>(`/api/cards?${qs.toString()}`);
}

export function fetchCardThemes(): Promise<{ themes: CardTheme[] }> {
  return apiFetch<{ themes: CardTheme[] }>("/api/cards/themes");
}

export function fetchCardFilters(): Promise<CardFilterValues> {
  return apiFetch<CardFilterValues>("/api/cards/filters");
}

export function fetchTrendingCards(params: {
  direction?: "hausse" | "baisse";
  priceMin?: number;
  priceMax?: number;
  theme?: string;
  limit?: number;
}): Promise<{
  direction: string;
  count: number;
  cartes: CatalogCard[];
  source_note: string;
}> {
  const qs = new URLSearchParams();
  if (params.direction) qs.set("direction", params.direction);
  if (params.priceMin !== undefined) qs.set("price_min", String(params.priceMin));
  if (params.priceMax !== undefined) qs.set("price_max", String(params.priceMax));
  if (params.theme) qs.set("theme", params.theme);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  return apiFetch(`/api/cards/trending?${qs.toString()}`);
}

export interface CardTrendHistory {
  points: number;
  jours_couverts: number;
  variation_pct: number | null;
  pente_eur_par_jour: number | null;
  r2: number | null;
  fiabilite: "insuffisant" | "faible" | "moyenne" | "bonne";
  avertissement: string;
}

export interface CardProjection {
  horizon_jours: number;
  // null tant que l'historique est insuffisant. C'est voulu : un prix
  // projete sur deux releves serait un chiffre invente.
  prix_projete_eur: number | null;
  fiabilite: string;
  avertissement: string;
}

export interface CatalogCardDetail extends CatalogCard {
  themes_detail: {
    slug: string;
    label: string;
    description: string;
    famille: string;
  }[];
  history: { captured_on: string; price_eur: number }[];
  trend_history: CardTrendHistory;
  projection: CardProjection;
}

export function fetchCardDetail(
  cardId: number,
  horizonJours = 30
): Promise<CatalogCardDetail> {
  return apiFetch<CatalogCardDetail>(
    `/api/cards/${cardId}?horizon_jours=${horizonJours}`
  );
}

export function triggerCardImageEnrichment(
  limit = 40
): Promise<{ examined: number; found: number; not_found: number }> {
  return apiFetch(`/api/admin/enrich-card-images?limit=${limit}`, { method: "POST" });
}

export function triggerThemeRecompute(): Promise<{ examined: number; updated: number }> {
  return apiFetch("/api/admin/recompute-card-themes", { method: "POST" });
}

export function triggerPriceSnapshot(): Promise<{
  captured_on: string;
  examined: number;
  created: number;
  updated: number;
}> {
  return apiFetch("/api/admin/snapshot-card-prices", { method: "POST" });
}

// ---------------------------------------------------------------------------
// Le pont entre les deux moitiés : les annonces en vente pour une carte du
// catalogue. On repère une carte, on voit s'il y a quelque chose à prendre
// maintenant, sans retourner fouiller le dashboard.
// ---------------------------------------------------------------------------

export interface CardListing {
  id: number;
  source: ListingSource | null;
  title: string;
  url: string;
  price_eur: number;
  shipping_eur: number | null;
  total_eur: number;
  deal_score: number | null;
  margin_net_eur: number | null;
  margin_ratio: number | null;
  condition_tier: string | null;
  quality_text_score: number | null;
  quality_vision_score: number | null;
  seller_username: string | null;
  seller_reliability_score: number | null;
  // Photos du VENDEUR : l'exemplaire réellement en vente, avec son centrage,
  // ses bords et son état. C'est ce qu'on regarde avant d'acheter.
  photo_urls: string[];
  price_match_confidence: string | null;
  first_seen_at: string | null;
}

export interface CardListingsResult {
  card_id: number;
  display_name: string;
  reference_price_eur: number | null;
  count: number;
  listings: CardListing[];
}

export function fetchCardListings(
  cardId: number,
  limit = 20
): Promise<CardListingsResult> {
  return apiFetch<CardListingsResult>(`/api/cards/${cardId}/listings?limit=${limit}`);
}
