"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import CardDetailPanel from "@/components/CardDetailPanel";
import CardFilters, { EtatFiltres, FILTRES_VIDES } from "@/components/CardFilters";
import CardTile from "@/components/CardTile";
import {
  CardFilterValues,
  CardTheme,
  CatalogCard,
  fetchCardFilters,
  fetchCardThemes,
  fetchTrendingCards,
  searchCards,
} from "@/lib/api";

/**
 * Exploration du catalogue : chercher des cartes par theme, par prix, par
 * type, et voir lesquelles bougent.
 *
 * Complete le dashboard des annonces sans le remplacer. Les deux repondent a
 * deux questions differentes : « quelle carte vaut la peine » se decide ici,
 * « ou l'acheter au bon prix » sur le dashboard.
 */

const PAR_PAGE = 48;

export default function ExplorerPage() {
  const [filtres, setFiltres] = useState<EtatFiltres>(FILTRES_VIDES);
  const [filtresDebounces, setFiltresDebounces] = useState<EtatFiltres>(FILTRES_VIDES);
  const [valeurs, setValeurs] = useState<CardFilterValues | null>(null);
  const [themes, setThemes] = useState<CardTheme[]>([]);

  const [cartes, setCartes] = useState<CatalogCard[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState<string | null>(null);

  const [vogue, setVogue] = useState<CatalogCard[]>([]);
  const [carteOuverte, setCarteOuverte] = useState<number | null>(null);

  // La frappe dans le champ de recherche ne doit pas declencher une requete
  // par caractere : on attend que ca se stabilise.
  useEffect(() => {
    const minuteur = setTimeout(() => {
      setFiltresDebounces(filtres);
      setPage(0);
    }, 350);
    return () => clearTimeout(minuteur);
  }, [filtres]);

  useEffect(() => {
    fetchCardFilters().then(setValeurs).catch(() => setValeurs(null));
    fetchCardThemes()
      .then((d) => setThemes(d.themes))
      .catch(() => setThemes([]));
    fetchTrendingCards({ direction: "hausse", limit: 12 })
      .then((d) => setVogue(d.cartes))
      .catch(() => setVogue([]));
  }, []);

  const parametres = useMemo(() => {
    const f = filtresDebounces;
    const enNombre = (v: string) => (v.trim() === "" ? undefined : Number(v));
    return {
      q: f.q.trim() || undefined,
      theme: f.theme || undefined,
      rarity: f.rarity || undefined,
      series: f.series || undefined,
      priceMin: enNombre(f.priceMin),
      priceMax: enNombre(f.priceMax),
      trend: f.trend,
      withImage: f.withImageOnly ? true : undefined,
      sortBy: f.sortBy,
      order: f.order,
      limit: PAR_PAGE,
      offset: page * PAR_PAGE,
    };
  }, [filtresDebounces, page]);

  useEffect(() => {
    let annule = false;
    setChargement(true);
    setErreur(null);
    searchCards(parametres)
      .then((res) => {
        if (annule) return;
        setCartes(res.cartes);
        setTotal(res.total);
      })
      .catch((e) => {
        if (annule) return;
        setErreur(e instanceof Error ? e.message : String(e));
        setCartes([]);
        setTotal(0);
      })
      .finally(() => !annule && setChargement(false));
    return () => {
      annule = true;
    };
  }, [parametres]);

  const majFiltres = useCallback((modif: Partial<EtatFiltres>) => {
    setFiltres((actuels) => ({ ...actuels, ...modif }));
  }, []);

  const catalogueVide = valeurs !== null && valeurs.total_cards === 0;
  const dernierePage = Math.max(0, Math.ceil(total / PAR_PAGE) - 1);

  return (
    <main className="mx-auto max-w-7xl px-4 py-6">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl text-parchment-100">
            Explorer le catalogue
          </h1>
          <p className="mt-0.5 text-xs text-parchment-100/50">
            Chercher des cartes par thème, par budget et par type, et voir
            lesquelles bougent.
          </p>
        </div>
        <nav className="flex gap-2 text-xs">
          <Link
            href="/"
            className="rounded-sm border border-ink-700 px-2.5 py-1.5 text-parchment-100/70 transition-colors hover:border-ember-500/50"
          >
            Bonnes affaires
          </Link>
          <Link
            href="/settings"
            className="rounded-sm border border-ink-700 px-2.5 py-1.5 text-parchment-100/70 transition-colors hover:border-ember-500/50"
          >
            Réglages
          </Link>
        </nav>
      </header>

      {catalogueVide && (
        <p className="mb-5 rounded-md border border-ember-500/40 bg-ember-500/10 p-3 text-xs leading-relaxed text-ember-400">
          Le catalogue est encore vide. Ce n&apos;est pas une panne : il se
          remplit série par série depuis ZebraDex, au rythme volontairement
          lent imposé à la source. Lance une synchronisation depuis les
          réglages, puis reviens.
        </p>
      )}

      {vogue.length > 0 && (
        <section className="mb-6">
          <div className="mb-2 flex items-baseline justify-between gap-3">
            <h2 className="font-display text-base text-parchment-100">
              En vogue cette semaine
            </h2>
            <p className="text-[11px] text-parchment-100/40">
              Classé en pourcentage, pas en euros : +12 € sur une carte à 400 €
              n&apos;est pas une tendance.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-6">
            {vogue.map((carte) => (
              <CardTile
                key={`vogue-${carte.id}`}
                carte={carte}
                onSelect={(c) => setCarteOuverte(c.id)}
              />
            ))}
          </div>
        </section>
      )}

      <div className="flex flex-col gap-4 lg:flex-row">
        <CardFilters
          valeurs={valeurs}
          filtres={filtres}
          themes={themes}
          onChange={majFiltres}
          onReset={() => setFiltres(FILTRES_VIDES)}
        />

        <section className="min-w-0 flex-1">
          <div className="mb-2.5 flex items-baseline justify-between gap-3">
            <p className="text-xs text-parchment-100/55">
              {chargement
                ? "Recherche…"
                : `${total.toLocaleString("fr-FR")} carte${total > 1 ? "s" : ""} trouvée${total > 1 ? "s" : ""}`}
            </p>
            {total > PAR_PAGE && (
              <div className="flex items-center gap-1.5 text-xs">
                <button
                  type="button"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  className="rounded-sm border border-ink-700 px-2 py-0.5 text-parchment-100/70 disabled:opacity-30"
                >
                  ←
                </button>
                <span className="font-mono text-parchment-100/50">
                  {page + 1} / {dernierePage + 1}
                </span>
                <button
                  type="button"
                  disabled={page >= dernierePage}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded-sm border border-ink-700 px-2 py-0.5 text-parchment-100/70 disabled:opacity-30"
                >
                  →
                </button>
              </div>
            )}
          </div>

          {erreur && (
            <p className="rounded-md border border-rust-500/40 bg-rust-500/10 p-3 text-xs text-rust-400">
              {erreur}
            </p>
          )}

          {!erreur && !chargement && cartes.length === 0 && !catalogueVide && (
            <p className="rounded-md border border-ink-700 bg-ink-900 p-4 text-xs text-parchment-100/50">
              Aucune carte ne correspond à ces filtres. Élargis la fourchette de
              prix, ou retire le thème.
            </p>
          )}

          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
            {cartes.map((carte) => (
              <CardTile
                key={carte.id}
                carte={carte}
                onSelect={(c) => setCarteOuverte(c.id)}
              />
            ))}
          </div>
        </section>
      </div>

      {carteOuverte !== null && (
        <CardDetailPanel cardId={carteOuverte} onClose={() => setCarteOuverte(null)} />
      )}
    </main>
  );
}
