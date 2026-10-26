"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import CardDetailPanel from "@/components/CardDetailPanel";
import SuiviCarte from "@/components/SuiviCarte";
import VisuelCarte from "@/components/VisuelCarte";
import type { CarteSuivie } from "@/lib/api";
import { formatEur } from "@/lib/format";
import { rechargerListe, useCartesSuivies } from "@/lib/suivi";

/**
 * « Ma liste » : les cartes que l'on cherche, son budget pour chacune, et ce
 * qui est en vente en ce moment. Les cartes qui ont une annonce dans le
 * budget viennent en tête : c'est la question qu'on se pose en ouvrant la
 * page.
 */
export default function MaListePage() {
  const { liste } = useCartesSuivies();
  const [erreur, setErreur] = useState<string | null>(null);
  const [carteOuverte, setCarteOuverte] = useState<number | null>(null);

  // Les annonces bougent entre deux visites : on recharge à l'ouverture.
  useEffect(() => {
    rechargerListe().catch((e) => setErreur(e instanceof Error ? e.message : String(e)));
  }, []);

  const dansLeBudget = (liste ?? []).filter((e) => (e.annonces?.dans_le_budget ?? 0) > 0).length;

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
          <Link href="/" className="font-display text-lg leading-none text-parchment-100">
            Radar
          </Link>
          <span className="text-ink-400">/</span>
          <span className="text-sm text-parchment-100">Ma liste</span>
          <Link
            href="/explorer"
            className="ml-auto rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
          >
            Catalogue
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 pb-16 pt-6">
        <h1 className="font-display text-2xl text-parchment-100">Ma liste</h1>
        <p className="mt-1 text-xs leading-relaxed text-ink-400">
          Les cartes que tu cherches, avec ton budget : le coût réel maximum, protection acheteur et port compris.
          Une annonce sous ce budget ressort sur le radar (★ dans ton budget) et t&apos;envoie une alerte, quel que
          soit son score.
        </p>

        {erreur && (
          <div className="mt-4 rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
            Impossible de charger ta liste. [{erreur}]
          </div>
        )}

        {liste === null && !erreur && (
          <div className="mt-4 flex flex-col gap-3">
            <div className="skeleton h-28" />
            <div className="skeleton h-28" />
          </div>
        )}

        {liste !== null && liste.length === 0 && (
          <div className="mt-6 rounded-lg border border-dashed border-ink-700 px-4 py-10 text-center">
            <p className="text-sm text-parchment-100">Ta liste est vide.</p>
            <p className="mt-1 text-xs text-ink-400">
              Ouvre une carte dans le catalogue et clique « ☆ Suivre ».
            </p>
            <Link
              href="/explorer"
              className="mt-4 inline-block rounded-md border border-amber-300/50 bg-amber-300/10 px-3 py-1.5 text-xs font-medium text-amber-200 hover:bg-amber-300/20"
            >
              Ouvrir le catalogue
            </Link>
          </div>
        )}

        {liste !== null && liste.length > 0 && (
          <>
            <p className="mt-4 font-mono text-[11px] text-ink-400">
              {liste.length} carte{liste.length > 1 ? "s" : ""} suivie{liste.length > 1 ? "s" : ""}
              {dansLeBudget > 0 && (
                <span className="text-amber-200">
                  {" "}· {dansLeBudget} avec une annonce dans ton budget
                </span>
              )}
            </p>
            <ul className="mt-2 flex list-none flex-col gap-2 p-0">
              {liste.map((entree) => (
                <Ligne
                  key={`${entree.card_code}-${entree.name_slug}`}
                  entree={entree}
                  onOuvrir={setCarteOuverte}
                />
              ))}
            </ul>
          </>
        )}
      </main>

      {carteOuverte !== null && (
        <CardDetailPanel cardId={carteOuverte} onClose={() => setCarteOuverte(null)} />
      )}
    </>
  );
}

function Ligne({ entree, onOuvrir }: { entree: CarteSuivie; onOuvrir: (id: number) => void }) {
  if (entree.introuvable || entree.id === null) {
    return (
      <li className="rounded-lg border border-ink-700 bg-ink-800/60 p-3 text-xs text-ink-400">
        <span className="font-mono text-parchment-100">{entree.card_code ?? "—"}</span> · {entree.name_slug} : cette
        carte n&apos;est plus dans le catalogue. Elle réapparaîtra quand le catalogue la retrouvera.
      </li>
    );
  }
  const annonces = entree.annonces;
  const moinsChere = annonces?.moins_chere;
  const enBudget = (annonces?.dans_le_budget ?? 0) > 0;
  const lienSur = moinsChere && /^https?:\/\//i.test(moinsChere.url) ? moinsChere.url : undefined;

  return (
    <li
      className={`rounded-lg border bg-ink-800/60 p-3 ${
        enBudget ? "border-amber-300/60 ring-1 ring-amber-300/30" : "border-ink-700"
      }`}
    >
      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => onOuvrir(entree.id as number)}
          className="relative h-24 w-[68px] shrink-0 overflow-hidden rounded-md bg-ink-700 ring-1 ring-ink-600"
          aria-label={`Ouvrir la fiche de ${entree.display_name ?? entree.name_slug}`}
        >
          <VisuelCarte
            src={entree.image_url}
            alt={entree.display_name ?? entree.name_slug}
            sizes="68px"
            repli={() => (
              <span className="flex h-full items-center justify-center px-1 text-center text-[9px] text-ink-400">
                pas de visuel
              </span>
            )}
          />
        </button>

        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => onOuvrir(entree.id as number)}
            className="text-left text-sm font-medium text-parchment-100 hover:text-ember-400"
          >
            {entree.display_name}
          </button>
          <p className="font-mono text-[11px] text-ink-400">
            {entree.card_code ?? "—"}
            {entree.series_name ? ` · ${entree.series_name}` : ""}
          </p>
          <p className="mt-1 text-[11px] text-ink-400">
            cote{" "}
            <span className="tabular font-mono text-parchment-100">
              {entree.price_eur != null ? formatEur(entree.price_eur) : "inconnue"}
            </span>
          </p>

          <p className="mt-1.5 text-xs">
            {!annonces || annonces.nombre === 0 ? (
              <span className="text-ink-400">Aucune annonce en vente pour l&apos;instant.</span>
            ) : (
              <>
                <span className="text-parchment-100">
                  {annonces.nombre} annonce{annonces.nombre > 1 ? "s" : ""}
                </span>
                {entree.prix_max !== null && (
                  <span className={enBudget ? "text-amber-200" : "text-ink-400"}>
                    {" "}· {annonces.dans_le_budget} dans ton budget
                  </span>
                )}
                {moinsChere && (
                  <span className="mt-0.5 block text-ink-400">
                    la moins chère :{" "}
                    <a
                      href={lienSur}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-parchment-100 underline decoration-ink-600 underline-offset-2 hover:text-ember-400"
                    >
                      ≈ {formatEur(moinsChere.cout_eur)} payé
                    </a>{" "}
                    ({formatEur(moinsChere.price_eur)} affiché
                    {moinsChere.condition_tier ? `, état ${moinsChere.condition_tier}` : ""},{" "}
                    {moinsChere.source === "ebay" ? "eBay" : "Vinted"})
                  </span>
                )}
              </>
            )}
          </p>
        </div>
      </div>

      <div className="mt-2.5">
        <SuiviCarte cardId={entree.id} cote={entree.price_eur ?? null} initial={{ prix_max: entree.prix_max }} />
      </div>
    </li>
  );
}
