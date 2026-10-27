"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import CardDetailPanel from "@/components/CardDetailPanel";
import VisuelCarte from "@/components/VisuelCarte";
import { fetchCollection, retirerExemplaire, type CarteCollection, type Collection } from "@/lib/api";
import { formatEur } from "@/lib/format";

/**
 * « Ma collection » : ce qu'on possède, ce qu'on l'a payé, ce que ça vaut.
 *
 * La valeur est la cote ramenée à l'état de chaque exemplaire — la même
 * décote que pour juger une annonce. Une carte sans cote n'est pas comptée
 * pour zéro : le total le dit à côté, plutôt que de sous-estimer en silence.
 */
export default function MaCollectionPage() {
  const [donnees, setDonnees] = useState<Collection | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [carteOuverte, setCarteOuverte] = useState<number | null>(null);

  const charger = useCallback(() => {
    fetchCollection()
      .then(setDonnees)
      .catch((e) => setErreur(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(charger, [charger]);

  const totaux = donnees?.totaux;

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
          <Link href="/" className="font-display text-lg leading-none text-parchment-100">
            Radar
          </Link>
          <span className="text-ink-400">/</span>
          <span className="text-sm text-parchment-100">Ma collection</span>
          <div className="ml-auto flex gap-1.5">
            <Link
              href="/suivi"
              className="rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
            >
              ★ Ma liste
            </Link>
            <Link
              href="/explorer"
              className="rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
            >
              Catalogue
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 pb-16 pt-6">
        <h1 className="font-display text-2xl text-parchment-100">Ma collection</h1>
        <p className="mt-1 text-xs leading-relaxed text-ink-400">
          Les cartes que tu possèdes. Leur valeur est la cote ramenée à l&apos;état de chaque exemplaire ; la
          plus-value la compare à ce que tu as payé, frais compris.
        </p>

        {erreur && (
          <div className="mt-4 rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
            Impossible de charger ta collection. [{erreur}]
          </div>
        )}

        {!donnees && !erreur && (
          <div className="mt-4 flex flex-col gap-3">
            <div className="skeleton h-20" />
            <div className="skeleton h-28" />
          </div>
        )}

        {donnees && donnees.cartes.length === 0 && (
          <div className="mt-6 rounded-lg border border-dashed border-ink-700 px-4 py-10 text-center">
            <p className="text-sm text-parchment-100">Ta collection est vide.</p>
            <p className="mt-1 text-xs leading-relaxed text-ink-400">
              Sur la fiche d&apos;une carte du catalogue, clique « ＋ J&apos;ai cette carte ». Sur le radar, une
              annonce achetée se range avec « ✓ Je l&apos;ai achetée » : le prix payé et l&apos;état sont repris.
            </p>
            <Link
              href="/explorer"
              className="mt-4 inline-block rounded-md border border-moss-500/50 bg-moss-500/10 px-3 py-1.5 text-xs font-medium text-moss-400 hover:bg-moss-500/20"
            >
              Ouvrir le catalogue
            </Link>
          </div>
        )}

        {donnees && totaux && donnees.cartes.length > 0 && (
          <>
            <section className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Totaux">
              <Total titre="Valeur estimée" valeur={formatEur(totaux.valeur)} accent="text-parchment-100" />
              <Total titre="Payé" valeur={formatEur(totaux.paye)} accent="text-parchment-100" />
              <Total
                titre="Plus-value"
                valeur={`${totaux.plus_value > 0 ? "+" : ""}${formatEur(totaux.plus_value)}`}
                accent={totaux.plus_value >= 0 ? "text-moss-400" : "text-rust-400"}
              />
              <Total
                titre="Exemplaires"
                valeur={String(totaux.exemplaires)}
                accent="text-parchment-100"
              />
            </section>
            {(totaux.sans_cote > 0 || totaux.sans_prix_paye > 0) && (
              <p className="mt-2 text-[11px] leading-relaxed text-ink-400">
                {totaux.sans_cote > 0 &&
                  `${totaux.sans_cote} exemplaire${totaux.sans_cote > 1 ? "s" : ""} sans cote connue : hors valeur estimée. `}
                {totaux.sans_prix_paye > 0 &&
                  `${totaux.sans_prix_paye} exemplaire${totaux.sans_prix_paye > 1 ? "s" : ""} sans prix payé : hors plus-value.`}
              </p>
            )}

            {donnees.par_personnage.length > 0 && (
              <section className="mt-5" aria-label="Par personnage">
                <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-400">
                  Par personnage
                </p>
                <ul className="flex list-none flex-wrap gap-2 p-0">
                  {donnees.par_personnage.map((p) => (
                    <li key={p.slug}>
                      <Link
                        href={`/personnages/${p.slug}`}
                        title={`Toutes les cartes de ${p.nom}, et celles qui manquent à ta collection`}
                        className="flex items-baseline gap-2 rounded-md border border-ink-700 bg-ink-800/60 px-2.5 py-1.5 text-xs transition-colors hover:border-ember-500/60"
                      >
                        <span className="font-display text-sm text-parchment-100">{p.nom}</span>
                        <span className="text-ink-400">
                          {p.cartes} carte{p.cartes > 1 ? "s" : ""}
                          {p.exemplaires > p.cartes ? ` · ${p.exemplaires} ex.` : ""}
                        </span>
                        <span className="tabular font-mono text-parchment-100">{formatEur(p.valeur)}</span>
                        <span className="text-ember-400">→</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <ul className="mt-4 flex list-none flex-col gap-2 p-0">
              {donnees.cartes.map((carte) => (
                <Ligne
                  key={`${carte.card_code}-${carte.name_slug}`}
                  carte={carte}
                  onOuvrir={setCarteOuverte}
                  onRetire={charger}
                />
              ))}
            </ul>
          </>
        )}
      </main>

      {carteOuverte !== null && (
        <CardDetailPanel
          cardId={carteOuverte}
          onClose={() => {
            setCarteOuverte(null);
            charger(); // un exemplaire a pu être ajouté depuis la fiche
          }}
        />
      )}
    </>
  );
}

function Total({ titre, valeur, accent }: { titre: string; valeur: string; accent: string }) {
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-800/60 px-3 py-2.5">
      <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-400">{titre}</p>
      <p className={`tabular mt-0.5 font-mono text-lg ${accent}`}>{valeur}</p>
    </div>
  );
}

function Ligne({
  carte,
  onOuvrir,
  onRetire,
}: {
  carte: CarteCollection;
  onOuvrir: (id: number) => void;
  onRetire: () => void;
}) {
  const [occupe, setOccupe] = useState<number | null>(null);
  const ouvrir = () => carte.id !== null && onOuvrir(carte.id);

  async function retirer(id: number) {
    setOccupe(id);
    try {
      await retirerExemplaire(id);
      onRetire();
    } finally {
      setOccupe(null);
    }
  }

  return (
    <li className="rounded-lg border border-ink-700 bg-ink-800/60 p-3">
      <div className="flex gap-3">
        <button
          type="button"
          onClick={ouvrir}
          disabled={carte.id === null}
          className="relative h-24 w-[68px] shrink-0 overflow-hidden rounded-md bg-ink-700 ring-1 ring-ink-600"
          aria-label={`Ouvrir la fiche de ${carte.display_name ?? carte.name_slug}`}
        >
          <VisuelCarte
            src={carte.image_url}
            alt={carte.display_name ?? carte.name_slug}
            sizes="68px"
            repli={() => (
              <span className="flex h-full items-center justify-center px-1 text-center text-[9px] text-ink-400">
                pas de visuel
              </span>
            )}
          />
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <button
              type="button"
              onClick={ouvrir}
              className="text-left text-sm font-medium text-parchment-100 hover:text-ember-400"
            >
              {carte.display_name}
            </button>
            <span className="tabular shrink-0 font-mono text-sm text-parchment-100">{formatEur(carte.valeur)}</span>
          </div>
          <p className="font-mono text-[11px] text-ink-400">
            {carte.card_code ?? "—"}
            {carte.series_name ? ` · ${carte.series_name}` : ""}
            {" · cote "}
            {carte.price_eur != null ? formatEur(carte.price_eur) : "inconnue"}
          </p>
          {carte.introuvable && (
            <p className="mt-1 text-[11px] text-rust-400">Cette carte n&apos;est plus dans le catalogue : sans cote.</p>
          )}

          <ul className="mt-1.5 flex list-none flex-col gap-1 p-0">
            {carte.exemplaires.map((ex) => (
              <li key={ex.id} className="flex flex-wrap items-center gap-x-2 text-[11px] text-ink-400">
                <span className="rounded bg-ink-700 px-1.5 py-0.5 font-semibold text-parchment-100">
                  {ex.etat ?? "état ?"}
                </span>
                <span>payé {ex.prix_paye != null ? formatEur(ex.prix_paye) : "—"}</span>
                <span>vaut {ex.valeur != null ? formatEur(ex.valeur) : "—"}</span>
                {ex.plus_value != null && (
                  <span className={ex.plus_value >= 0 ? "text-moss-400" : "text-rust-400"}>
                    {ex.plus_value > 0 ? "+" : ""}
                    {formatEur(ex.plus_value)}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => retirer(ex.id)}
                  disabled={occupe === ex.id}
                  className="ml-auto text-ink-400 underline decoration-ink-600 underline-offset-2 hover:text-rust-400 disabled:opacity-40"
                  title="Retirer cet exemplaire de ta collection (vendu, échangé, erreur)"
                >
                  retirer
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </li>
  );
}
