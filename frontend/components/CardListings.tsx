"use client";

import { useEffect, useState } from "react";
import { CardListing, CardListingsResult, fetchCardListings } from "@/lib/api";
import { formatEur } from "@/lib/format";
import { useModeEvaluation } from "@/lib/mode";

/**
 * Les annonces en vente pour une carte du catalogue.
 *
 * C'est le pont entre les deux moities de l'app : on repere une carte dans le
 * catalogue, et on voit immediatement s'il y a quelque chose a prendre, sans
 * repartir fouiller le tableau de bord.
 *
 * Les photos affichees sont celles du VENDEUR, pas l'illustration officielle.
 * Pour decider d'acheter c'est ce qui compte : on voit l'exemplaire reel, son
 * centrage, ses bords, son etat. L'illustration officielle, elle, est en haut
 * de la fiche et sert a identifier la carte, pas a juger la marchandise.
 */

function Score({ score, douteux }: { score: number | null; douteux: boolean }) {
  if (score === null) {
    return (
      <span className="shrink-0 rounded-sm border border-ink-600 px-1.5 py-0.5 font-mono text-[10px] text-parchment-100/60">
        non noté
      </span>
    );
  }

  // Un score se calcule contre le prix de reference d'une carte PRECISE.
  // Quand on n'est pas sur que l'annonce porte bien sur cette carte-la, le
  // chiffre reste affiche — il n'est pas faux, il est juste conditionnel —
  // mais sans la couleur qui invite a y croire. Un 86/100 vert sur une
  // carte mal identifiee est exactement le piege qu'on veut eviter.
  const ton = douteux
    ? "border-ink-600 bg-ink-800 text-parchment-100/65"
    : score >= 80
      ? "border-moss-500/40 bg-moss-500/10 text-moss-400"
      : score >= 60
        ? "border-ember-500/40 bg-ember-500/10 text-ember-400"
        : "border-ink-600 bg-ink-800 text-parchment-100/65";

  const titre = douteux
    ? "Score d'affaire calculé contre le prix d'une carte dont l'identification est incertaine : à vérifier sur la photo avant d'y croire."
    : "Score d'affaire : plus il est haut, plus l'écart avec le prix de référence est favorable.";

  return (
    <span
      title={titre}
      className={`shrink-0 rounded-sm border px-1.5 py-0.5 font-mono text-[10px] ${ton}`}
    >
      {score.toFixed(0)}/100
    </span>
  );
}

