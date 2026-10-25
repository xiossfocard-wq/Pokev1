"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  fetchListings,
  fetchPriceIndexStatus,
  fetchSettings,
  searchListings,
  triggerCheckNow,
  type Listing,
  type PriceIndexStatus,
  type SortField,
  type SortOrder,
} from "@/lib/api";
import ListingColumn from "@/components/ListingColumn";
import ListingCard from "@/components/ListingCard";
import StatStrip from "@/components/StatStrip";
import FilterChips, { applyFilters, DEFAULT_FILTERS, type Filters } from "@/components/FilterChips";

const REFRESH_INTERVAL_MS = 60_000;
const DEFAULT_DEAL_THRESHOLD = 70;

export default function DashboardPage() {
  const [vinted, setVinted] = useState<Listing[]>([]);
  const [ebay, setEbay] = useState<Listing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<SortField>("deal_score");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [mobileTab, setMobileTab] = useState<"vinted" | "ebay">("vinted");
  const [indexStatus, setIndexStatus] = useState<PriceIndexStatus | null>(null);
  const [dealThreshold, setDealThreshold] = useState(DEFAULT_DEAL_THRESHOLD);
  const [checking, setChecking] = useState(false);

  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<Listing[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchProgress, setSearchProgress] = useState("");

  // Une recherche peut durer 6 minutes et un "Collecter" declenche un
  // rechargement 4 s plus tard : si l'utilisateur quitte la page entre
  // temps, plus rien ne doit toucher a l'etat.
  const mounted = useRef(true);
  const searchAbort = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      searchAbort.current?.abort();
    };
  }, []);

  // `silent` : rafraîchir sans vider l'écran. Le rafraîchissement
  // automatique ne doit pas remplacer les annonces par des squelettes.
  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      setError(null);
      try {
        const [v, e] = await Promise.all([
          fetchListings({ source: "vinted", sortBy, order }),
          fetchListings({ source: "ebay", sortBy, order }),
        ]);
        setVinted(v);
        setEbay(e);
      } catch {
        setError(
          "Impossible de joindre le backend. S'il vient de se réveiller (hébergement gratuit), réessaie dans une minute."
        );
      } finally {
        setLoading(false);
      }
    },
    [sortBy, order]
  );

  const loadMeta = useCallback(() => {
    fetchPriceIndexStatus().then(setIndexStatus).catch(() => {});
    fetchSettings()
      .then((s) => setDealThreshold(s.deal_score_threshold))
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
    loadMeta();
    const interval = setInterval(() => {
      load(true);
      loadMeta();
    }, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [load, loadMeta]);

  async function handleCheckNow() {
    setChecking(true);
    try {
      await triggerCheckNow();
    } finally {
      setTimeout(() => {
        if (!mounted.current) return;
        setChecking(false);
        load(true);
      }, 4000);
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = searchInput.trim();
    if (q.length < 2) return;
    setSearching(true);
    setSearchError(null);
    setSearchQuery(q);
    setSearchResults([]);
    setSearchProgress("Démarrage de la recherche…");
    searchAbort.current?.abort();
    const controller = new AbortController();
    searchAbort.current = controller;
    try {
      const results = await searchListings(q, setSearchProgress, controller.signal);
      if (mounted.current) setSearchResults(results);
    } catch (err) {
      if (!mounted.current || controller.signal.aborted) return;
      const detail = err instanceof Error ? err.message : String(err);
      setSearchError(`La recherche a échoué. [${detail}]`);
    } finally {
      if (mounted.current) {
        setSearching(false);
        setSearchProgress("");
      }
    }
  }

  function clearSearch() {
    setSearchQuery(null);
    setSearchResults([]);
    setSearchInput("");
    setSearchError(null);
  }

  // Une correction saisie sur une carte se répercute tout de suite dans
  // les listes, sans recharger — et une annonce masquée disparaît.
  const handleListingChanged = useCallback((updated: Listing) => {
    const replace = (list: Listing[]) =>
      updated.manual_status === "hidden"
        ? list.filter((l) => l.id !== updated.id)
        : list.map((l) => (l.id === updated.id ? updated : l));
    setVinted(replace);
    setEbay(replace);
    setSearchResults(replace);
  }, []);

  const all = useMemo(() => [...vinted, ...ebay], [vinted, ebay]);
  const vintedShown = useMemo(() => applyFilters(vinted, filters), [vinted, filters]);
  const ebayShown = useMemo(() => applyFilters(ebay, filters), [ebay, filters]);
  // Sans clé eBay configurée, la colonne eBay restait vide et prenait la
  // moitié de l'écran. Elle n'apparaît que si elle a quelque chose à
  // montrer — ou si on l'a demandée explicitement avec le filtre.
  const ebayVide = !loading && ebay.length === 0;
  const showVinted = filters.source !== "ebay";
  const showEbay = filters.source === "ebay" || (filters.source !== "vinted" && !ebayVide);

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 sm:flex-nowrap">
          <Link href="/" className="shrink-0">
            <span className="font-display text-lg leading-none text-parchment-100">Radar</span>
            <span className="ml-1.5 hidden font-mono text-[10px] uppercase tracking-[0.14em] text-ink-400 sm:inline">
              à pépites
            </span>
          </Link>

          {/* Sur téléphone, les boutons écrasaient le champ de recherche à
              quelques pixels : il passe sur sa propre ligne, pleine largeur. */}
          <form onSubmit={handleSearch} className="order-last flex min-w-0 basis-full gap-1.5 sm:order-none sm:basis-auto sm:flex-1">
            <input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Chercher une carte : Luffy, Zoro alt art, OP01-120…"
              aria-label="Chercher une carte One Piece sur Vinted et eBay"
              className="min-w-0 flex-1 rounded-md border border-ink-700 bg-ink-800/80 px-3 py-1.5 text-sm text-parchment-100 placeholder:text-ink-400 focus:border-ember-500 focus:outline-none"
            />
            <button
              type="submit"
              disabled={searching || searchInput.trim().length < 2}
              className="shrink-0 rounded-md border border-ember-500/50 bg-ember-500/10 px-3 py-1.5 text-sm font-medium text-ember-400 transition-colors hover:bg-ember-500/20 disabled:opacity-40"
            >
              {searching ? "…" : "Chercher"}
            </button>
          </form>

          <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:ml-0">
            <button
              onClick={handleCheckNow}
              disabled={checking}
              title="Lancer un cycle de collecte Vinted + eBay maintenant"
              className="hidden rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500 disabled:opacity-50 md:block"
            >
              {checking ? "Collecte…" : "Collecter"}
            </button>
            <Link
              href="/explorer"
              title="Chercher dans le catalogue par thème, budget et tendance"
              className="rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
            >
              Catalogue
            </Link>
            <Link
              href="/settings"
              className="rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
            >
              Réglages
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-16 pt-4">
        {error && (
          <div className="mb-4 rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
            {error}
          </div>
        )}

        {searchQuery ? (
          <section className="mb-8">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-display text-xl text-parchment-100">
                Résultats pour « {searchQuery} »
                <span className="tabular ml-2 font-mono text-xs font-normal text-ink-400">
                  {searchResults.length}
                </span>
              </h2>
              <button
                type="button"
                onClick={clearSearch}
                className="rounded-md border border-ink-700 px-2.5 py-1 text-xs text-ink-400 transition-colors hover:border-ink-600 hover:text-parchment-100"
              >
                Retour au radar
              </button>
            </div>

            {searchError && (
              <div className="mb-3 rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
                {searchError}
              </div>
            )}

            {searching && (
              <div className="rounded-lg border border-dashed border-ink-700 px-4 py-8 text-center">
                <p className="text-sm text-parchment-100">Recherche en direct sur Vinted et eBay</p>
                <p className="mt-1 text-xs text-ink-400">
                  Compte 1 à 6 minutes la première fois. Tu peux laisser la page ouverte.
                </p>
                {searchProgress && (
                  <p className="mt-2 font-mono text-[11px] text-ember-400">{searchProgress}</p>
                )}
              </div>
            )}

            {!searching && !searchError && searchResults.length === 0 && (
              <div className="rounded-lg border border-dashed border-ink-700 px-4 py-8 text-center">
                <p className="text-sm text-parchment-100">Aucune annonce trouvée pour ce terme.</p>
                <p className="mt-1 text-xs text-ink-400">Essaie un nom légèrement différent, ou reviens plus tard.</p>
              </div>
            )}

            <div className="grid gap-2 md:grid-cols-2">
              {searchResults.map((l) => (
                <ListingCard key={`${l.source}-${l.id}`} listing={l} onChanged={handleListingChanged} />
              ))}
            </div>
          </section>
        ) : (
          <>
            <StatStrip listings={all} indexStatus={indexStatus} dealThreshold={dealThreshold} loading={loading} />

            <div className="mt-4 mb-4">
              <FilterChips value={filters} onChange={setFilters} />
            </div>

            {ebayVide && filters.source === "all" && (
              <p className="mb-3 text-[11px] text-ink-400">
                Aucune annonce eBay : la collecte eBay demande une clé d&apos;API (voir le README), ou
                n&apos;a encore rien trouvé. Le radar montre Vinted en pleine largeur.
              </p>
            )}

            <div className={`mb-3 flex gap-1 md:hidden ${showVinted && showEbay ? "" : "hidden"}`}>
              {(["vinted", "ebay"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  aria-pressed={mobileTab === tab}
                  onClick={() => setMobileTab(tab)}
                  className={`flex-1 rounded-md py-1.5 text-xs font-medium capitalize transition-colors ${
                    mobileTab === tab ? "bg-ember-500/20 text-ember-400" : "bg-ink-800 text-ink-400"
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            <div className="flex flex-col gap-6 md:flex-row">
              {showVinted && (
                <div className={mobileTab === "vinted" || !showEbay ? "block min-w-0 flex-1" : "hidden min-w-0 flex-1 md:block"}>
                  <ListingColumn
                    source="vinted"
                    listings={vintedShown}
                    total={vinted.length}
                    loading={loading}
                    sortBy={sortBy}
                    order={order}
                    onSortChange={(f, o) => { setSortBy(f); setOrder(o); }}
                    onListingChanged={handleListingChanged}
                  />
                </div>
              )}
              {showEbay && (
                <div className={mobileTab === "ebay" || !showVinted ? "block min-w-0 flex-1" : "hidden min-w-0 flex-1 md:block"}>
                  <ListingColumn
                    source="ebay"
                    listings={ebayShown}
                    total={ebay.length}
                    loading={loading}
                    sortBy={sortBy}
                    order={order}
                    onSortChange={(f, o) => { setSortBy(f); setOrder(o); }}
                    onListingChanged={handleListingChanged}
                  />
                </div>
              )}
            </div>
          </>
        )}

        <footer className="mt-12 space-y-1 border-t border-ink-800 pt-4 text-center text-[11px] text-ink-400">
          <p>Scores de qualité = estimations automatiques, pas un grading professionnel.</p>
          <p>Prix de référence : OPECards (marché FR, relevé Cardmarket). Vérifie toujours l&apos;annonce et les photos avant d&apos;acheter.</p>
          <p>
            « Payé » = prix + protection acheteur Vinted (0,70 € + 5 %) + port estimé. La marge déduit aussi les frais de
            revente sur Cardmarket, et la cote est ramenée à l&apos;état de la carte.
          </p>
        </footer>
      </main>
    </>
  );
}
