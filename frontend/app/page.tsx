"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  fetchListings,
  triggerCheckNow,
  type Listing,
  type SortField,
  type SortOrder,
} from "@/lib/api";
import ListingColumn from "@/components/ListingColumn";

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

  useEffect(() => {
    load();
    const interval = setInterval(load, 60_000); // rafraîchit l'affichage 1x/min
    return () => clearInterval(interval);
  }, [load]);

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

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl text-parchment-100">
            Chasse aux bonnes affaires
          </h1>
          <p className="text-xs text-ink-600">
            Cartes Pokémon FR · Vinted &amp; eBay, comparées à Cardmarket &amp; ZebraDex
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

      {/* Mobile : onglets pour basculer entre les deux colonnes */}
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

      <p className="mt-8 text-center text-[11px] text-ink-600">
        * Les scores de qualité photo sont des estimations indicatives générées
        automatiquement — pas un grading professionnel (PSA/BGS/CGC).
      </p>
    </main>
  );
}