function Annonce({ annonce }: { annonce: CardListing }) {
  const mode = useModeEvaluation();
  const [index, setIndex] = useState(0);
  const photos = annonce.photo_urls ?? [];
  const photo = photos[index];
  const douteux = annonce.price_match_confidence === "low";

  return (
    <li className="rounded-sm border border-ink-700 bg-ink-950 p-2">
      <div className="flex gap-2.5">
        <div className="relative h-[94px] w-[67px] shrink-0 overflow-hidden rounded-sm border border-ink-700 bg-ink-900">
          {photo ? (
            /* Balise <img> nue, pas next/image : next/image refuse tout
               hote absent de l'allowlist de next.config.js, et ces photos
               viennent de CDN qui repartissent sur des sous-domaines
               variables. Ici une photo qui ne s'affiche pas, c'est la
               decision d'achat qu'on perd ; aucun gain d'optimisation ne
               vaut ce risque. */
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={photo}
              alt={`Photo ${index + 1} de « ${annonce.title} »`}
              className="h-full w-full object-cover"
              loading="lazy"
            />
          ) : (
            <span className="flex h-full w-full items-center justify-center p-1 text-center text-[9px] leading-tight text-parchment-100/60">
              Pas de photo
            </span>
          )}
          {photos.length > 1 && (
            <button
              type="button"
              onClick={() => setIndex((i) => (i + 1) % photos.length)}
              aria-label="Photo suivante"
              className="absolute bottom-0 right-0 bg-ink-950/85 px-1 font-mono text-[9px] text-parchment-100/70 hover:text-ember-400"
            >
              {index + 1}/{photos.length}
            </button>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-start justify-between gap-2">
            <p className="line-clamp-2 text-[11px] leading-snug text-parchment-100/85">
              {annonce.title}
            </p>
            <Score score={annonce.deal_score} douteux={douteux} />
          </div>

          {/* Le prix affiché, puis ce que l'achat coûte vraiment : sur Vinted,
              la protection acheteur et le port s'ajoutent au panier. */}
          <p className="font-mono text-sm text-parchment-100">
            {formatEur(annonce.price_eur)}
            {Math.abs(annonce.total_eur - annonce.price_eur) >= 0.01 && (
              <span
                className="text-[10px] text-parchment-100/60"
                title={
                  annonce.total_detail
                    ? `Protection acheteur ${formatEur(annonce.total_detail.protection)} · port ${formatEur(annonce.total_detail.port)}${annonce.total_detail.port_estime ? " (estimé)" : ""}`
                    : undefined
                }
              >
                {" "}≈ {formatEur(annonce.total_eur)} payé
              </span>
            )}
          </p>
          {annonce.alerte && (
            <p className="text-[10px] leading-snug text-ember-400">⚠ {annonce.alerte}</p>
          )}
          {annonce.non_comparable && (
            <p className="text-[10px] leading-snug text-sky-300">{annonce.non_comparable}</p>
          )}

          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[10px] text-parchment-100/60">
            {annonce.source && (
              <span className="uppercase tracking-wide">{annonce.source}</span>
            )}
            {mode === "collection" && annonce.savings_eur != null ? (
              <span
                className={`font-mono ${annonce.savings_eur >= 0 ? "text-moss-400" : "text-rust-400"}`}
                title="Par rapport à la cote, protection acheteur et port compris"
              >
                {annonce.savings_eur >= 0
                  ? `économie ≈ ${formatEur(annonce.savings_eur, 0)}`
                  : `${formatEur(-annonce.savings_eur, 0)} plus cher que la cote`}
              </span>
            ) : annonce.margin_net_eur !== null && (
              <span
                className={`font-mono ${
                  annonce.margin_net_eur >= 0 ? "text-moss-400" : "text-rust-400"
                }`}
              >
                marge nette ≈ {formatEur(annonce.margin_net_eur, 0)}
              </span>
            )}
            {annonce.condition_tier && <span>état {annonce.condition_tier}</span>}
            {annonce.seller_reliability_score !== null && (
              <span title="Fiabilité du vendeur : nombre d'avis et note moyenne">fiabilité vendeur {annonce.seller_reliability_score.toFixed(0)}/100</span>
            )}
            {douteux && (
              <span
                className="text-rust-400"
                title="Le rapprochement entre le titre de l'annonce et cette carte est incertain : vérifiez la photo avant d'acheter."
              >
                identification incertaine
              </span>
            )}
          </div>

          <a
            href={annonce.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-0.5 self-start rounded-sm border border-ember-500/50 bg-ember-500/10 px-2 py-0.5 text-[11px] text-ember-400 transition-colors hover:bg-ember-500/20"
          >
            Voir l&apos;annonce ↗
          </a>
        </div>
      </div>
    </li>
  );
}

export default function CardListings({ cardId }: { cardId: number }) {
  const [donnees, setDonnees] = useState<CardListingsResult | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [chargement, setChargement] = useState(true);

  useEffect(() => {
    let annule = false;
    setChargement(true);
    setDonnees(null);
    setErreur(null);
    fetchCardListings(cardId)
      .then((d) => {
        if (!annule) setDonnees(d);
      })
      .catch((e) => {
        if (!annule) setErreur(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!annule) setChargement(false);
      });
    return () => {
      annule = true;
    };
  }, [cardId]);

  return (
    <div className="border-t border-ink-700 pt-3">
      <h3 className="mb-1.5 text-[11px] uppercase tracking-wide text-parchment-100/60">
        En vente en ce moment
      </h3>

      {chargement && (
        <p className="text-[11px] text-parchment-100/60">Recherche des annonces…</p>
      )}

      {erreur && (
        <p className="rounded-sm border border-rust-500/40 bg-rust-500/10 p-2 text-[11px] text-rust-400">
          {erreur}
        </p>
      )}

      {!chargement && !erreur && donnees?.count === 0 && (
        <p className="text-[11px] leading-relaxed text-parchment-100/60">
          Aucune annonce pour cette carte en ce moment. Ce n&apos;est pas une
          panne : la collecte ne retient que ce qui est réellement en vente, et
          à un instant donné la plupart des cartes ne le sont pas.
        </p>
      )}

      {donnees && donnees.count > 0 && (
        <>
          <p className="mb-2 font-mono text-[10px] text-parchment-100/60">
            {donnees.count} annonce{donnees.count > 1 ? "s" : ""} ·{" "}
            {donnees.reference_price_eur === null
              ? "pas de prix de référence, donc pas de score"
              : `cote ${formatEur(donnees.reference_price_eur)}`}{" "}
            · photos du vendeur, donc de l&apos;exemplaire réel
          </p>
          <ul className="flex list-none flex-col gap-2 p-0">
            {donnees.listings.map((a) => (
              <Annonce key={a.id} annonce={a} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
