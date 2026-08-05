"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  fetchListings,
  triggerCheckNow,
  fetchPriceIndexStatus,
  triggerPriceSync,
  searchListings,
  type Listing,
  type PriceIndexStatus,
  type SortField,
  type SortOrder,
} from "@/lib/api";
import ListingColumn from "@/components/ListingColumn";
import ListingCard from "@/components/ListingCard";

export default function DashboardPage() {
  const [vinted, setVinted] = useState<Listing[]>([]);
  const [ebay, setEbay] = useState<Listing[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<SortField>("deal_score");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [minScore, setMinScore] = useState<number | undefined>(undefined);
  const [mobileTab, setMobileTab] = useState<"vinted" | "ebay">("vinted");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [indexStatus, setIndexStatus] = useState<PriceIndexStatus | null>(null);
  const [syncing, setSyncing] = useState(false);

  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<Listing[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [v, e] = await Promise.all([
        fetchListings({ source: "vinted", sortBy, order, minScore }),
        fetchListings({ source: "ebay", sortBy, order, minScore }),
      ]);
      setVinted(v);
      setEbay(e);
    } catch (err) {
      setError(
        "Impossible de joindre le backend. Vérifie qu'il tourne et que " +
          "NEXT_PUBLIC_API_URL pointe dessus (voir README)."
      );
    } finally {
      setLoading(false);
    }
  }, [sortBy, order, minScore]);

  const loadIndexStatus = useCallback(() => {
    fetchPriceIndexStatus().then(setIndexStatus).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    loadIndexStatus();
    const interval = setInterval(() => {
      load();
      loadIndexStatus();
    }, 60_000);
    return () => clearInterval(interval);
  }, [load, loadIndexStatus]);

  async function handleSyncPrices() {
    setSyncing(true);
    try {
      await triggerPriceSync(12);
    } finally {
      setTimeout(() => {
        setSyncing(false);
        loadIndexStatus();
      }, 5000);
    }
  }

  async function handleCheckNow() {
    setChecking(true);
    try {
      await triggerCheckNow();
    } finally {
      setTimeout(() => {
        setChecking(false);
        load();
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
    try {
      const results = await searchListings(q);
      setSearchResults(results);
    } catch (err) {
      setSearchError(
        "La recherche a échoué — le backend est peut-être en train de se réveiller " +
          "(hébergement gratuit), réessaie dans quelques secondes."
      );
    } finally {
      setSearching(false);
    }
  }

  function clearSearch() {
    setSearchQuery(null);
    setSearchResults([]);
    setSearchInput("");
    setSearchError(null);
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl text-parchment-100">
            Le Pokéradar à Pépites
          </h1>
          <p className="text-xs text-ink-600">
            Vinted &amp; eBay passés au radar · comparés à Cardmarket &amp; ZebraDex
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="number"
            placeholder="Score min."
            value={minScore ?? ""}
            onChange={(e) => setMinScore(e.target.value ? Number(e.target.value) : undefined)}
            className="w-24 rounded-sm border border-ink-700 bg-ink-800 px-2 py-1.5 font-mono text-xs text-parchment-100 placeholder:text-ink-600 focus:border-ember-500 focus:outline-none"
          />
          <button
            onClick={handleCheckNow}
            disabled={checking}
            className="rounded-sm border border-ink-700 bg-ink-800 px-3 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500 disabled:opacity-50"
          >
            {checking ? "Vérification…" : "Vérifier maintenant"}
          </button>
          <Link
            href="/settings"
            className="rounded-sm border border-ink-700 bg-ink-800 px-3 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
          >
            Réglages
          </Link>
        </div>
      </header>

      {error && (
        <div className="mb-4 rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
          {error}
        </div>
      )}

      <form onSubmit={handleSearch} className="mb-4 flex gap-2">
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Chercher un Pokémon ou une carte précise (ex: Pikachu, Dracaufeu ex, PAF 232)…"
          className="flex-1 rounded-md border border-ink-700 bg-ink-800 px-3 py-2 text-sm text-parchment-100 placeholder:text-ink-600 focus:border-ember-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={searching || searchInput.trim().length < 2}
          className="shrink-0 rounded-md border border-ember-500/50 bg-ember-500/10 px-4 py-2 text-sm font-medium text-ember-400 transition-colors hover:bg-ember-500/20 disabled:opacity-40"
        >
          {searching ? "Recherche…" : "Chercher"}
        </button>
        {searchQuery && (
          <button
            type="button"
            onClick={clearSearch}
            className="shrink-0 rounded-md border border-ink-700 px-3 py-2 text-sm text-ink-600 transition-colors hover:border-ink-600 hover:text-parchment-100"
          >
            Effacer
          </button>
        )}
      </form>

      {searchQuery && (
        <section className="mb-8">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="font-display text-lg text-parchment-100">
              Résultats pour « {searchQuery} »
              <span className="ml-2 font-mono text-xs font-normal text-ink-600">
                {searchResults.length}
              </span>
            </h2>
          </div>

          {searchError && (
            <div className="mb-3 rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
              {searchError}
            </div>
          )}

          {searching && (
            <div className="rounded-md border border-dashed border-ink-700 p-6 text-center text-xs text-ink-600">
              Recherche en cours sur Vinted et eBay — ça peut prendre quelques secondes…
            </div>
          )}

          {!searching && !searchError && searchResults.length === 0 && (
            <div className="rounded-md border border-dashed border-ink-700 p-6 text-center text-xs text-ink-600">
              Aucune annonce trouvée pour ce terme pour l&apos;instant. Réessaie avec un
              nom légèrement différent, ou reviens plus tard.
            </div>
          )}

          <div className="flex flex-col gap-2">
            {searchResults.map((l) => (
              <ListingCard key={`${l.source}-${l.id}`} listing={l} />
            ))}
          </div>
        </section>
      )}

      {!searchQuery && indexStatus && indexStatus.series_pending > 0 && (
        <div className="mb-4 rounded-lg border border-ember-500/30 bg-ember-500/5 px-3 py-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs font-medium text-ember-400">
                Index des prix en construction — {indexStatus.progress_percent}%
              </p>
              <p className="mt-0.5 text-[11px] text-ink-600">
                {indexStatus.cards_in_index.toLocaleString("fr-FR")} cartes indexées ·{" "}
                {indexStatus.series_synced}/{indexStatus.series_known} séries. Les annonces
                sans prix seront recalculées au fur et à mesure.
              </p>
            </div>
            <button
              onClick={handleSyncPrices}
              disabled={syncing}
              className="shrink-0 rounded-md border border-ember-500/40 px-2.5 py-1 text-[11px] text-ember-400 transition-colors hover:bg-ember-500/10 disabled:opacity-50"
            >
              {syncing ? "Synchro…" : "Accélérer"}
            </button>
          </div>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-ink-700">
            <div
              className="h-full rounded-full bg-ember-500 transition-all duration-500"
              style={{ width: `${indexStatus.progress_percent}%` }}
            />
          </div>
        </div>
      )}

      {!searchQuery && (
      <>
      <div className="mb-3 flex gap-1 md:hidden">
        {(["vinted", "ebay"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setMobileTab(tab)}
            className={`flex-1 rounded-sm py-1.5 text-xs font-medium capitalize transition-colors ${
              mobileTab === tab
                ? "bg-ember-500/20 text-ember-400"
                : "bg-ink-800 text-ink-600"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-6 md:flex-row">
        <div className={mobileTab === "vinted" ? "block" : "hidden md:block"}>
          <ListingColumn
            source="vinted"
            listings={vinted}
            loading={loading}
            sortBy={sortBy}
            order={order}
            onSortChange={(f, o) => {
              setSortBy(f);
              setOrder(o);
            }}
          />
        </div>
        <div className={mobileTab === "ebay" ? "block" : "hidden md:block"}>
          <ListingColumn
            source="ebay"
            listings={ebay}
            loading={loading}
            sortBy={sortBy}
            order={order}
            onSortChange={(f, o) => {
              setSortBy(f);
              setOrder(o);
            }}
          />
        </div>
      </div>
      </>
      )}

      <div className="mt-10 space-y-1.5 border-t border-ink-800 pt-4 text-center text-[11px] text-ink-600">
        <p>
          * Scores de qualité = estimations automatiques indicatives, pas un grading
          professionnel (PSA/BGS/CGC).
        </p>
        <p>
          Prix de référence : ZebraDex (marché FR). La fourchette affichée est dérivée de la
          volatilité sur 7 jours, ce n&apos;est pas un historique de ventes conclues.
        </p>
        <p>Vérifie toujours l&apos;annonce et les photos avant d&apos;acheter.</p>
      </div>
    </main>
  );
}
