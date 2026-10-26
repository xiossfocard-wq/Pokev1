"use client";

import VisuelCarte from "./VisuelCarte";
import { CatalogCard } from "@/lib/api";
import { formatEur, formatFourchette, formatNombre } from "@/lib/format";
import { useCartesSuivies } from "@/lib/suivi";

/**
 * Une carte du catalogue, avec son visuel.
 *
 * L'image est le point de depart de la demande : « je veux voir l'image de
 * chaque carte dans la recherche ». Toutes les cartes n'en ont pas encore
 * (l'enrichissement est progressif, et certaines restent introuvables) : on
 * affiche alors un cadre explicite plutot que de masquer la carte. Un
 * catalogue de prix sans visuel reste utile ; un catalogue amoindri parce
 * qu'une image manque ne l'est pas.
 */

const COULEURS_TENDANCE: Record<string, string> = {
  hausse: "text-moss-400 border-moss-500/40 bg-moss-500/10",
  baisse: "text-rust-400 border-rust-500/40 bg-rust-500/10",
  stable: "text-parchment-100/60 border-ink-600 bg-ink-800",
  inconnu: "text-parchment-100/60 border-ink-700 bg-ink-900",
};

function FlecheTendance({ direction }: { direction: string }) {
  if (direction === "hausse") return <span aria-hidden>▲</span>;
  if (direction === "baisse") return <span aria-hidden>▼</span>;
  if (direction === "stable") return <span aria-hidden>●</span>;
  return <span aria-hidden>·</span>;
}

export default function CardTile({
  carte,
  onSelect,
}: {
  carte: CatalogCard;
  onSelect?: (carte: CatalogCard) => void;
}) {
  const tendance = carte.trend_7d;
  const { budgets } = useCartesSuivies();
  const suivie = budgets.has(carte.id);
  const couleur = COULEURS_TENDANCE[tendance.direction] ?? COULEURS_TENDANCE.inconnu;

  // Une affaire se voit depuis la grille, pas seulement en ouvrant la fiche.
  // Le ton suit le meilleur score pour que l'œil trie sans lire.
  const annonces = carte.listings_count;
  const meilleur = carte.best_deal_score;
  const tonAffaire =
    meilleur !== null && meilleur >= 80
      ? "border-moss-500/50 bg-moss-500/15 text-moss-400"
      : meilleur !== null && meilleur >= 60
        ? "border-ember-500/50 bg-ember-500/15 text-ember-400"
        : "border-ink-600 bg-ink-900/90 text-parchment-100/60";

  return (
    <button
      type="button"
      onClick={() => onSelect?.(carte)}
      className="group flex flex-col overflow-hidden rounded-md border border-ink-700 bg-ink-900 text-left transition-colors hover:border-ember-500/60"
    >
      <div className="relative aspect-[63/88] w-full bg-ink-950">
        <VisuelCarte
          src={carte.image_url}
          alt={carte.display_name}
          sizes="(max-width: 640px) 45vw, (max-width: 1024px) 30vw, 200px"
          repli={(raison) => (
            <div className="flex h-full w-full flex-col items-center justify-center gap-1 p-2 text-center">
              <span className="text-2xl opacity-30" aria-hidden>
                ▭
              </span>
              <span className="text-[10px] leading-tight text-parchment-100/60">
                {raison === "absent" ? "Visuel pas encore récupéré" : "Visuel indisponible"}
              </span>
            </div>
          )}
        />

        {annonces > 0 && (
          <span
            title={
              meilleur !== null
                ? `${annonces} annonce${annonces > 1 ? "s" : ""} en vente · meilleur score d'affaire ${meilleur.toFixed(0)}/100`
                : `${annonces} annonce${annonces > 1 ? "s" : ""} en vente`
            }
            className={`absolute left-1.5 top-1.5 rounded-sm border px-1.5 py-0.5 font-mono text-[10px] backdrop-blur-sm ${tonAffaire}`}
          >
            {annonces} en vente
            {meilleur !== null && ` · ${meilleur.toFixed(0)}`}
          </span>
        )}

        {suivie && (
          <span
            title={
              budgets.get(carte.id) != null
                ? `Dans ta liste · budget ${formatEur(budgets.get(carte.id) as number)}`
                : "Dans ta liste"
            }
            className="absolute right-1.5 top-1.5 rounded-sm border border-amber-300/60 bg-ink-950/80 px-1.5 py-0.5 text-[11px] text-amber-200 backdrop-blur-sm"
          >
            ★
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-1.5 p-2.5">
        <p className="font-display text-sm leading-tight text-parchment-100">
          {carte.display_name}
        </p>

        <p className="text-[11px] text-parchment-100/60">
          {carte.card_code ? `${carte.card_code} · ` : ""}
          {carte.series_name ?? "Série inconnue"}
        </p>

        {/* Seule la carte ANGLAISE est signalée. Marquer aussi les
            françaises couvrirait toute la grille d'étiquettes pour dire
            « normal » : une pastille qui s'allume partout ne se lit plus.
            Le titre au survol porte la raison exacte. */}
        {carte.language === "en" && (
          <p
            className="inline-flex w-fit items-center gap-1 rounded border border-ink-600 bg-ink-800 px-1.5 py-0.5 text-[10px] text-parchment-100/65"
            title={carte.language_note ?? undefined}
          >
            <span aria-hidden>EN</span>
            <span>nom anglais</span>
          </p>
        )}

        {carte.rarity && (
          <p className="text-[11px] text-ember-400/80">{carte.rarity}</p>
        )}

        <div className="mt-auto flex items-end justify-between gap-2 pt-1.5">
          <div>
            {/* Une carte peut etre au catalogue sans qu'on connaisse son
                prix : la liste officielle dit quelles cartes existent, pas
                ce qu'elles valent. On l'ecrit, au lieu d'afficher un
                « 0,00 € » qui se lirait comme « cette carte ne vaut rien ». */}
            {carte.price_eur === null ? (
              <p className="text-xs italic text-parchment-100/60">
                Prix de référence inconnu
              </p>
            ) : (
              <p className="font-mono text-base text-parchment-100">
                {formatEur(carte.price_eur)}
              </p>
            )}
            {carte.price_low_eur !== null && carte.price_high_eur !== null && (
              // Titre au survol : la fourchette est derivee de la volatilite
              // recente, pas des ventes conclues. Le dire la ou le chiffre
              // est lu, pas seulement dans une note de bas de page.
              <p
                className="font-mono text-[10px] text-parchment-100/60"
                title="Fourchette dérivée de la volatilité récente, pas des ventes réellement conclues"
              >
                {formatFourchette(carte.price_low_eur, carte.price_high_eur)}
              </p>
            )}
          </div>

          <span
            className={`shrink-0 rounded-sm border px-1.5 py-0.5 font-mono text-[10px] ${couleur}`}
            title={tendance.label}
          >
            <FlecheTendance direction={tendance.direction} />{" "}
            {tendance.variation_pct !== null
              ? `${tendance.variation_pct > 0 ? "+" : ""}${formatNombre(tendance.variation_pct, 1)} %`
              : "—"}
          </span>
        </div>
      </div>
    </button>
  );
}
